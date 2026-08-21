"""Brutal behavior tests for WorkspaceCompactionMiddleware.

This middleware is what makes "large tool output is stored in the VFS" real:
oversized tool results are offloaded to /workspace/sessions/<conv>/tool_outputs/
and replaced inline with a preview + path. It had no tests. We mock the one
boundary (write_session_file → JuiceFS) and exercise the real decision and
persistence logic.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware.compaction import (
    COMPACTION_TRUNCATED_MARKER,
    WorkspaceCompactionMiddleware,
    _summarize_output,
    _summary_input_sample,
    should_compact_output,
)
from app.constants.offload import OFFLOAD_KEY
from app.constants.summarization import (
    COMPACTION_FALLBACK_HEAD_CHARS,
    COMPACTION_FALLBACK_TAIL_CHARS,
    COMPACTION_SUMMARY_MAX_CHARS,
    MIN_COMPACTION_SIZE,
)
from app.services.storage import JuiceFSUnavailable
from tests.helpers import create_fake_llm

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


def _decide(
    mw: WorkspaceCompactionMiddleware, msg: ToolMessage, tool_name: str, usage: float
) -> tuple[bool, str]:
    """Run the middleware's compaction decision the way ``awrap_tool_call`` does.

    The decide logic now lives in the module-level ``should_compact_output``; the
    middleware only supplies its config and derives the per-tool flags. This
    mirrors that derivation so the behavioral assertions stay identical.
    """
    return should_compact_output(
        str(msg.content),
        tool_name,
        usage,
        max_output_chars=mw.max_output_chars,
        compaction_threshold=mw.compaction_threshold,
        always_persist=tool_name in mw.always_persist_tools,
        excluded=tool_name in mw.excluded_tools,
    )


class TestShouldCompact:
    def test_excluded_tool_never_compacts_even_when_huge(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=100, excluded_tools={"bash"})
        ok, reason = _decide(mw, _tool_msg("x" * 50_000, "bash"), "bash", 0.99)
        assert ok is False and reason == ""

    def test_small_output_is_left_inline(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        ok, _ = _decide(mw, _tool_msg("x" * (MIN_COMPACTION_SIZE - 1)), "search", 0.0)
        assert ok is False

    def test_large_single_output_compacts(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        ok, reason = _decide(mw, _tool_msg("x" * 1500), "search", 0.0)
        assert ok is True
        assert "large_output" in reason and "1500" in reason

    def test_context_pressure_compacts_mid_size_output(self) -> None:
        mw = WorkspaceCompactionMiddleware(compaction_threshold=0.5, max_output_chars=100_000)
        # between MIN and max, but context usage over threshold
        ok, reason = _decide(mw, _tool_msg("y" * 600), "search", 0.73)
        assert ok is True
        assert "context_threshold" in reason

    def test_always_persist_tool_compacts_even_when_tiny(self) -> None:
        mw = WorkspaceCompactionMiddleware(always_persist_tools=["search"])
        ok, reason = _decide(mw, _tool_msg("tiny"), "search", 0.0)
        assert ok is True and reason == "always_persist_tool"

    def test_excluded_beats_always_persist(self) -> None:
        # excluded is checked first; a tool in both lists must NOT compact
        mw = WorkspaceCompactionMiddleware(
            always_persist_tools=["search"], excluded_tools={"search"}
        )
        ok, reason = _decide(mw, _tool_msg("x" * 9999), "search", 0.99)
        assert ok is False and reason == ""


class TestContextUsage:
    def test_no_state_is_zero(self) -> None:
        mw = WorkspaceCompactionMiddleware()
        assert mw._get_context_usage(SimpleNamespace(state=None)) == pytest.approx(0.0)

    def test_usage_is_capped_at_one(self) -> None:
        mw = WorkspaceCompactionMiddleware(context_window=1000)
        msgs = [SimpleNamespace(content="z" * 8000)]  # 8000 chars // 4 = 2000 tokens > window
        usage = mw._get_context_usage(SimpleNamespace(state={"messages": msgs}))
        assert usage == pytest.approx(1.0)


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

        # offloaded JSON binds the mining tools via a Command carrying the message
        assert isinstance(result, Command)
        assert result.update["selected_tool_ids"] == ["query_json", "grep"]
        message = result.update["messages"][0]
        # inline message shrank to a pointer; full payload written under tool_outputs/
        assert "stored at:" in message.content
        assert WROTE[1] in message.content
        assert message.additional_kwargs["compacted"] is True
        assert message.additional_kwargs["compaction_strategy"] == "workspace_spill"
        assert message.additional_kwargs["workspace_path"] == WROTE[1]
        rel_path = mock_write.await_args.kwargs["relative_path"]
        assert rel_path.startswith("tool_outputs/") and rel_path.endswith(".json")
        # the FULL raw content is what gets persisted (recoverable and mineable
        # by query_json/grep), not the preview or a metadata wrapper
        assert mock_write.await_args.kwargs["content"] == big

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

    async def test_missing_mount_compacts_in_context_instead_of_skipping(self) -> None:
        """JuiceFS down (native dev / outage) must still compact.

        The workspace spill is the lossless tier; when it is unavailable the
        output is truncated in context instead. Returning the full output
        unchanged (the old behavior) let context grow without bound.
        """
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "HEAD" + ("x" * 200_000) + "TAIL"

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

        assert isinstance(result, ToolMessage)
        assert len(result.content) < len(big) / 10
        assert result.content.startswith(COMPACTION_TRUNCATED_MARKER)
        assert "HEAD" in result.content and "TAIL" in result.content
        assert result.additional_kwargs["compacted"] is True
        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"
        assert result.additional_kwargs["original_length"] == len(big)
        # no file was written, so nothing to mine — the offload marker must be absent
        assert OFFLOAD_KEY not in result.additional_kwargs

    async def test_fallback_keeps_output_under_the_char_budget(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "x" * 500_000

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

        budget = COMPACTION_FALLBACK_HEAD_CHARS + COMPACTION_FALLBACK_TAIL_CHARS
        # marker + elision note add a bounded, content-independent overhead
        assert len(result.content) < budget + 500

    async def test_fallback_leaves_output_already_under_budget_alone(self) -> None:
        """Nothing to reclaim below the budget — the original must pass through."""
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        small = "x" * (MIN_COMPACTION_SIZE + 10)
        original = _tool_msg(small)

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return original

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert result is original

    async def test_fallback_preserves_error_status(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        failed = ToolMessage(
            content="boom " * 100_000, tool_call_id="call_1", name="search", status="error"
        )

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return failed

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert result.status == "error"
        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"

    async def test_fallback_fires_when_the_spill_fails_for_any_reason(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "x" * 200_000

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=OSError("disk exploded"),
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"

    async def test_media_blocks_still_skip_compaction_without_a_workspace(self) -> None:
        """Inline media is the payload; it must not be truncated by the fallback."""
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        blocks = [
            {"type": "text", "text": "here is the screenshot"},
            {"type": "image", "source": {"type": "base64", "data": "A" * 100_000}},
        ]
        original = ToolMessage(content=blocks, tool_call_id="call_1", name="search")

        async def handler(  # NOSONAR python:S7503 awaited by awrap_tool_call; must be a coroutine
            _req,
        ):
            return original

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=JuiceFSUnavailable("no mount"),
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert result is original

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

    async def test_missing_user_id_compacts_in_context(self) -> None:
        """No workspace identity means no spill target — compact in context,
        never hand the agent the full output back."""
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        big = "x" * 200_000
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

        assert result.content.startswith(COMPACTION_TRUNCATED_MARKER)
        assert len(result.content) < len(big) / 10
        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"
        mock_write.assert_not_awaited()


class TestSummary:
    def test_json_list_preview_reports_count(self) -> None:
        summary = _summarize_output(json.dumps([{"i": i} for i in range(42)]), "search")
        assert "Returned 42 items" in summary

    def test_json_dict_preview_reports_keys(self) -> None:
        summary = _summarize_output(json.dumps({"a": 1, "b": 2}), "fetch")
        assert "keys" in summary and "fetch" in summary

    def test_plain_text_is_truncated(self) -> None:
        summary = _summarize_output("z" * 2000, "bash")
        assert summary.endswith("...")
        assert len(summary) < 2000


class _BrokenModel:
    """Stands in for an unreachable summarizer endpoint."""

    async def ainvoke(self, _messages: object) -> object:
        raise RuntimeError("endpoint down")


class _SlowModel:
    """Stands in for an endpoint that answers after the compaction timeout."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def ainvoke(self, _messages: object) -> object:
        await asyncio.sleep(self.delay)
        return AIMessage(content="too late")


