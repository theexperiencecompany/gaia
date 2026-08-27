"""Brutal behavior tests for WorkspaceCompactionMiddleware.

This middleware is what makes "large tool output is stored in the VFS" real:
oversized tool results are offloaded to /workspace/sessions/<conv>/tool_outputs/
and replaced inline with a preview + path. It had no tests. We mock the one
boundary (write_session_file → JuiceFS) and exercise the real decision and
persistence logic.
"""

import asyncio
import json
import re as _re
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

from langchain_core.language_models import BaseChatModel, LanguageModelLike
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.types import Command
import pytest

from app.agents.middleware import compaction as cm
from app.agents.middleware.compaction import (
    COMPACTION_TRUNCATED_MARKER,
    WorkspaceCompactionMiddleware,
    _offload_kwargs,
    _stub_spill_message,
    _summarize_output,
    _summarized_compact_message,
    _summary_input_sample,
    should_compact_output,
)
from app.agents.workspace.offload import read_offload
from app.constants.offload import OFFLOAD_KEY
from app.constants.summarization import (
    COMPACTION_FALLBACK_HEAD_CHARS,
    COMPACTION_FALLBACK_TAIL_CHARS,
    COMPACTION_SUMMARY_MAX_CHARS,
    MIN_COMPACTION_SIZE,
)
from app.services.storage import JuiceFSUnavailable


