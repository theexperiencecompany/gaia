"""Tests for app.agents.middleware.vfs_summarization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from app.agents.middleware.vfs_summarization import (
    VFSArchivingSummarizationMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_middleware(**kwargs):
    """Create middleware with mocked parent __init__."""
    with patch(
        "app.agents.middleware.vfs_summarization.SummarizationMiddleware.__init__",
        return_value=None,
    ):
        mw = VFSArchivingSummarizationMiddleware(
            model="gpt-4o-mini",
            **kwargs,
        )
        # Manually set attributes that parent __init__ would normally set
        mw.trigger = kwargs.get("trigger", ("fraction", 0.85))
        mw.token_counter = MagicMock(return_value=0)
        return mw


def _make_runtime(
    user_id="u1", thread_id="t1", subagent_id="executor", vfs_session_id=None
):
    """Build a fake runtime with configurable."""
    config = {
        "configurable": {
            "user_id": user_id,
            "thread_id": thread_id,
            "subagent_id": subagent_id,
            "vfs_session_id": vfs_session_id,
        },
        "metadata": {"agent_name": "executor"},
    }
    return SimpleNamespace(config=config)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self):
        mw = _make_middleware()
        assert mw.vfs_enabled is True
        assert mw.excluded_tools == set()
        assert mw._vfs is None

    def test_custom_values(self):
        mw = _make_middleware(
            vfs_enabled=False,
            excluded_tools={"tool_a"},
        )
        assert mw.vfs_enabled is False
        assert mw.excluded_tools == {"tool_a"}


# ---------------------------------------------------------------------------
# _get_vfs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetVFS:
    async def test_lazy_loads_vfs(self):
        mw = _make_middleware()
        mock_vfs = MagicMock()
        with patch(
            "app.agents.middleware.vfs_summarization.get_vfs",
            new_callable=AsyncMock,
            return_value=mock_vfs,
        ):
            result = await mw._get_vfs()
        assert result is mock_vfs
        assert mw._vfs is mock_vfs

    async def test_returns_cached_vfs(self):
        mw = _make_middleware()
        cached = MagicMock()
        mw._vfs = cached
        result = await mw._get_vfs()
        assert result is cached


# ---------------------------------------------------------------------------
# _should_trigger_summarization
# ---------------------------------------------------------------------------


class TestShouldTriggerSummarization:
    def test_returns_false_for_empty_messages(self):
        mw = _make_middleware()
        assert mw._should_trigger_summarization({"messages": []}) is False

    def test_returns_false_when_no_messages_key(self):
        mw = _make_middleware()
        assert mw._should_trigger_summarization({}) is False

    def test_fraction_trigger_below_threshold(self):
        mw = _make_middleware(trigger=("fraction", 0.85))
        mw.token_counter = MagicMock(return_value=1000)
        mw._max_tokens = 128000
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False

    def test_fraction_trigger_above_threshold(self):
        mw = _make_middleware(trigger=("fraction", 0.85))
        mw.token_counter = MagicMock(return_value=120000)
        mw._max_tokens = 128000
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is True

    def test_tokens_trigger_above_threshold(self):
        mw = _make_middleware(trigger=("tokens", 5000))
        mw.token_counter = MagicMock(return_value=6000)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is True

    def test_tokens_trigger_below_threshold(self):
        mw = _make_middleware(trigger=("tokens", 5000))
        mw.token_counter = MagicMock(return_value=4000)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False

    def test_messages_trigger_above_threshold(self):
        mw = _make_middleware(trigger=("messages", 2))
        mw.token_counter = MagicMock(return_value=100)
        msgs = [HumanMessage(content=f"msg{i}") for i in range(5)]
        state = {"messages": msgs}
        assert mw._should_trigger_summarization(state) is True

    def test_messages_trigger_below_threshold(self):
        mw = _make_middleware(trigger=("messages", 10))
        mw.token_counter = MagicMock(return_value=100)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False

    def test_excluded_tools_are_filtered(self):
        mw = _make_middleware(excluded_tools={"big_tool"}, trigger=("messages", 1))
        mw.token_counter = MagicMock(return_value=100)
        msgs = [
            ToolMessage(content="data", tool_call_id="tc1", name="big_tool"),
            ToolMessage(content="data", tool_call_id="tc2", name="big_tool"),
        ]
        state = {"messages": msgs}
        # After filtering, 0 messages remain -> False
        assert mw._should_trigger_summarization(state) is False

    def test_returns_false_on_token_counter_exception(self):
        mw = _make_middleware(trigger=("fraction", 0.85))
        mw.token_counter = MagicMock(side_effect=RuntimeError("fail"))
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False


# ---------------------------------------------------------------------------
# _serialize_messages
# ---------------------------------------------------------------------------


class TestSerializeMessages:
    def test_serializes_human_message(self):
        mw = _make_middleware()
        msgs = [HumanMessage(content="hello")]
        result = mw._serialize_messages(msgs)
        assert len(result) == 1
        assert result[0]["type"] == "HumanMessage"
        assert result[0]["content"] == "hello"

    def test_serializes_tool_message(self):
        mw = _make_middleware()
        msgs = [ToolMessage(content="result", tool_call_id="tc1", name="my_tool")]
        result = mw._serialize_messages(msgs)
        assert result[0]["tool_call_id"] == "tc1"
        assert result[0]["name"] == "my_tool"

    def test_serializes_tool_calls(self):
        mw = _make_middleware()
        msg = MagicMock()
        msg.content = "I'll call tool"
        msg.tool_calls = [{"id": "tc1", "name": "search", "args": {"q": "test"}}]
        type(msg).__name__ = "AIMessage"
        result = mw._serialize_messages([msg])
        assert len(result[0]["tool_calls"]) == 1
        assert result[0]["tool_calls"][0]["name"] == "search"

    def test_handles_message_without_tool_calls(self):
        mw = _make_middleware()
        msg = HumanMessage(content="plain message")
        result = mw._serialize_messages([msg])
        assert "tool_calls" not in result[0]
        assert "tool_call_id" not in result[0]


# ---------------------------------------------------------------------------
# _inject_archive_path
# ---------------------------------------------------------------------------


class TestInjectArchivePath:
    def test_injects_into_summary_message(self):
        mw = _make_middleware()
        summary_msg = HumanMessage(
            content="Summary of conversation",
            additional_kwargs={"is_summary": True},
        )
        result_dict = {"messages": [summary_msg]}
        result = mw._inject_archive_path(result_dict, "/vfs/archive.json")
        assert "/vfs/archive.json" in result["messages"][0].content
        assert (
            result["messages"][0].additional_kwargs["archive_path"]
            == "/vfs/archive.json"
        )

    def test_no_summary_message_unchanged(self):
        mw = _make_middleware()
        msg = HumanMessage(content="regular", additional_kwargs={})
        result_dict = {"messages": [msg]}
        result = mw._inject_archive_path(result_dict, "/vfs/archive.json")
        assert "archive" not in result["messages"][0].content

    def test_empty_messages_returns_unchanged(self):
        mw = _make_middleware()
        result_dict = {"messages": []}
        result = mw._inject_archive_path(result_dict, "/path")
        assert result == {"messages": []}


# ---------------------------------------------------------------------------
# _archive_to_vfs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestArchiveToVfs:
    async def test_archives_messages(self):
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hello")]}

        with patch(
            "app.agents.middleware.vfs_summarization.get_session_path",
            return_value="/users/u1/sessions/t1",
        ):
            path = await mw._archive_to_vfs(state, runtime)

        assert "pre_summary" in path
        mock_vfs.write.assert_awaited_once()
        call_kwargs = mock_vfs.write.call_args.kwargs
        assert call_kwargs["user_id"] == "u1"

    async def test_raises_without_user_id(self):
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(user_id=None)
        state = {"messages": []}

        with pytest.raises(ValueError, match="user_id"):
            await mw._archive_to_vfs(state, runtime)

    async def test_raises_without_conversation_id(self):
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(thread_id=None, vfs_session_id=None)
        state = {"messages": []}

        with pytest.raises(ValueError, match="vfs_session_id"):
            await mw._archive_to_vfs(state, runtime)

    async def test_raises_without_written_by(self):
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(subagent_id=None)
        # Also remove agent_name from metadata
        runtime.config["metadata"] = {}
        state = {"messages": []}

        with pytest.raises(ValueError, match="subagent_id"):
            await mw._archive_to_vfs(state, runtime)

    async def test_uses_vfs_session_id_over_thread_id(self):
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime(
            thread_id="thread_id",
            vfs_session_id="vfs_session_id",
        )
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            "app.agents.middleware.vfs_summarization.get_session_path",
            return_value="/path",
        ) as mock_path:
            await mw._archive_to_vfs(state, runtime)
        mock_path.assert_called_once_with("u1", "vfs_session_id")


# ---------------------------------------------------------------------------
# abefore_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAbeforeModel:
    async def test_no_archive_when_vfs_disabled(self):
        mw = _make_middleware(vfs_enabled=False)
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await mw.abefore_model(state, runtime)
        assert result is None

    async def test_archives_and_injects_on_summarization(self):
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock(return_value="/vfs/archive.json")

        summary_msg = HumanMessage(
            content="Summary",
            additional_kwargs={"is_summary": True},
        )
        summarization_result = {"messages": [summary_msg]}

        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=summarization_result,
        ):
            result = await mw.abefore_model(state, runtime)

        assert result is not None
        assert "/vfs/archive.json" in result["messages"][0].content

    async def test_archive_failure_continues(self):
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock(side_effect=RuntimeError("VFS down"))

        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await mw.abefore_model(state, runtime)
        assert result is None

    async def test_no_inject_when_no_archive_path(self):
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=False)

        summarization_result = {"messages": [HumanMessage(content="Summary")]}
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            "app.agents.middleware.vfs_summarization.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=summarization_result,
        ):
            result = await mw.abefore_model(state, runtime)

        # No archive path => no injection, but result still returned
        assert "archived at" not in result["messages"][0].content
