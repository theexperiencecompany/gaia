"""Unit tests for VFS Compaction Middleware.

Tests the VFSCompactionMiddleware that intercepts tool outputs
and compacts large ones to VFS storage.
"""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command

from app.agents.middleware.vfs_compaction import VFSCompactionMiddleware
from app.constants.summarization import MIN_COMPACTION_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_ID = "test_user_123"
THREAD_ID = "thread_abc"
CONVERSATION_ID = "conv_xyz"
SUBAGENT_ID = "sub_agent_1"


def _make_tool_request(
    tool_name: str = "test_tool",
    tool_call_id: str = "call_1",
    args: dict[str, Any] | None = None,
    context_messages: list[Any] | None = None,
    user_id: str = USER_ID,
    thread_id: str = THREAD_ID,
    vfs_session_id: str | None = CONVERSATION_ID,
    subagent_id: str | None = SUBAGENT_ID,
    agent_name: str = "executor",
) -> MagicMock:
    """Create a mock ToolCallRequest with the expected structure."""
    request = MagicMock(spec=ToolCallRequest)
    request.tool_call = {
        "name": tool_name,
        "args": args or {},
        "id": tool_call_id,
    }
    # State with messages for context usage calc
    state = MagicMock()
    state.get.side_effect = lambda k, d=None: context_messages if k == "messages" else d
    request.state = state

    # Runtime with config
    runtime = MagicMock()
    configurable: dict[str, Any] = {
        "user_id": user_id,
        "thread_id": thread_id,
        "subagent_id": subagent_id,
    }
    if vfs_session_id is not None:
        configurable["vfs_session_id"] = vfs_session_id

    runtime.config = {
        "configurable": configurable,
        "metadata": {"agent_name": agent_name},
    }
    request.runtime = runtime

    return request


def _make_tool_message(
    content: str, tool_call_id: str = "call_1", name: str = "test_tool"
) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, name=name)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVFSCompactionInit:
    def test_defaults(self) -> None:
        mw = VFSCompactionMiddleware()
        assert mw.compaction_threshold == pytest.approx(0.65)
        assert mw.max_output_chars == 20000
        assert mw.always_persist_tools == []
        assert mw.context_window == 128000
        assert mw.excluded_tools == set()

    def test_custom_values(self) -> None:
        mw = VFSCompactionMiddleware(
            compaction_threshold=0.5,
            max_output_chars=10000,
            always_persist_tools=["search_tool"],
            context_window=200000,
            excluded_tools={"small_tool"},
        )
        assert mw.compaction_threshold == pytest.approx(0.5)
        assert mw.max_output_chars == 10000
        assert mw.always_persist_tools == ["search_tool"]
        assert mw.context_window == 200000
        assert mw.excluded_tools == {"small_tool"}

    def test_vfs_lazy(self) -> None:
        mw = VFSCompactionMiddleware()
        assert mw._vfs is None


# ---------------------------------------------------------------------------
# _get_vfs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetVfs:
    @patch(
        "app.agents.middleware.vfs_compaction.get_vfs",
        new_callable=AsyncMock,
    )
    async def test_lazy_loads_vfs(self, mock_get: AsyncMock) -> None:
        mock_vfs = AsyncMock()
        mock_get.return_value = mock_vfs
        mw = VFSCompactionMiddleware()
        result = await mw._get_vfs()
        assert result is mock_vfs
        mock_get.assert_called_once()

    async def test_cached_vfs(self) -> None:
        mw = VFSCompactionMiddleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        result = await mw._get_vfs()
        assert result is mock_vfs

    @patch(
        "app.agents.middleware.vfs_compaction.get_vfs",
        new_callable=AsyncMock,
        return_value=None,
    )
    async def test_none_vfs_raises(self, mock_get: AsyncMock) -> None:
        mw = VFSCompactionMiddleware()
        with pytest.raises(RuntimeError, match="VFS service is not available"):
            await mw._get_vfs()