class _StubLog:
    """Records warning/error payloads; other levels are swallowed."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def warning(self, msg: str, **kw):
        self.records.append((msg, kw))

    def error(self, msg: str, **kw):
        self.records.append((msg, kw))

    def info(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass


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


_DIGEST_CAPTURE: dict = {"messages": None}


class _RecordingDigestModel(BaseChatModel):
    """Captures the prompt messages and returns a stripped-ready reply."""

    @property
    def _llm_type(self) -> str:
        return "recording"

    def _generate(self, *a, **k):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **k):
        _DIGEST_CAPTURE["messages"] = messages
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="  ok  "))])


_DIGEST_SWAP: dict = {"done": False}


class _SwapAfterInvokeModel(BaseChatModel):
    """Lets the first invoke complete, then swaps in an unusable payload so
    the narrowing branch (content neither str nor list) is exercised."""

    @property
    def _llm_type(self) -> str:
        return "swap"

    def _generate(self, *a, **k):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **k):
        from types import SimpleNamespace

        result = ChatResult(generations=[ChatGeneration(message=AIMessage(content="fine"))])
        if not _DIGEST_SWAP["done"]:
            result.generations[0].message = SimpleNamespace(content=12345)
        return result


class _OverCapDigestModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "overcap"

    def _generate(self, *a, **k):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **k):
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content="y" * (COMPACTION_SUMMARY_MAX_CHARS + 10)))
            ]
        )


class _InstantDigestModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "instant"

    def _generate(self, *a, **k):
        raise NotImplementedError

    async def _agenerate(self, messages, stop=None, run_manager=None, **k):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="fast"))])


class TestLLMSummary:
    """The digest tier: the LLM summary IS the compacted payload; the JuiceFS
    pointer is an optional add-on, never a requirement (issue #916)."""

    def _mw(self, llm: object) -> WorkspaceCompactionMiddleware:
        return WorkspaceCompactionMiddleware(
            max_output_chars=1000, summary_llm=cast("LanguageModelLike", llm)
        )

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

    def test_summary_input_sample_boundary_is_inclusive(self) -> None:
        """len == head+tail passes through untouched; one more char splits."""
        from app.constants.summarization import (
            COMPACTION_SUMMARY_INPUT_HEAD_CHARS as HEAD,
            COMPACTION_SUMMARY_INPUT_TAIL_CHARS as TAIL,
        )

        at_limit = "A" * (HEAD + TAIL)
        assert _summary_input_sample(at_limit) == at_limit

        content = "A" * HEAD + "M" + "Z" * TAIL
        expected = f"{'A' * HEAD}\n[... 1 middle chars omitted from this sample ...]\n{'Z' * TAIL}"
        assert _summary_input_sample(content) == expected


class TestDigestComposition:
    """Pin the digest message's exact observable pieces — header, pointer
    wording per format, kwargs fields, status passthrough, kwargs merging."""

    def _build(self, *, fmt="json", spilled=True, status="success", extra=None):
        path = WROTE[1]
        msg = _summarized_compact_message(
            summary="the digest",
            tool_name="search",
            tool_call_id="call_1",
            reason="large_output (9000 chars)",
            status=status,
            content_str="z" * 9000,
            spilled=(fmt, path) if spilled else None,
            existing_additional_kwargs=extra or {},
        )
        return msg

    def test_header_carries_tool_and_reason(self) -> None:
        assert self._build().content.startswith(
            "[search compacted — large_output (9000 chars)] the digest"
        )

    def test_json_pointer_offers_query_json_and_grep(self) -> None:
        body = self._build(fmt="json").content
        assert "query_json/grep" in body
        # a corrupted wording must fail this test, not hide inside a substring
        assert "XXquery_json/grepXX" not in body

    def test_jsonl_pointer_also_offers_query_json(self) -> None:
        assert "query_json/grep" in self._build(fmt="jsonl").content

    def test_text_pointer_offers_grep_only(self) -> None:
        body = self._build(fmt="text").content
        # exact word: "XXgrepXX" (a corrupted wording) contains "grep" too

        assert _re.search(r"(?<!X)grep(?!X)", body)
        assert "query_json" not in body

    def test_pointer_reports_size_in_kb(self) -> None:
        assert f"{9000 / 1024:.1f} KB" in self._build(spilled=True).content

    def test_no_spill_means_no_pointer_line(self) -> None:
        assert "saved at" not in self._build(spilled=False).content

    def test_kwargs_fields(self) -> None:
        kw = self._build(spilled=False).additional_kwargs
        assert kw["original_length"] == 9000
        assert kw["compaction_reason"] == "large_output (9000 chars)"
        assert kw["compacted"] is True
        assert kw["compaction_strategy"] == "llm_summary"

    def test_spilled_kwargs_add_path_and_strategy(self) -> None:
        kw = self._build(spilled=True).additional_kwargs
        assert kw["workspace_path"] == WROTE[1]
        assert kw["compaction_strategy"] == "llm_summary_workspace_spill"

    def test_error_status_survives_the_digest(self) -> None:
        assert self._build(status="error").status == "error"

    def test_message_fields_carry_the_tool_and_format(self) -> None:
        msg = self._build(fmt="json")
        # the ToolMessage name routes the reply back to the right tool call
        assert msg.name == "search"
        info = read_offload(msg)
        assert info is not None and info["fmt"] == "json"
        assert info["producer"] == "search"
        assert f"{9000 / 1024:.1f} KB" in msg.content  # 1024, not 1025

    def test_existing_additional_kwargs_are_preserved(self) -> None:
        kw = self._build(extra={"custom": "keep"}).additional_kwargs
        assert kw["custom"] == "keep"

    def test_builder_uses_summary_verbatim(self) -> None:
        """Capping happens in _llm_summarize_output; the builder renders as-is."""

        msg = _summarized_compact_message(
            summary="a" * 500,
            tool_name="t",
            tool_call_id="c",
            reason="r",
            status="success",
            content_str="x",
            spilled=None,
            existing_additional_kwargs={},
        )
        assert "a" * 500 in msg.content


class TestOffloadKwargsFields:
    def test_every_field_is_set_from_the_inputs(self) -> None:
        info = _offload_kwargs(
            sandbox_path="/w/x.json", fmt="json", content_str="héllo", tool_name="t"
        )
        assert info["path"] == "/w/x.json"
        # utf-8 byte count, not char count: é is two bytes
        assert info["bytes"] == 6
        assert info["fmt"] == "json"
        assert info["producer"] == "t"
        assert info["records"] is None


class TestStubSpillBody:
    def test_stub_body_pieces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        content = json.dumps([{"i": i} for i in range(40)])
        msg = _stub_spill_message(
            content_str=content,
            fmt="json",
            sandbox_path=WROTE[1],
            tool_name="search",
            tool_call_id="call_1",
            reason="large_output",
            status="error",
            existing_additional_kwargs={"pre": 1},
        )
        assert "Returned 40 items" in msg.content
        assert f"{len(content) / 1024:.1f} KB" in msg.content
        assert WROTE[1] in msg.content
        assert "query_json" in msg.content
        assert msg.status == "error"
        kw = msg.additional_kwargs
        assert kw["compaction_strategy"] == "workspace_spill"
        assert kw["original_length"] == len(content)
        assert kw["pre"] == 1

        info = read_offload(msg)
        assert info is not None and info["producer"] == "search"

    def test_stub_text_body_suggests_grep_only(self) -> None:
        msg = _stub_spill_message(
            content_str="log line\n" * 300,
            fmt="text",
            sandbox_path="/w/x.txt",
            tool_name="run",
            tool_call_id="1",
            reason="r",
            status="success",
            existing_additional_kwargs={},
        )
        assert "grep" in msg.content
        assert "query_json" not in msg.content


class TestLLMSummarizeInternals:
    async def test_prompt_carries_tool_name_and_sample(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        _DIGEST_CAPTURE["messages"] = None
        result = await cm._llm_summarize_output(
            _RecordingDigestModel(), "HEAD" + "x" * 100_000 + "TAIL", "my_tool"
        )

        assert result == "ok"  # stripped
        system, human = _DIGEST_CAPTURE["messages"]
        assert isinstance(system, SystemMessage) and "4000" in system.content
        assert isinstance(human, HumanMessage)
        assert "Tool: my_tool" in human.content
        assert "HEAD" in human.content and "TAIL" in human.content

    async def test_unusable_payload_logs_and_falls_back(self) -> None:
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        async def swapping_wait_for(coro, timeout):
            _ = await coro
            from types import SimpleNamespace

            return SimpleNamespace(content=12345, junk="x")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm.asyncio, "wait_for", swapping_wait_for)
        monkeypatch.setattr(cm, "log", log)
        try:
            from tests.helpers import create_fake_llm

            out = await cm._llm_summarize_output(create_fake_llm(["fine"]), "content", "my_tool")
        finally:
            monkeypatch.undo()

        assert out is None
        matches = [(m, k) for m, k in log.records if "returned an unusable payload" in m]
        assert len(matches) == 1, log.records

    async def test_missing_content_attr_uses_empty_default(self) -> None:
        """getattr's '' default must survive: a message without .content yields
        an empty digest -> 'was empty' warning, not a crash or a phantom value."""
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        async def swapping_wait_for(coro, timeout):
            message = await coro
            from types import SimpleNamespace

            print("[SPY2] content:", repr(getattr(message, "content", "NO_ATTR"))[:50])
            return SimpleNamespace(no_content_attr=True)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm.asyncio, "wait_for", swapping_wait_for)
        monkeypatch.setattr(cm, "log", log)
        try:
            from tests.helpers import create_fake_llm

            out = await cm._llm_summarize_output(create_fake_llm(["fine"]), "content", "my_tool")
        finally:
            monkeypatch.undo()

        assert out is None
        matches = [(m, k) for m, k in log.records if "was empty" in m]
        assert len(matches) == 1
        # getattr defaults ('' vs None vs "XXXX") change which branch runs;
        # only the '' default reaches the was-empty warning
        assert matches[0][1] == {"tool_name": "my_tool"}

    async def test_over_cap_response_gets_truncation_suffix(self) -> None:
        out = await cm._llm_summarize_output(_OverCapDigestModel(), "content", "tool")
        assert out is not None
        assert out.endswith("…[digest truncated]")
        assert len(out) <= COMPACTION_SUMMARY_MAX_CHARS + len("…[digest truncated]")

    async def test_digest_at_exactly_the_cap_is_not_truncated(self) -> None:
        from langchain_core.messages import AIMessage

        class Exactly(BaseChatModel):
            @property
            def _llm_type(self) -> str:
                return "exactly"

            def _generate(self, *a, **k):
                raise NotImplementedError

            async def _agenerate(self, messages, stop=None, run_manager=None, **k):
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(content="x" * COMPACTION_SUMMARY_MAX_CHARS)
                        )
                    ]
                )

        out = await cm._llm_summarize_output(Exactly(), "content", "tool")
        assert out is not None
        # >= instead of > here would append the truncation suffix at the cap
        assert not out.endswith("[digest truncated]")

    async def test_cap_slice_rstrips_trailing_whitespace(self) -> None:
        from langchain_core.messages import AIMessage

        from app.constants.summarization import (
            COMPACTION_SUMMARY_MAX_CHARS as MAX,
        )

        class Spaced(BaseChatModel):
            @property
            def _llm_type(self) -> str:
                return "spaced"

            def _generate(self, *a, **k):
                raise NotImplementedError

            async def _agenerate(self, messages, stop=None, run_manager=None, **k):
                # the cap lands exactly on the two spaces, so rstrip() vs
                # lstrip() produces visibly different tails
                content = "a" * (MAX - 2) + "  " + "b" * 5
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

        out = await cm._llm_summarize_output(Spaced(), "content", "tool")
        assert out is not None
        # lstrip() instead of rstrip() would leave leading whitespace of the
        # slice and cut the 'a's instead
        head, _, _ = out.partition("…[digest truncated]")
        assert head.endswith("aaaa")  # rstrip removed the spaces after the a's
        assert not head.endswith(" ")

    async def test_timeout_is_enforced_per_call(self) -> None:
        timeouts: list = []
        real_wait = asyncio.wait_for

        async def spy_wait_for(coro, timeout):
            timeouts.append(timeout)
            return await real_wait(coro, timeout)

        with patch.object(cm.asyncio, "wait_for", side_effect=spy_wait_for):
            await cm._llm_summarize_output(_InstantDigestModel(), "small", "tool")
        assert timeouts == [cm.COMPACTION_SUMMARY_TIMEOUT_SECONDS]


