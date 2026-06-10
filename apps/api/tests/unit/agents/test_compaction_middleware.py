"""Brutal behavior tests for WorkspaceCompactionMiddleware.

This middleware is what makes "large tool output is stored in the VFS" real:
oversized tool results are offloaded to /workspace/sessions/<conv>/tool_outputs/
and replaced inline with a preview + path. It had no tests. We mock the one
boundary (write_session_file → JuiceFS) and exercise the real decision and
persistence logic.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
import pytest

from app.agents.middleware.compaction import WorkspaceCompactionMiddleware
from app.constants.summarization import MIN_COMPACTION_SIZE
from app.services.storage import JuiceFSUnavailable

WROTE = (
    "/mnt/jfs/users/u1/sessions/conv1/tool_outputs/x.json",
    "/workspace/sessions/conv1/tool_outputs/x.json",
)


def _request(tool_name: str = "search", *, messages: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tool_call={"name": tool_name, "id": "call_1", "args": {"q": "foo"}},
        runtime=SimpleNamespace(
            config={"configurable": {"user_id": "u1", "vfs_session_id": "conv1"}}
        ),
        state={"messages": messages or []},
    )


def _tool_msg(content: str, name: str = "search") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="call_1", name=name)


@pytest.mark.unit
class TestShouldCompact:
    def test_excluded_tool_never_compacts_even_when_huge(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=100, excluded_tools={"bash"})
        ok, reason = mw._should_compact(_tool_msg("x" * 50_000, "bash"), "bash", 0.99)
        assert ok is False and reason == ""

    def test_small_output_is_left_inline(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        ok, _ = mw._should_compact(_tool_msg("x" * (MIN_COMPACTION_SIZE - 1)), "search", 0.0)
        assert ok is False

    def test_large_single_output_compacts(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        ok, reason = mw._should_compact(_tool_msg("x" * 1500), "search", 0.0)
        assert ok is True
        assert "large_output" in reason and "1500" in reason

    def test_context_pressure_compacts_mid_size_output(self) -> None:
        mw = WorkspaceCompactionMiddleware(compaction_threshold=0.5, max_output_chars=100_000)
        # between MIN and max, but context usage over threshold
        ok, reason = mw._should_compact(_tool_msg("y" * 600), "search", 0.73)
        assert ok is True
        assert "context_threshold" in reason

    def test_always_persist_tool_compacts_even_when_tiny(self) -> None:
        mw = WorkspaceCompactionMiddleware(always_persist_tools=["search"])
        ok, reason = mw._should_compact(_tool_msg("tiny"), "search", 0.0)
        assert ok is True and reason == "always_persist_tool"

    def test_excluded_beats_always_persist(self) -> None:
        # excluded is checked first; a tool in both lists must NOT compact
        mw = WorkspaceCompactionMiddleware(
            always_persist_tools=["search"], excluded_tools={"search"}
        )
        ok, reason = mw._should_compact(_tool_msg("x" * 9999), "search", 0.99)
        assert ok is False and reason == ""


@pytest.mark.unit
class TestContextUsage:
    def test_no_state_is_zero(self) -> None:
        mw = WorkspaceCompactionMiddleware()
        assert mw._get_context_usage(SimpleNamespace(state=None)) == pytest.approx(0.0)

    def test_usage_is_capped_at_one(self) -> None:
        mw = WorkspaceCompactionMiddleware(context_window=1000)
        msgs = [SimpleNamespace(content="z" * 8000)]  # 8000 chars // 4 = 2000 tokens > window
        usage = mw._get_context_usage(SimpleNamespace(state={"messages": msgs}))
        assert usage == pytest.approx(1.0)


@pytest.mark.unit
class TestAwrapToolCall:
    async def test_large_output_is_offloaded_and_recoverable(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        big = json.dumps([{"i": i} for i in range(500)])
        request = _request()

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            return_value=WROTE,
        ) as mock_write:
            result = await mw.awrap_tool_call(request, handler)

        # inline message shrank to a pointer; full payload written under tool_outputs/
        assert "stored at:" in result.content
        assert WROTE[1] in result.content
        assert result.additional_kwargs["compacted"] is True
        assert result.additional_kwargs["workspace_path"] == WROTE[1]
        rel_path = mock_write.await_args.kwargs["relative_path"]
        assert rel_path.startswith("tool_outputs/") and rel_path.endswith(".json")
        # the FULL content is what gets persisted (recoverable), not the preview
        persisted = json.loads(mock_write.await_args.kwargs["content"])
        assert persisted["content"] == big

    async def test_small_output_passes_through_untouched(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        original = _tool_msg("small result")

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return original

        with patch(
            "app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock
        ) as mock_write:
            result = await mw.awrap_tool_call(_request(), handler)

        assert result is original
        mock_write.assert_not_awaited()

    async def test_missing_mount_returns_original_not_crash(self) -> None:
        """JuiceFS down (native dev / outage) must degrade to the full inline
        output, never raise into the agent loop."""
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "x" * 5000

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert result.content == big
        assert "compacted" not in result.additional_kwargs

    async def test_non_tool_message_result_passes_through(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1)
        sentinel = SimpleNamespace(kind="command")  # not a ToolMessage

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return sentinel

        with patch(
            "app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock
        ) as mock_write:
            result = await mw.awrap_tool_call(_request(), handler)

        assert result is sentinel
        mock_write.assert_not_awaited()

    async def test_missing_user_id_degrades_to_original(self) -> None:
        """_persist raises ValueError without a user_id; the broad guard must
        swallow it and return the full output rather than crash the agent."""
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "x" * 5000
        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(config={"configurable": {}}),  # no user_id
            state={"messages": []},
        )

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock
        ) as mock_write:
            result = await mw.awrap_tool_call(request, handler)

        assert result.content == big
        assert "compacted" not in result.additional_kwargs
        mock_write.assert_not_awaited()


@pytest.mark.unit
class TestSummary:
    def test_json_list_preview_reports_count(self) -> None:
        mw = WorkspaceCompactionMiddleware()
        summary = mw._summary(json.dumps([{"i": i} for i in range(42)]), "search")
        assert "Returned 42 items" in summary

    def test_json_dict_preview_reports_keys(self) -> None:
        mw = WorkspaceCompactionMiddleware()
        summary = mw._summary(json.dumps({"a": 1, "b": 2}), "fetch")
        assert "keys" in summary and "fetch" in summary

    def test_plain_text_is_truncated(self) -> None:
        mw = WorkspaceCompactionMiddleware()
        summary = mw._summary("z" * 2000, "bash")
        assert summary.endswith("...")
        assert len(summary) < 2000