# ---------------------------------------------------------------------------
# _get_context_usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetContextUsage:
    def test_no_state(self) -> None:
        mw = VFSCompactionMiddleware(context_window=100000)
        request = MagicMock(spec=ToolCallRequest)
        request.state = None
        assert mw._get_context_usage(request) == pytest.approx(0.0)

    def test_empty_messages(self) -> None:
        mw = VFSCompactionMiddleware(context_window=100000)
        request = MagicMock(spec=ToolCallRequest)
        state = MagicMock()
        state.get.return_value = []
        request.state = state
        assert mw._get_context_usage(request) == pytest.approx(0.0)

    def test_calculates_usage(self) -> None:
        mw = VFSCompactionMiddleware(context_window=1000)
        request = MagicMock(spec=ToolCallRequest)
        # 4000 chars = ~1000 tokens = 100% of 1000 token window
        msgs = [HumanMessage(content="x" * 4000)]
        state = MagicMock()
        state.get.return_value = msgs
        request.state = state
        usage = mw._get_context_usage(request)
        assert usage == pytest.approx(1.0, abs=0.01)

    def test_caps_at_1(self) -> None:
        mw = VFSCompactionMiddleware(context_window=100)
        request = MagicMock(spec=ToolCallRequest)
        msgs = [HumanMessage(content="x" * 10000)]
        state = MagicMock()
        state.get.return_value = msgs
        request.state = state
        assert mw._get_context_usage(request) == pytest.approx(1.0)

    def test_exception_returns_zero(self) -> None:
        mw = VFSCompactionMiddleware()
        request = MagicMock(spec=ToolCallRequest)
        request.state = MagicMock()
        request.state.get.side_effect = RuntimeError("boom")
        assert mw._get_context_usage(request) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _should_compact
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShouldCompact:
    def test_excluded_tool(self) -> None:
        mw = VFSCompactionMiddleware(excluded_tools={"skip_me"})
        msg = _make_tool_message("x" * 50000)
        should, reason = mw._should_compact(msg, "skip_me", 0.0)
        assert should is False
        assert reason == ""

    def test_always_persist_tool(self) -> None:
        mw = VFSCompactionMiddleware(always_persist_tools=["persist_me"])
        msg = _make_tool_message("tiny")
        should, reason = mw._should_compact(msg, "persist_me", 0.0)
        assert should is True
        assert reason == "always_persist_tool"

    def test_small_output_not_compacted(self) -> None:
        mw = VFSCompactionMiddleware()
        msg = _make_tool_message("x" * (MIN_COMPACTION_SIZE - 1))
        should, reason = mw._should_compact(msg, "some_tool", 0.0)
        assert should is False

    def test_large_output_compacted(self) -> None:
        mw = VFSCompactionMiddleware(max_output_chars=MIN_COMPACTION_SIZE + 50)
        msg = _make_tool_message("x" * (MIN_COMPACTION_SIZE + 100))
        should, reason = mw._should_compact(msg, "some_tool", 0.0)
        assert should is True
        assert "large_output" in reason

    def test_context_threshold_compaction(self) -> None:
        mw = VFSCompactionMiddleware(compaction_threshold=0.5)
        # Content bigger than MIN_COMPACTION_SIZE but smaller than max_output_chars
        msg = _make_tool_message("x" * (MIN_COMPACTION_SIZE + 100))
        should, reason = mw._should_compact(msg, "some_tool", 0.6)
        assert should is True
        assert "context_threshold" in reason

    def test_below_threshold_not_compacted(self) -> None:
        mw = VFSCompactionMiddleware(compaction_threshold=0.65, max_output_chars=50000)
        msg = _make_tool_message("x" * (MIN_COMPACTION_SIZE + 100))
        should, reason = mw._should_compact(msg, "some_tool", 0.3)
        assert should is False