class TestDigestWarningPayloads:
    """The fallback warnings carry the tool name and error type — operators
    grep for them when a lane degrades; they must not be able to go None."""

    async def test_llm_failure_warning_names_tool_and_error(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            out = await cm._llm_summarize_output(_BrokenModel(), "content", "my_tool")
        finally:
            monkeypatch.undo()

        assert out is None
        matches = [(m, k) for m, k in log.records if "LLM compaction summary failed" in m]
        assert len(matches) == 1
        _, kwargs = matches[0]
        # exact payload: nothing dropped, nothing degraded to None
        assert kwargs == {
            "tool_name": "my_tool",
            "error": "endpoint down",
            "error_type": "RuntimeError",
        }

    async def test_empty_digest_warning_names_tool(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            out = await cm._llm_summarize_output(create_fake_llm(["   "]), "content", "my_tool")
        finally:
            monkeypatch.undo()

        assert out is None
        matches = [(m, k) for m, k in log.records if "LLM compaction summary was empty" in m]
        assert len(matches) == 1
        assert matches[0][1] == {"tool_name": "my_tool"}


class TestKwargPlumbing:
    """compact_tool_output forwards identity/reason/tool kwargs into the
    spill write, the log payloads, and the message fields. A None slipped
    into any of those is invisible in happy-path assertions, so capture
    everything at every boundary and compare exactly."""

    async def test_spill_write_receives_identity_and_raw_content(self) -> None:
        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=None)
        content = json.dumps([{"i": i} for i in range(500)])
        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u-identity", "vfs_session_id": "c-identity"}}
            ),
            state={"messages": []},
        )

        captured: dict = {}

        async def fake_write(**kwargs):
            captured.update(kwargs)
            return ("/host/path", "/workspace/sessions/c-identity/x.json")

        async def handler(_req):
            return ToolMessage(content=content, tool_call_id="call_1", name="search")

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=fake_write,
        ):
            await mw.awrap_tool_call(request, handler)

        assert captured["user_id"] == "u-identity"
        assert captured["conversation_id"] == "c-identity"
        # RAW content, not a preview or wrapper
        assert captured["content"] == content
        assert captured["relative_path"].startswith("tool_outputs/search_")

    async def test_digest_failure_warning_carries_tool_kwarg(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())

            async def handler(_req):
                return ToolMessage(content="x" * 5000, tool_call_id="call_1", name="search")

            await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        fails = [(m, k) for m, k in log.records if "LLM compaction summary failed" in m]
        assert fails, log.records
        assert fails[0][1]["tool_name"] == "search"

    async def test_no_spill_warning_carries_tool_kwarg(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())

            async def handler(_req):
                return ToolMessage(content="x" * 5000, tool_call_id="call_1", name="search")

            await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        stops = [m for m, _ in log.records if "No spill and no LLM digest" in m]
        assert stops, log.records


