"""Brutal behavior tests for WorkspaceCompactionMiddleware.

This middleware is what makes "large tool output is stored in the VFS" real:
oversized tool results are offloaded to /workspace/sessions/<conv>/tool_outputs/
and replaced inline with a preview + path. It had no tests. We mock the one
boundary (write_session_file → JuiceFS) and exercise the real decision and
persistence logic.
"""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware.compaction import (
    COMPACTION_TRUNCATED_MARKER,
    WorkspaceCompactionMiddleware,
    _spill_to_workspace,
    _summarize_output,
    _truncate_in_context,
    compact_tool_output,
    estimate_context_usage,
    should_compact_output,
)
from app.constants.log_tags import LogTag
from app.constants.offload import OFFLOAD_KEY
from app.constants.summarization import (
    COMPACTION_FALLBACK_HEAD_CHARS,
    COMPACTION_FALLBACK_TAIL_CHARS,
    MIN_COMPACTION_SIZE,
)
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
        """Inline media is the payload; it must not be truncated by the fallback.

        Uses the app's canonical block shape (``image_content_block``) and a
        text part big enough to force compaction — so the media gate itself is
        what keeps the result untouched.
        """
        mw = WorkspaceCompactionMiddleware(max_output_chars=10)
        blocks = [
            {"type": "text", "text": "here is the screenshot" + "x" * 600},
            {"type": "image", "base64": "A" * 100_000, "mime_type": "image/png"},
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

    def test_list_preview_pins_exact_text(self) -> None:
        summary = _summarize_output(json.dumps([{"i": i} for i in range(42)]), "search")
        # exactly the first 3 items, dumped, capped at 200 chars, plus the marker
        assert summary == (
            '[search] Returned 42 items. '
            'Preview: [{"i": 0}, {"i": 1}, {"i": 2}]...'
        )

    def test_list_preview_is_capped_at_200_chars(self) -> None:
        payload = [{"pad": "p" * 80} for _ in range(3)]
        summary = _summarize_output(json.dumps(payload), "search")
        preview = summary.split("Preview: ", 1)[1]
        # the full dump is 280 chars; the preview is cut at exactly 200 + "..."
        assert preview == json.dumps(payload)[:200] + "..."

    def test_list_preview_shows_all_items_when_three_or_fewer(self) -> None:
        summary = _summarize_output(json.dumps([{"a": 1}, {"b": 2}]), "search")
        assert summary == '[search] Returned 2 items. Preview: [{"a": 1}, {"b": 2}]...'

    def test_list_preview_slices_to_three_when_four_items(self) -> None:
        # ``len(data) > 3`` (not ``> 4``): exactly 4 items must still preview 3
        summary = _summarize_output(json.dumps([{"i": i} for i in range(4)]), "search")
        assert summary == (
            "[search] Returned 4 items. Preview: "
            '[{"i": 0}, {"i": 1}, {"i": 2}]...'
        )

    def test_dict_preview_pins_exact_text(self) -> None:
        summary = _summarize_output(json.dumps({"a": 1, "b": 2}), "fetch")
        assert summary == "[fetch] Returned object with keys: ['a', 'b']..."

    def test_dict_preview_caps_at_five_keys(self) -> None:
        data = {f"k{i}": i for i in range(7)}
        summary = _summarize_output(json.dumps(data), "fetch")
        assert summary == "[fetch] Returned object with keys: ['k0', 'k1', 'k2', 'k3', 'k4']..."

    def test_long_plain_text_is_cut_at_500_chars(self) -> None:
        summary = _summarize_output("z" * 600, "bash")
        assert summary == "[bash] " + "z" * 500 + "..."

    def test_plain_text_at_exactly_500_is_not_truncated(self) -> None:
        summary = _summarize_output("q" * 500, "bash")
        assert summary == "[bash] " + "q" * 500

    def test_plain_text_at_501_is_truncated(self) -> None:
        # ``len(content) > 500`` (not ``> 501``): 501 chars is already cut
        summary = _summarize_output("r" * 501, "bash")
        assert summary == "[bash] " + "r" * 500 + "..."

    def test_short_plain_text_is_kept_verbatim(self) -> None:
        summary = _summarize_output("hello", "bash")
        assert summary == "[bash] hello"

    def test_invalid_json_falls_through_to_plain_text(self) -> None:
        summary = _summarize_output("not json at all", "bash")
        assert summary == "[bash] not json at all"


class TestEstimateContextUsage:
    def test_empty_messages_use_no_context(self) -> None:
        assert estimate_context_usage([], 1000) == 0.0

    def test_chars_to_tokens_heuristic(self) -> None:
        # 101 chars // 4 = 25 tokens out of a 1000-token window
        msgs = [SimpleNamespace(content="a" * 101)]
        assert estimate_context_usage(msgs, 1000) == pytest.approx(25 / 1000)

    def test_messages_without_content_count_zero(self) -> None:
        assert estimate_context_usage([object()], 1000) == 0.0

    def test_usage_is_capped_at_full_window(self) -> None:
        msgs = [SimpleNamespace(content="z" * 8000)]  # 2000 tokens > 1000-token window
        assert estimate_context_usage(msgs, 1000) == 1.0

    def test_usage_is_proportional_across_messages(self) -> None:
        msgs = [SimpleNamespace(content="a" * 100), SimpleNamespace(content="b" * 100)]
        assert estimate_context_usage(msgs, 200) == pytest.approx(0.25)


class TestShouldCompactOutputDirect:
    def test_exact_large_output_reason(self) -> None:
        ok, reason = should_compact_output(
            "x" * 1500,
            "search",
            0.0,
            max_output_chars=1000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert ok is True
        assert reason == "large_output (1500 chars)"

    def test_exact_context_threshold_reason(self) -> None:
        ok, reason = should_compact_output(
            "y" * 600,
            "search",
            0.731,
            max_output_chars=100_000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert ok is True
        assert reason == "context_threshold (73.1% used)"

    def test_size_exactly_at_max_output_chars_is_not_large(self) -> None:
        # `>` not `>=`: at the cap exactly, only the context trigger may fire
        ok, reason = should_compact_output(
            "z" * 1000,
            "search",
            0.0,
            max_output_chars=1000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert (ok, reason) == (False, "")

    def test_context_usage_exactly_at_threshold_still_compacts(self) -> None:
        # `>=` not `>`: exactly at the threshold must still trigger
        ok, reason = should_compact_output(
            "w" * 600,
            "search",
            0.65,
            max_output_chars=100_000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert ok is True
        assert reason == "context_threshold (65.0% used)"

    def test_size_exactly_at_minimum_is_not_skipped(self) -> None:
        # `size < MIN` (not `<=`): at the boundary the context trigger still fires
        ok, reason = should_compact_output(
            "m" * MIN_COMPACTION_SIZE,
            "search",
            0.99,
            max_output_chars=100_000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert ok is True
        assert reason == "context_threshold (99.0% used)"

    def test_excluded_short_circuits_every_trigger(self) -> None:
        ok, reason = should_compact_output(
            "x" * 50_000,
            "bash",
            0.99,
            max_output_chars=10,
            compaction_threshold=0.1,
            always_persist=True,
            excluded=True,
        )
        assert (ok, reason) == (False, "")

    def test_below_minimum_returns_exactly_empty_reason(self) -> None:
        # the MIN-size branch must return "" — a mutated "XXXX" reason is caught
        ok, reason = should_compact_output(
            "x" * 10,
            "search",
            0.0,
            max_output_chars=1000,
            compaction_threshold=0.65,
            always_persist=False,
            excluded=False,
        )
        assert (ok, reason) == (False, "")


class _FrozenClock:
    """Deterministic ``datetime`` replacement for the spill path.

    Pins that the timestamp is taken in UTC: ``datetime.now`` must be called
    with ``UTC`` — a ``now(None)`` mutant would silently switch the filename
    timestamp to local time.
    """

    @classmethod
    def now(cls, tz=None):  # NOSONAR python:S3242 signature mirrors datetime.now
        assert tz is UTC, f"datetime.now must be called with UTC, got {tz!r}"
        return datetime(2026, 8, 11, 12, 34, 56, tzinfo=tz)


class TestSpillToWorkspace:
    async def test_spill_pins_path_body_and_offload_marker(self) -> None:
        # "café " is 5 chars / 6 utf-8 bytes, so the char-count and byte-count
        # fields are observably different (bytes field must use utf-8 length).
        # 102400 chars makes size_kb exactly 100.0 — a ``/ 1024`` → ``/ 1025``
        # mutant would render 99.9 and be caught by the exact body.
        content_str = "café " * 20480  # 102400 chars, 122880 bytes
        existing = {"pre_existing": 1}
        reason = "large_output (102400 chars)"
        real_hex = hashlib.md5(content_str.encode(), usedforsecurity=False).hexdigest()

        with (
            patch("app.agents.middleware.compaction.datetime", _FrozenClock),
            patch(
                "app.agents.middleware.compaction.write_session_file",
                new_callable=AsyncMock,
                return_value=WROTE,
            ) as mock_write,
            patch("app.agents.middleware.compaction.log") as mock_log,
            patch("app.agents.middleware.compaction.hashlib.md5") as mock_md5,
        ):
            mock_md5.return_value.hexdigest.return_value = real_hex
            msg = await _spill_to_workspace(
                content_str=content_str,
                tool_name="search",
                tool_call_id="call_9",
                user_id="u1",
                conversation_id="conv1",
                reason=reason,
                status="success",
                existing_additional_kwargs=existing,
            )

        # the digest is taken from the RAW utf-8 bytes, marked non-security
        mock_md5.assert_called_once_with(content_str.encode(), usedforsecurity=False)
        rel_path = f"tool_outputs/search_20260811_123456_{real_hex[:8]}.txt"
        mock_write.assert_awaited_once_with(
            user_id="u1",
            conversation_id="conv1",
            relative_path=rel_path,
            content=content_str,
        )
        assert msg.tool_call_id == "call_9"
        assert msg.name == "search"
        assert msg.status == "success"
        assert msg.content == (
            f"{_summarize_output(content_str, 'search')}\n\n"
            f"[Full output (100.0 KB / 102400 chars) stored at: {WROTE[1]}]\n"
            "[Do NOT `read` the whole file back into context, that undoes the offload. "
            f"To pull just what you need, use `grep` to pull matching lines; `bash` and "
            f"spawn_subagent also work for {WROTE[1]}.]"
        )
        assert msg.additional_kwargs == {
            **existing,
            "workspace_path": WROTE[1],
            "original_length": 102400,
            "compacted": True,
            "compaction_reason": reason,
            "compaction_strategy": "workspace_spill",
            OFFLOAD_KEY: {
                "path": WROTE[1],
                "bytes": 122880,
                "fmt": "text",
                "producer": "search",
                "records": None,
            },
        }
        mock_log.info.assert_called_once_with(
            f"{LogTag.AGENT} Compacted tool output",
            tool_name="search",
            content_chars=102400,
            sandbox_path=WROTE[1],
            reason=reason,
        )

    async def test_spill_json_fmt_gets_json_extension_and_json_mining_hint(self) -> None:
        content_str = json.dumps([{"i": i} for i in range(10)])  # 100 chars
        with (
            patch("app.agents.middleware.compaction.datetime", _FrozenClock),
            patch(
                "app.agents.middleware.compaction.write_session_file",
                new_callable=AsyncMock,
                return_value=WROTE,
            ) as mock_write,
        ):
            msg = await _spill_to_workspace(
                content_str=content_str,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                reason="large_output",
                status="error",
                existing_additional_kwargs={},
            )

        assert mock_write.await_args.kwargs["relative_path"].endswith(".json")
        assert msg.additional_kwargs[OFFLOAD_KEY]["fmt"] == "json"
        assert msg.status == "error"  # error results stay errors after the spill
        # exact body pins the json mining hint (a mutated hint string must fail)
        assert msg.content == (
            "[search] Returned 10 items. Preview: "
            '[{"i": 0}, {"i": 1}, {"i": 2}]...\n\n'
            f"[Full output (0.1 KB / 100 chars) stored at: {WROTE[1]}]\n"
            "[Do NOT `read` the whole file back into context, that undoes the offload. "
            "To pull just what you need, prefer `query_json` (structured records) or "
            f"`grep` (text); `bash` and spawn_subagent also work for {WROTE[1]}.]"
        )

    async def test_spill_jsonl_fmt_gets_jsonl_extension(self) -> None:
        content_str = "\n".join(json.dumps({"i": i}) for i in range(3))
        with (
            patch("app.agents.middleware.compaction.datetime", _FrozenClock),
            patch(
                "app.agents.middleware.compaction.write_session_file",
                new_callable=AsyncMock,
                return_value=WROTE,
            ) as mock_write,
        ):
            msg = await _spill_to_workspace(
                content_str=content_str,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                reason="large_output",
                status="success",
                existing_additional_kwargs={},
            )

        assert mock_write.await_args.kwargs["relative_path"].endswith(".jsonl")
        assert msg.additional_kwargs[OFFLOAD_KEY]["fmt"] == "jsonl"
        assert "prefer `query_json` (structured records) or `grep` (text)" in msg.content


class TestCompactToolOutputDirect:
    async def test_media_blocks_skip_compaction_entirely(self) -> None:
        # Big text alongside the image: if the media check were inverted the
        # extracted text would trigger a spill, so a skipped spill proves the
        # media gate itself short-circuits.
        with patch(
            "app.agents.middleware.compaction._spill_to_workspace",
            new_callable=AsyncMock,
        ) as mock_spill:
            result = await compact_tool_output(
                content=[
                    {"type": "text", "text": "x" * 10_000},
                    {"type": "image", "base64": "A" * 100, "mime_type": "image/png"},
                ],
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.99,
                max_output_chars=10,
                compaction_threshold=0.5,
            )

        assert result is None
        mock_spill.assert_not_awaited()

    async def test_excluded_output_returns_none(self) -> None:
        result = await compact_tool_output(
            content="x" * 10_000,
            tool_name="bash",
            tool_call_id="c1",
            user_id="u1",
            conversation_id="conv1",
            context_usage=0.99,
            max_output_chars=10,
            compaction_threshold=0.5,
            excluded=True,
        )
        assert result is None

    async def test_small_output_returns_none(self) -> None:
        result = await compact_tool_output(
            content="small",
            tool_name="search",
            tool_call_id="c1",
            user_id="u1",
            conversation_id="conv1",
            context_usage=0.0,
            max_output_chars=10,
            compaction_threshold=0.5,
        )
        assert result is None

    async def test_passes_exact_args_to_decision(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(False, ""),
            ) as mock_decide,
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
            ) as mock_spill,
        ):
            result = await compact_tool_output(
                content="abc",
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.42,
                max_output_chars=1234,
                compaction_threshold=0.5,
                always_persist=True,
                excluded=False,
            )

        assert result is None
        mock_decide.assert_called_once_with(
            "abc",
            "search",
            0.42,
            max_output_chars=1234,
            compaction_threshold=0.5,
            always_persist=True,
            excluded=False,
        )
        mock_spill.assert_not_awaited()

    async def test_spill_called_with_exact_kwargs(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output (5000 chars)"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(spilled=True),
            ) as mock_spill,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c7",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
                status="error",
                existing_additional_kwargs={"k": "v"},
            )

        assert result.spilled is True
        mock_spill.assert_awaited_once_with(
            content_str="x" * 5000,
            tool_name="search",
            tool_call_id="c7",
            user_id="u1",
            conversation_id="conv1",
            reason="large_output (5000 chars)",
            status="error",
            existing_additional_kwargs={"k": "v"},
        )

    async def test_block_list_is_text_extracted_not_reprd(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
                return_value=SimpleNamespace(spilled=True),
            ) as mock_spill,
        ):
            result = await compact_tool_output(
                content=[{"type": "text", "text": "hello"}, "world"],
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.0,
                max_output_chars=5,
                compaction_threshold=0.65,
            )

        assert result.spilled is True
        assert mock_spill.await_args.kwargs["content_str"] == "hello\nworld"

    async def test_missing_identity_truncates_with_exact_args(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "context_threshold (90.0% used)"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
            patch("app.agents.middleware.compaction.log") as mock_log,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c7",
                user_id=None,
                conversation_id=None,
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
                status="error",
                existing_additional_kwargs={"k": "v"},
            )

        assert result.truncated is True
        mock_truncate.assert_called_once_with(
            content_str="x" * 5000,
            tool_name="search",
            tool_call_id="c7",
            reason="context_threshold (90.0% used)",
            status="error",
            existing_additional_kwargs={"k": "v"},
        )
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Compaction has no workspace identity; truncating in context instead",
            tool_name="search",
            user_id="missing",
            conversation_id="missing",
        )

    async def test_omitted_status_defaults_to_success(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
            patch("app.agents.middleware.compaction.log"),
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id=None,
                conversation_id=None,
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        # status was omitted → the signature default "success" must flow through
        assert mock_truncate.call_args.kwargs["status"] == "success"

    async def test_omitted_always_persist_defaults_to_false(self) -> None:
        with patch(
            "app.agents.middleware.compaction.should_compact_output",
            return_value=(False, ""),
        ) as mock_decide:
            result = await compact_tool_output(
                content="small",
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.0,
                max_output_chars=10,
                compaction_threshold=0.5,
            )

        assert result is None
        assert mock_decide.call_args.kwargs["always_persist"] is False

    async def test_omitted_excluded_defaults_to_false(self) -> None:
        with patch(
            "app.agents.middleware.compaction.should_compact_output",
            return_value=(True, "large_output"),
        ) as mock_decide, patch(
            "app.agents.middleware.compaction._spill_to_workspace",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(spilled=True),
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.spilled is True
        assert mock_decide.call_args.kwargs["excluded"] is False

    async def test_empty_conversation_id_logs_user_id_as_set(self) -> None:
        # "" is falsy → identity branch fires with user_id truthy: the log must
        # say "set" for the user and "missing" for the conversation
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ),
            patch("app.agents.middleware.compaction.log") as mock_log,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Compaction has no workspace identity; truncating in context instead",
            tool_name="search",
            user_id="set",
            conversation_id="missing",
        )

    async def test_missing_user_id_alone_truncates(self) -> None:
        # ``not user_id or not conversation_id`` — either half missing is enough;
        # with the conversation present the log must say "set" for it
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
            ) as mock_spill,
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ),
            patch("app.agents.middleware.compaction.log") as mock_log,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id=None,
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        mock_spill.assert_not_awaited()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Compaction has no workspace identity; truncating in context instead",
            tool_name="search",
            user_id="missing",
            conversation_id="set",
        )

    async def test_missing_existing_kwargs_default_to_empty_dict(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c7",
                user_id=None,
                conversation_id=None,
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
                existing_additional_kwargs=None,
            )

        assert result.truncated is True
        assert mock_truncate.call_args.kwargs["existing_additional_kwargs"] == {}

    async def test_missing_conversation_id_alone_still_truncates(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
            ) as mock_spill,
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ),
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id=None,
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        mock_spill.assert_not_awaited()

    async def test_spill_result_is_returned_directly(self) -> None:
        spilled = SimpleNamespace(spilled=True)
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
                return_value=spilled,
            ) as mock_spill,
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result is spilled
        mock_spill.assert_awaited_once()
        mock_truncate.assert_not_called()

    async def test_generic_spill_failure_triggers_fallback(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
                side_effect=OSError("disk exploded"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
            patch("app.agents.middleware.compaction.log") as mock_log,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        mock_truncate.assert_called_once()
        mock_log.error.assert_called_once_with(
            f"{LogTag.AGENT} Workspace spill failed, compacting in context instead",
            tool_name="search",
            error_type="OSError",
        )

    async def test_juicefs_unavailable_triggers_fallback(self) -> None:
        with (
            patch(
                "app.agents.middleware.compaction.should_compact_output",
                return_value=(True, "large_output"),
            ),
            patch(
                "app.agents.middleware.compaction._spill_to_workspace",
                new_callable=AsyncMock,
                side_effect=JuiceFSUnavailable("no mount"),
            ),
            patch(
                "app.agents.middleware.compaction._truncate_in_context",
                return_value=SimpleNamespace(truncated=True),
            ) as mock_truncate,
            patch("app.agents.middleware.compaction.log") as mock_log,
        ):
            result = await compact_tool_output(
                content="x" * 5000,
                tool_name="search",
                tool_call_id="c1",
                user_id="u1",
                conversation_id="conv1",
                context_usage=0.9,
                max_output_chars=10,
                compaction_threshold=0.65,
            )

        assert result.truncated is True
        mock_truncate.assert_called_once()
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Workspace unavailable, compacting in context",
            tool_name="search",
            error_type="JuiceFSUnavailable",
        )


class TestTruncateInContextDirect:
    def test_output_already_under_budget_returns_none(self) -> None:
        result = _truncate_in_context(
            content_str="small",
            tool_name="search",
            tool_call_id="c1",
            reason="large_output",
            status="success",
            existing_additional_kwargs={},
        )
        assert result is None

    def test_output_exactly_at_budget_returns_none(self) -> None:
        # ``dropped <= 0`` (not ``< 0``): nothing to reclaim at exactly the budget
        content_str = "H" * COMPACTION_FALLBACK_HEAD_CHARS + "T" * COMPACTION_FALLBACK_TAIL_CHARS
        result = _truncate_in_context(
            content_str=content_str,
            tool_name="search",
            tool_call_id="c1",
            reason="large_output",
            status="success",
            existing_additional_kwargs={},
        )
        assert result is None

    def test_output_one_char_over_budget_builds_body(self) -> None:
        # ``dropped <= 0`` (not ``<= 1``): even a single char is reclaimed
        content_str = "H" * COMPACTION_FALLBACK_HEAD_CHARS + "M" + "T" * COMPACTION_FALLBACK_TAIL_CHARS
        result = _truncate_in_context(
            content_str=content_str,
            tool_name="search",
            tool_call_id="c1",
            reason="large_output",
            status="success",
            existing_additional_kwargs={},
        )
        assert result is not None
        assert "[... 1 chars dropped ...]" in result.content

    async def test_truncate_pins_exact_body_and_kwargs(self) -> None:
        # 3000 chars of head + 17 of middle + 1000 of tail, so both slices and
        # the dropped count are independently observable.
        content_str = "H" * COMPACTION_FALLBACK_HEAD_CHARS + "M" * 17 + "T" * COMPACTION_FALLBACK_TAIL_CHARS
        expected = (
            f"{COMPACTION_TRUNCATED_MARKER} search returned {len(content_str)} chars "
            f"(large_output (4017 chars)). The workspace is unavailable, so the full output "
            f"could NOT be saved for later and the middle 17 chars are gone for good. "
            f"The first {COMPACTION_FALLBACK_HEAD_CHARS} and last {COMPACTION_FALLBACK_TAIL_CHARS} "
            "chars are below — if you need what was dropped, call the tool again with a "
            "narrower query rather than assuming this is the complete result.\n\n"
            f"{'H' * COMPACTION_FALLBACK_HEAD_CHARS}\n\n"
            f"[... 17 chars dropped ...]\n\n"
            f"{'T' * COMPACTION_FALLBACK_TAIL_CHARS}"
        )
        with patch("app.agents.middleware.compaction.log") as mock_log:
            result = _truncate_in_context(
                content_str=content_str,
                tool_name="search",
                tool_call_id="c3",
                reason="large_output (4017 chars)",
                status="error",
                existing_additional_kwargs={"orig": 1},
            )

        assert result is not None
        assert result.content == expected
        assert result.tool_call_id == "c3"
        assert result.name == "search"
        assert result.status == "error"
        assert result.additional_kwargs == {
            "orig": 1,
            "original_length": len(content_str),
            "compacted": True,
            "compaction_reason": "large_output (4017 chars)",
            "compaction_strategy": "in_context_truncation",
            "compaction_lossy": True,
        }
        mock_log.warning.assert_called_once_with(
            f"{LogTag.AGENT} Compacted tool output in context because the workspace was unavailable",
            tool_name="search",
            chars_before=len(content_str),
            chars_after=len(expected),
            dropped=17,
            lossy=True,
            reason="large_output (4017 chars)",
        )