# ---------------------------------------------------------------------------
# _create_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateSummary:
    def test_json_list_summary(self) -> None:
        mw = VFSCompactionMiddleware()
        data = json.dumps([{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])
        result = mw._create_summary(data, "search")
        assert "4 items" in result
        assert "[search]" in result

    def test_json_dict_summary(self) -> None:
        mw = VFSCompactionMiddleware()
        data = json.dumps({"key1": "val1", "key2": "val2"})
        result = mw._create_summary(data, "fetch")
        assert "keys" in result
        assert "[fetch]" in result

    def test_plain_text_short(self) -> None:
        mw = VFSCompactionMiddleware()
        result = mw._create_summary("short content", "tool")
        assert result == "[tool] short content"

    def test_plain_text_long_truncated(self) -> None:
        mw = VFSCompactionMiddleware()
        content = "x" * 1000
        result = mw._create_summary(content, "tool")
        assert result.endswith("...")
        assert "[tool]" in result
        assert len(result) < 600  # 500 chars + prefix

    def test_invalid_json_fallback(self) -> None:
        mw = VFSCompactionMiddleware()
        result = mw._create_summary("{not: valid json", "tool")
        assert "[tool]" in result


# ---------------------------------------------------------------------------
# _compact_to_vfs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCompactToVfs:
    async def test_compact_stores_and_returns_reference(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        content = "x" * 5000
        result_msg = _make_tool_message(content)
        request = _make_tool_request()

        compacted = await mw._compact_to_vfs(result_msg, request, "large_output")

        # VFS write called
        mock_vfs.write.assert_called_once()
        write_kwargs = mock_vfs.write.call_args.kwargs
        assert write_kwargs["user_id"] == USER_ID
        assert "tool_output" in write_kwargs["metadata"]["type"]

        # Compacted message has reference
        assert isinstance(compacted, ToolMessage)
        assert "stored at:" in compacted.content
        assert compacted.additional_kwargs["compacted"] is True
        assert compacted.additional_kwargs["original_length"] == len(content)

    async def test_compact_requires_user_id(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("content")
        request = _make_tool_request(user_id="")
        # Patch the runtime config to have empty user_id
        request.runtime.config["configurable"]["user_id"] = ""

        with pytest.raises(ValueError, match="user_id"):
            await mw._compact_to_vfs(result_msg, request, "reason")

    async def test_compact_requires_conversation_id(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("content")
        request = _make_tool_request(vfs_session_id=None, thread_id="")
        request.runtime.config["configurable"]["thread_id"] = ""
        # Remove vfs_session_id
        request.runtime.config["configurable"].pop("vfs_session_id", None)

        with pytest.raises(ValueError, match="vfs_session_id"):
            await mw._compact_to_vfs(result_msg, request, "reason")

    async def test_compact_requires_written_by(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("content")
        request = _make_tool_request(subagent_id=None, agent_name="")
        request.runtime.config["configurable"]["subagent_id"] = None
        request.runtime.config["metadata"]["agent_name"] = ""

        with pytest.raises(ValueError, match="subagent_id"):
            await mw._compact_to_vfs(result_msg, request, "reason")

    async def test_compact_uses_thread_id_when_no_vfs_session(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("some content")
        request = _make_tool_request(vfs_session_id=None, thread_id=THREAD_ID)
        request.runtime.config["configurable"].pop("vfs_session_id", None)
        request.runtime.config["configurable"]["thread_id"] = THREAD_ID

        await mw._compact_to_vfs(result_msg, request, "reason")
        # Path should contain thread_id as conversation_id
        write_path = mock_vfs.write.call_args.kwargs["path"]
        assert THREAD_ID in write_path

    async def test_compact_path_format(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("data")
        request = _make_tool_request(tool_name="my_search")

        await mw._compact_to_vfs(result_msg, request, "large_output")

        write_path = mock_vfs.write.call_args.kwargs["path"]
        assert "/tool_outputs/" in write_path
        assert "my_search" in write_path
        assert write_path.endswith(".json")

    async def test_compact_stores_tool_args(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware()
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("result data")
        request = _make_tool_request(args={"query": "test"})

        await mw._compact_to_vfs(result_msg, request, "large_output")

        # Verify the JSON content stored includes args
        stored_content = mock_vfs.write.call_args.kwargs["content"]
        stored_data = json.loads(stored_content)
        assert stored_data["args"] == {"query": "test"}
        assert stored_data["tool_name"] == "test_tool"


# ---------------------------------------------------------------------------
# awrap_tool_call integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAwrapToolCall:
    async def test_small_output_passes_through(self) -> None:
        mw = VFSCompactionMiddleware()
        mw._vfs = AsyncMock()

        result_msg = _make_tool_message("small output")
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request()

        result = await mw.awrap_tool_call(request, handler)
        assert result is result_msg
        handler.assert_called_once_with(request)

    async def test_command_result_passes_through(self) -> None:
        mw = VFSCompactionMiddleware()
        mw._vfs = AsyncMock()

        command = Command(goto="some_node")
        handler = AsyncMock(return_value=command)
        request = _make_tool_request()

        result = await mw.awrap_tool_call(request, handler)
        assert result is command

    async def test_large_output_compacted(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware(max_output_chars=MIN_COMPACTION_SIZE + 50)
        mw._vfs = mock_vfs

        large_content = "x" * (MIN_COMPACTION_SIZE + 100)
        result_msg = _make_tool_message(large_content)
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request()

        result = await mw.awrap_tool_call(request, handler)
        assert "stored at:" in result.content  # type: ignore[union-attr]
        mock_vfs.write.assert_called_once()

    async def test_always_persist_tool_compacted(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware(always_persist_tools=["special_tool"])
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("tiny data")
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request(tool_name="special_tool")

        result = await mw.awrap_tool_call(request, handler)
        assert result.additional_kwargs.get("compacted") is True  # type: ignore[union-attr]

    async def test_excluded_tool_never_compacted(self) -> None:
        mw = VFSCompactionMiddleware(
            max_output_chars=10,
            excluded_tools={"safe_tool"},
        )
        mw._vfs = AsyncMock()

        large_content = "x" * 50000
        result_msg = _make_tool_message(large_content)
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request(tool_name="safe_tool")

        result = await mw.awrap_tool_call(request, handler)
        assert result is result_msg

    async def test_compaction_failure_returns_original(self) -> None:
        mock_vfs = AsyncMock()
        mock_vfs.write.side_effect = RuntimeError("VFS write failed")
        mw = VFSCompactionMiddleware(max_output_chars=MIN_COMPACTION_SIZE + 50)
        mw._vfs = mock_vfs

        large_content = "x" * (MIN_COMPACTION_SIZE + 100)
        result_msg = _make_tool_message(large_content)
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request()

        result = await mw.awrap_tool_call(request, handler)
        # Should return original since compaction failed
        assert result is result_msg

    async def test_context_threshold_trigger(self) -> None:
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware(
            compaction_threshold=0.5,
            max_output_chars=100000,
            context_window=100,
        )
        mw._vfs = mock_vfs

        # Content > MIN_COMPACTION_SIZE but < max_output_chars
        medium_content = "x" * (MIN_COMPACTION_SIZE + 100)
        result_msg = _make_tool_message(medium_content)
        handler = AsyncMock(return_value=result_msg)

        # Provide enough message context to push usage over threshold
        # 100 token window, need > 50 tokens (200 chars / 4 = 50 tokens)
        context_msgs = [HumanMessage(content="y" * 400)]
        request = _make_tool_request(context_messages=context_msgs)

        result = await mw.awrap_tool_call(request, handler)
        assert result.additional_kwargs.get("compacted") is True  # type: ignore[union-attr]

    async def test_tool_call_as_dict(self) -> None:
        """tool_call is a dict — exercise the dict branch of name extraction."""
        mw = VFSCompactionMiddleware(always_persist_tools=["dict_tool"])
        mw._vfs = AsyncMock()

        result_msg = _make_tool_message("data", name="dict_tool")
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request(tool_name="dict_tool")

        result = await mw.awrap_tool_call(request, handler)
        assert result.additional_kwargs.get("compacted") is True  # type: ignore[union-attr]

    async def test_tool_call_as_object(self) -> None:
        """tool_call is an object with .name attribute."""
        mock_vfs = AsyncMock()
        mw = VFSCompactionMiddleware(always_persist_tools=["obj_tool"])
        mw._vfs = mock_vfs

        result_msg = _make_tool_message("data")
        handler = AsyncMock(return_value=result_msg)
        request = _make_tool_request(tool_name="obj_tool")
        # Replace dict tool_call with object-like mock
        tc_obj = MagicMock()
        tc_obj.name = "obj_tool"
        tc_obj.id = "call_1"
        tc_obj.args = {}
        request.tool_call = tc_obj

        result = await mw.awrap_tool_call(request, handler)
        assert result.additional_kwargs.get("compacted") is True  # type: ignore[union-attr]