class TestCompactToolOutputBoundary:
    """Every kwarg compact_tool_output forwards must land somewhere observable
    — message fields, log payloads, write kwargs — or a None can slip through."""

    async def test_digest_success_path_pins_every_forwarded_kwarg(self) -> None:
        from langchain_core.messages import AIMessage

        captured: dict = {}

        class Capturing(BaseChatModel):
            @property
            def _llm_type(self) -> str:
                return "capturing"

            def _generate(self, *a, **k):
                raise NotImplementedError

            async def _agenerate(self, messages, stop=None, run_manager=None, **k):
                captured["messages"] = messages
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage(content="the digest"))]
                )

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=Capturing())
        content = json.dumps([{"i": i} for i in range(500)])
        original = ToolMessage(
            content=content,
            tool_call_id="call_1",
            name="search",
            additional_kwargs={"custom": "keep"},
        )
        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "conv1"}}
            ),
            state={"messages": []},
        )

        async def handler(_req):
            return original

        wrote: dict = {}

        async def fake_write(**kwargs):
            wrote.update(kwargs)
            return ("/host", "/workspace/sessions/conv1/tool_outputs/x.json")

        with patch(
            "app.agents.middleware.compaction.write_session_file",
            new_callable=AsyncMock,
            side_effect=fake_write,
        ):
            result = await mw.awrap_tool_call(request, handler)

        from langgraph.types import Command

        assert isinstance(result, Command)
        msg = result.update["messages"][0]
        # tool_name reached both the message name and the summarizer prompt
        assert msg.name == "search"
        assert msg.content.startswith("[search compacted — large_output")
        human = captured["messages"][1]
        assert "Tool: search" in human.content
        # reason reached the header; size reached the pointer (1024-based)
        kb = f"{len(content) / 1024:.1f} KB"
        assert kb in msg.content
        # caller's kwargs survive the merge
        assert msg.additional_kwargs["custom"] == "keep"

    async def test_juicefs_warning_payload_is_exact(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())

            async def handler(_req):
                return ToolMessage(content="x" * 5000, tool_call_id="c1", name="search")

            await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        juice = [(m, k) for m, k in log.records if "Workspace unavailable" in m]
        assert len(juice) == 1
        msg, kwargs = juice[0]
        assert kwargs == {"tool_name": "search", "error_type": "JuiceFSUnavailable"}

    async def test_spill_error_warning_payload_is_exact(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())

            async def handler(_req):
                return ToolMessage(content="x" * 5000, tool_call_id="c1", name="search")

            with patch(
                "app.agents.middleware.compaction.write_session_file",
                new_callable=AsyncMock,
                side_effect=OSError("disk exploded"),
            ):
                await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        errs = [(m, k) for m, k in log.records if "Workspace spill failed" in m]
        assert len(errs) == 1
        _, kwargs = errs[0]
        assert kwargs["tool_name"] == "search"
        assert kwargs["error_type"] == "OSError"

    async def test_truncation_path_pins_message_fields_and_kwargs(self) -> None:
        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=None)

            async def handler(_req):
                return ToolMessage(
                    content="x" * 5000,
                    tool_call_id="call_9",
                    name="run_query",
                    additional_kwargs={"keepme": True},
                )

            await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        stops = [(m, k) for m, k in log.records if "No spill and no LLM digest" in m]
        assert len(stops) == 1
        _, kwargs = stops[0]
        # exact payload: tool_name present (not None), nothing extra
        assert kwargs == {"tool_name": "search"}