class TestLLMSummary:
    """The digest tier: the LLM summary IS the compacted payload; the JuiceFS
    pointer is an optional add-on, never a requirement (issue #916)."""

    def _mw(self, llm: object) -> WorkspaceCompactionMiddleware:
        return WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=llm)  # type: ignore[arg-type]

    @staticmethod
    def _request_without_identity() -> SimpleNamespace:
        return SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(config={"configurable": {}}),
            state={"messages": []},
        )

    async def test_digest_stands_alone_without_a_workspace(self) -> None:
        """No user/conversation id → nowhere to spill; the summary alone must
        carry the substance instead of degrading to lossy truncation."""
        mw = self._mw(create_fake_llm(["Found 3000 rows; all status=shipped."]))
        big = json.dumps([{"row": i, "status": "shipped"} for i in range(1500)])

        async def handler(_req):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock
        ) as mock_write:
            result = await mw.awrap_tool_call(self._request_without_identity(), handler)

        mock_write.assert_not_awaited()
        assert isinstance(result, ToolMessage)
        assert "Found 3000 rows; all status=shipped." in result.content
        assert len(result.content) < len(big) / 10
        assert result.additional_kwargs["compacted"] is True
        assert result.additional_kwargs["compaction_strategy"] == "llm_summary"
        # nothing spilled, so there is no file to mine and no marker to bind on
        assert OFFLOAD_KEY not in result.additional_kwargs

    async def test_digest_with_spill_keeps_pointer_and_binds_miners(self) -> None:
        mw = self._mw(create_fake_llm(["Digest: 500 records, ids 0-499."]))
        big = json.dumps([{"i": i} for i in range(500)])

        async def handler(_req):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            return_value=WROTE,
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        # the offload marker must still bind query_json/grep — lossless recovery
        # survives even though the agent no longer NEEDS the file
        assert isinstance(result, Command)
        message = result.update["messages"][0]
        assert "Digest: 500 records, ids 0-499." in message.content
        assert WROTE[1] in message.content
        assert message.additional_kwargs["compaction_strategy"] == "llm_summary_workspace_spill"
        assert message.additional_kwargs["workspace_path"] == WROTE[1]

    async def test_digest_failure_degrades_to_legacy_spill_body_without_double_write(
        self,
    ) -> None:
        """When the summarizer is unreachable but the workspace exists, today's
        preview-plus-pointer body is kept — and the raw output is written ONCE."""
        mw = self._mw(_BrokenModel())
        big = "x" * 5000

        async def handler(_req):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            return_value=WROTE,
        ) as mock_write:
            result = await mw.awrap_tool_call(_request(), handler)

        assert mock_write.await_count == 1
        assert isinstance(result, Command)
        message = result.update["messages"][0]
        assert "stored at:" in message.content
        assert message.additional_kwargs["compaction_strategy"] == "workspace_spill"

    async def test_digest_failure_without_a_workspace_truncates_in_context(self) -> None:
        mw = self._mw(_BrokenModel())
        big = "HEAD" + ("x" * 200_000) + "TAIL"

        async def handler(_req):
            return _tool_msg(big)

        with patch("app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock):
            result = await mw.awrap_tool_call(self._request_without_identity(), handler)

        assert isinstance(result, ToolMessage)
        assert result.content.startswith(COMPACTION_TRUNCATED_MARKER)
        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"

    async def test_empty_digest_falls_back(self) -> None:
        mw = self._mw(create_fake_llm(["   "]))
        big = "y" * 200_000

        async def handler(_req):
            return _tool_msg(big)

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            return_value=WROTE,
        ):
            result = await mw.awrap_tool_call(_request(), handler)

        assert isinstance(result, Command)
        message = result.update["messages"][0]
        assert message.additional_kwargs["compaction_strategy"] == "workspace_spill"

    async def test_digest_is_hard_capped_even_when_the_model_rambles(self) -> None:
        rambler = create_fake_llm(["z" * 50_000])
        mw = self._mw(rambler)
        big = "x" * 5000

        async def handler(_req):
            return _tool_msg(big)

        with patch("app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock):
            result = await mw.awrap_tool_call(self._request_without_identity(), handler)

        assert isinstance(result, ToolMessage)
        # digest cap + strategy header + truncation suffix stay bounded
        assert len(result.content) < COMPACTION_SUMMARY_MAX_CHARS + 300

    async def test_slow_endpoint_times_out_and_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.agents.middleware.compaction.COMPACTION_SUMMARY_TIMEOUT_SECONDS", 0.05
        )
        mw = self._mw(_SlowModel(delay=1.0))
        big = "x" * 200_000

        async def handler(_req):
            return _tool_msg(big)

        with patch("app.agents.middleware.compaction.write_session_file", new_callable=AsyncMock):
            result = await mw.awrap_tool_call(self._request_without_identity(), handler)

        assert isinstance(result, ToolMessage)
        assert result.additional_kwargs["compaction_strategy"] == "in_context_truncation"

    def test_summary_input_sample_keeps_head_and_tail(self) -> None:
        sampled = _summary_input_sample("A" * 50_000 + "MIDDLE" + "Z" * 50_000)
        assert sampled.startswith("AAAA")
        assert sampled.endswith("ZZZZ")
        assert "middle chars omitted" in sampled
        assert len(sampled) < 40_000

    def test_summary_input_sample_passes_short_content_through(self) -> None:
        short = "compact already"
        assert _summary_input_sample(short) == short