class TestTruncateTierKwargs:
    """The truncation fallback receives the caller's context intact."""

    async def test_truncate_tier_receives_full_context(self) -> None:
        seen: dict = {}

        def fake_truncate(**kwargs):
            seen.update(kwargs)
            return ToolMessage(
                content="[Compacted in context]",
                tool_call_id="call_9",
                name=kwargs.get("tool_name", ""),
            )

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())
        content = json.dumps([{"i": i} for i in range(500)])
        request = SimpleNamespace(
            tool_call={"name": "run_query", "id": "call_9", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "conv1"}}
            ),
            state={"messages": []},
        )

        async def handler(_req):
            return ToolMessage(
                content=content,
                tool_call_id="call_9",
                name="run_query",
                additional_kwargs={"keepme": True},
            )

        async def no_digest(llm, content_str, tool_name):
            return None

        with (
            patch.object(cm, "_write_raw_output", side_effect=RuntimeError("no storage")),
            patch.object(cm, "_llm_summarize_output", side_effect=no_digest),
            patch.object(cm, "_truncate_in_context", side_effect=fake_truncate),
        ):
            result = await mw.awrap_tool_call(request, handler)
            print("\nRESULT:", type(result).__name__, getattr(result, "additional_kwargs", {}))

        assert seen.get("tool_name") == "run_query", seen
        assert seen["reason"].startswith("large_output")
        assert seen["status"] == "success"
        assert seen["existing_additional_kwargs"] == {"keepme": True}
        assert seen["content_str"] == content


class TestNoSpillWarningPayload:
    async def test_truncation_warning_kwargs_are_exact(self) -> None:
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        async def no_digest(llm, content_str, tool_name):
            return None

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)

        def raise_no_storage(*a, **k):
            raise RuntimeError("no storage")

        monkeypatch.setattr(cm, "_write_raw_output", raise_no_storage)
        monkeypatch.setattr(cm, "_llm_summarize_output", no_digest)
        try:
            await cm.compact_tool_output(
                content="x" * 5000,
                tool_name="run_query",
                tool_call_id="c9",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.5,
                max_output_chars=1000,
                compaction_threshold=0.4,
            )
        finally:
            monkeypatch.undo()

        matches = [(m, k) for m, k in log.records if "No spill and no LLM digest" in m]
        assert len(matches) == 1
        assert matches[0][1] == {"tool_name": "run_query"}


class TestStubSpillKwargsExact:
    def test_additional_kwargs_dict_is_exact(self) -> None:
        from app.agents.middleware.compaction import _stub_spill_message

        content = json.dumps([{"i": 1}])
        msg = _stub_spill_message(
            content_str=content,
            fmt="json",
            sandbox_path=WROTE[1],
            tool_name="search",
            tool_call_id="call_1",
            reason="large_output",
            status="success",
            existing_additional_kwargs={},
        )
        # exact dict: a renamed or dropped key cannot hide
        assert msg.additional_kwargs["compaction_reason"] == "large_output"
        assert msg.additional_kwargs["compaction_strategy"] == "workspace_spill"


class TestDigestKBFigure:
    def test_kb_figure_uses_1024(self) -> None:
        """1024 vs 1025 differs at this length: 100000/1024=97.7, /1025=97.6."""
        from app.agents.middleware.compaction import _summarized_compact_message

        msg = _summarized_compact_message(
            summary="s",
            tool_name="t",
            tool_call_id="c",
            reason="r",
            status="success",
            content_str="z" * 100_000,
            spilled=("json", "/w/x.json"),
            existing_additional_kwargs={},
        )
        assert "97.7 KB" in msg.content


class TestSignatureDefaultsAndBranches:
    """Signature defaults and branch polarity on compact_tool_output itself."""

    def test_default_always_persist_is_false(self) -> None:
        """Without always_persist, a small output must stay inline."""
        result = asyncio.run(
            cm.compact_tool_output(
                content="small",
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="c1",
                context_usage=0.0,
                max_output_chars=100_000,
                compaction_threshold=0.4,
            )
        )
        assert result is None

    def test_small_output_stays_inline_without_always_persist(self) -> None:
        """The default always_persist=False must leave small outputs inline."""
        result = asyncio.run(
            cm.compact_tool_output(
                content="small output",
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="c1",
                context_usage=0.0,
                max_output_chars=100_000,
                compaction_threshold=0.4,
            )
        )
        assert result is None


class TestNoWorkspaceIdentityWarningPayload:
    async def test_warning_kwargs_are_exact(self) -> None:
        log = _StubLog()

        async def fake_digest(llm, content_str, tool_name):
            return "digest"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            await cm.compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id=None,
                conversation_id=None,
                context_usage=0.5,
                max_output_chars=100_000,
                compaction_threshold=0.4,
                summary_llm=_RecordingDigestModel(),
            )
        finally:
            monkeypatch.undo()

        matches = [(m, k) for m, k in log.records if "no workspace identity" in m]
        assert len(matches) == 1
        _, kwargs = matches[0]
        # exact payload: nothing dropped or set to None
        assert kwargs == {"tool_name": "search", "user_id": "missing", "conversation_id": "missing"}

    async def test_partial_identity_shows_set(self) -> None:
        log = _StubLog()

        async def fake_digest(llm, content_str, tool_name):
            return "d"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            await cm.compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id=None,
                context_usage=0.5,
                max_output_chars=100_000,
                compaction_threshold=0.4,
                summary_llm=_RecordingDigestModel(),
            )
        finally:
            monkeypatch.undo()

        matches = [(m, k) for m, k in log.records if "no workspace identity" in m]
        assert len(matches) == 1
        assert matches[0][1] == {
            "tool_name": "search",
            "user_id": "set",
            "conversation_id": "missing",
        }


class TestFullKwargsCapture:
    """Patch every internal function, drive all three tiers, and assert the
    EXACT kwargs each receives — any dropped or None'd kwarg fails."""

    async def test_digest_path_kwargs(self) -> None:
        import json as _json

        calls = {}

        async def fake_write(**kw):
            return ("/host", "/workspace/sessions/c/tool_outputs/x.json")

        async def fake_digest(llm, content_str, tool_name):
            calls["digest"] = {"content_str": content_str, "tool_name": tool_name}
            return "the digest"

        captured_msg = {}

        def fake_summarized(**kw):
            calls["summarized"] = dict(kw)
            msg = ToolMessage(
                content=f"[{kw['tool_name']}] {kw['summary']}",
                tool_call_id=kw["tool_call_id"],
                name=kw["tool_name"],
                status=kw["status"],
            )
            captured_msg["msg"] = msg
            return msg

        class _Digest(BaseChatModel):
            @property
            def _llm_type(self):
                return "digest"

            def _generate(self, *a, **k):
                raise NotImplementedError

            async def _agenerate(self, messages, stop=None, run_manager=None, **k):
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage(content="the digest"))]
                )

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_Digest())
        content = _json.dumps([{"i": i} for i in range(300)])

        async def handler(_req):
            return ToolMessage(content=content, tool_call_id="call_1", name="search")

        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "c1"}}
            ),
            state={"messages": []},
        )

        with (
            patch.object(cm, "_write_raw_output", side_effect=fake_write),
            patch.object(cm, "_summarized_compact_message", side_effect=fake_summarized),
        ):
            await mw.awrap_tool_call(request, handler)

        s = calls["summarized"]
        assert s["summary"] == "the digest"
        assert s["tool_name"] == "search"
        assert s["tool_call_id"] == "call_1"
        assert s["reason"].startswith("large_output")
        assert s["status"] == "success"
        assert s["content_str"] == content
        assert s["spilled"] is not None
        assert s["existing_additional_kwargs"] == {}

    async def test_truncate_path_kwargs(self) -> None:
        import json as _json

        from app.agents.middleware import compaction as cm

        calls = {}

        async def fake_write(**kw):
            raise RuntimeError("no storage")

        async def fake_no_digest(llm, content_str, tool_name):
            return None

        def fake_truncate(**kw):
            calls.update(kw)
            return ToolMessage(
                content="[Compacted in context]",
                tool_call_id=kw["tool_call_id"],
                name=kw["tool_name"],
                status=kw["status"],
            )

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        content = _json.dumps([{"i": i} for i in range(300)])

        async def handler(_req):
            return ToolMessage(content=content, tool_call_id="call_1", name="search")

        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "c1"}}
            ),
            state={"messages": []},
        )

        with (
            patch.object(cm, "_write_raw_output", side_effect=fake_write),
            patch.object(cm, "_llm_summarize_output", side_effect=fake_no_digest),
            patch.object(cm, "_truncate_in_context", side_effect=fake_truncate),
        ):
            _ = await mw.awrap_tool_call(request, handler)

        assert calls["content_str"] == content
        assert calls["tool_name"] == "search"
        assert calls["tool_call_id"] == "call_1"
        assert calls["reason"].startswith("large_output")
        assert calls["status"] == "success"
        assert calls["existing_additional_kwargs"] == {}

    async def test_stub_spill_path_kwargs(self) -> None:
        import json as _json

        from app.agents.middleware import compaction as cm

        calls = {}

        async def fake_write(**kw):
            return ("json", "/workspace/sessions/c/x.json")

        def fake_stub(**kw):
            calls.update(kw)
            return ToolMessage(
                content=f"[{kw['tool_name']}] {kw['sandbox_path']}",
                tool_call_id=kw["tool_call_id"],
                name=kw["tool_name"],
                status=kw["status"],
            )

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        content = _json.dumps([{"i": i} for i in range(300)])

        async def handler(_req):
            return ToolMessage(content=content, tool_call_id="call_1", name="search")

        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "c1"}}
            ),
            state={"messages": []},
        )

        with (
            patch.object(cm, "_write_raw_output", side_effect=fake_write),
            patch.object(cm, "_stub_spill_message", side_effect=fake_stub),
        ):
            await mw.awrap_tool_call(request, handler)

        assert calls["fmt"] == "json"
        assert calls["sandbox_path"] == "/workspace/sessions/c/x.json"
        assert calls["content_str"] == content
        assert calls["tool_name"] == "search"
        assert calls["tool_call_id"] == "call_1"
        assert calls["reason"].startswith("large_output")
        assert calls["status"] == "success"
        assert calls["existing_additional_kwargs"] == {}


class TestUnusablePayloadKwargs:
    """The narrowing branch must reject non-str/list content."""

    async def test_unusable_payload_kwargs_are_exact(self) -> None:
        from types import SimpleNamespace

        from app.agents.middleware import compaction as cm

        class _IntContent:
            async def ainvoke(self, messages, **kwargs):
                return SimpleNamespace(content=12345)

        log = _StubLog()
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            out = await cm._llm_summarize_output(_IntContent(), "content", "my_tool")
        finally:
            monkeypatch.undo()

        assert out is None
        matches = [(m, k) for m, k in log.records if "unusable payload" in m]
        assert len(matches) == 1
        # every kwarg present, nothing None'd or dropped
        assert matches[0][1] == {"tool_name": "my_tool", "payload_type": "int"}

    async def test_no_workspace_warning_missing_strings_exact(self) -> None:
        """The 'set'/'missing' strings in the identity-warning kwargs are
        load-bearing — operators grep for them."""
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        async def fake_digest(llm, content_str, tool_name):
            return "d"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            await cm.compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id=None,
                conversation_id=None,
                context_usage=0.5,
                max_output_chars=100_000,
                compaction_threshold=0.4,
                summary_llm=None,
            )
        finally:
            monkeypatch.undo()

        matches = [(m, k) for m, k in log.records if "no workspace identity" in m]
        assert len(matches) == 1
        _, kwargs = matches[0]
        assert "XXmissingXX" not in kwargs.values()
        assert "MISSING" not in kwargs.values()
        assert kwargs["user_id"] == "missing"
        assert kwargs["conversation_id"] == "missing"


class TestWritePathAndIdentityKwargs:
    """Kills the remaining write-path and identity-warning mutants."""

    def test_write_raw_output_timestamp_format_is_exact(self) -> None:
        import asyncio
        import re as _re

        from app.agents.middleware.compaction import _write_raw_output as wro_fn

        captured = {}

        async def fake_write(*, user_id, conversation_id, relative_path, content):
            captured["relative_path"] = relative_path
            return ("/h", "/w/s/c/" + relative_path)

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "write_session_file", fake_write)
        try:
            asyncio.run(
                wro_fn(content_str='{"a": 1}', tool_name="search", user_id="u", conversation_id="c")
            )
        finally:
            monkeypatch.undo()

        m = _re.search(
            r"search_\d{8}_\d{6}_[0-9a-f]{8}\.(json|jsonl|txt)$", captured["relative_path"]
        )
        assert m is not None, captured["relative_path"]

    async def test_no_identity_warning_conversation_id_set_variant(self) -> None:
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        async def fake_digest(llm, content_str, tool_name):
            return "d"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            await cm.compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id=None,
                context_usage=0.5,
                max_output_chars=100_000,
                compaction_threshold=0.4,
                summary_llm=None,
            )
        finally:
            monkeypatch.undo()

        matches = [(m, k) for m, k in log.records if "no workspace identity" in m]
        assert len(matches) == 1
        _, kwargs = matches[0]
        assert kwargs["user_id"] == "set"
        assert kwargs["conversation_id"] == "missing"

    async def test_spill_error_payload_includes_message_and_type(self) -> None:
        from app.agents.middleware import compaction as cm

        log = _StubLog()

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cm, "log", log)
        try:
            mw = WorkspaceCompactionMiddleware(max_output_chars=1000, summary_llm=_BrokenModel())

            async def handler(_req):
                return ToolMessage(content="x" * 5000, tool_call_id="c1", name="search")

            with patch(
                "app.agents.middleware.compaction.write_session_file",
                new_callable=AsyncMock,
                side_effect=OSError("disk exploded badly"),
            ):
                await mw.awrap_tool_call(_request(), handler)
        finally:
            monkeypatch.undo()

        errs = [(m, k) for m, k in log.records if "Workspace spill failed" in m]
        assert len(errs) == 1
        _, kwargs = errs[0]
        # exact payload: every field present with real values
        assert kwargs["tool_name"] == "search"
        assert kwargs["error"] == "disk exploded badly"
        assert kwargs["error_type"] == "OSError"

    async def test_stub_spill_kwargs_merge_preserves_existing(self) -> None:
        import json as _json

        from app.agents.middleware import compaction as cm

        calls = {}

        async def fake_write(**kw):
            return ("json", "/workspace/sessions/c/x.json")

        def fake_stub(**kw):
            calls.update(kw)
            return ToolMessage(content="stub", tool_call_id="call_1", name="search")

        mw = WorkspaceCompactionMiddleware(max_output_chars=1000)
        content = _json.dumps([{"i": i} for i in range(300)])

        async def handler(_req):
            return ToolMessage(
                content=content,
                tool_call_id="call_1",
                name="search",
                additional_kwargs={"pre": True},
            )

        request = SimpleNamespace(
            tool_call={"name": "search", "id": "call_1", "args": {}},
            runtime=SimpleNamespace(
                config={"configurable": {"user_id": "u1", "vfs_session_id": "c1"}}
            ),
            state={"messages": []},
        )

        with (
            patch.object(cm, "_write_raw_output", side_effect=fake_write),
            patch.object(cm, "_stub_spill_message", side_effect=fake_stub),
        ):
            await mw.awrap_tool_call(request, handler)

        assert calls["existing_additional_kwargs"] == {"pre": True}
