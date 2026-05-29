"""Tests for app.agents.middleware.vfs_summarization.

UNIT: VFSArchivingSummarizationMiddleware (extends LangChain SummarizationMiddleware
to archive full history to VFS before the parent summarizes, then inject the archive
path into the produced summary message).

BEHAVIOR SPEC
-------------
__init__:
  EXPECTED: forwards defaults trigger=("fraction", 0.85) and keep=("messages", 15)
            to the real parent; stores vfs_enabled (default True), excluded_tools
            (default empty set), and lazy _vfs=None.
  MUST-CATCH: real parent runs (mw.trigger / mw.keep carry the exact default tuples);
              vfs_enabled / excluded_tools overrides take effect.

_get_vfs:
  EXPECTED: lazy-load get_vfs() once, cache on self._vfs, return cached on reuse.
  MECHANISM: if self._vfs is None: self._vfs = await get_vfs(); return self._vfs.
  MUST-CATCH: get_vfs called exactly once across two calls; cached instance returned.

_should_trigger_summarization:
  EXPECTED: True iff, after dropping ToolMessages whose name is in excluded_tools,
            the remaining messages exceed the configured trigger threshold.
            fraction -> token_count > 128000*fraction (no _max_tokens attr in prod);
            tokens   -> token_count > value; messages -> len(filtered) > value.
            Empty / all-filtered / token_counter error -> False.
  MUST-CATCH: each branch boundary; the 128000 fraction divisor; the And in the
              excluded-tool filter (ToolMessage AND name-in-excluded); token-counter
              failure swallowed to False.

_archive_to_vfs:
  EXPECTED: validate user_id + conversation_id + written_by from runtime config,
            write a JSON archive at <session>/archives/pre_summary_<ts>.json with a
            metadata block, return the archive path. conversation_id prefers
            vfs_session_id over thread_id; written_by prefers subagent_id over
            metadata.agent_name. Missing any required field -> ValueError.
  MUST-CATCH: each ValueError branch; vfs_session_id wins over thread_id; the written
              content is the serialized history; the metadata keys/values are exact;
              the path template / filename prefix are exact.

_serialize_messages:
  EXPECTED: each message -> {"type", "content"} (+ "tool_calls" when present mapping
            id/name/args, + "tool_call_id"/"name" for ToolMessage).
  MUST-CATCH: the type/content keys and values; tool_calls arg passthrough;
              ToolMessage-only fields.

_inject_archive_path:
  EXPECTED: find first HumanMessage with additional_kwargs.is_summary, append
            "\n\n[Full history archived at: <path>]" to its content and set
            additional_kwargs["archive_path"]. No summary message / empty -> unchanged.
  MUST-CATCH: exact appended sentence; archive_path kwarg; no-op when no summary.

abefore_model:
  EXPECTED: when vfs_enabled and parent will summarize, archive first, run parent,
            then inject the archive path into the summary. vfs disabled -> no archive.
            Archive failure is swallowed (parent still runs). Inject only when BOTH
            parent returned a result AND an archive path exists.
  MUST-CATCH: the (result is not None) AND (archive_path) guard; archive-failure
              swallow; disabled path skips archiving.

EQUIVALENT MUTANTS (allowed survivors, justified): none expected.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.middleware.vfs_summarization import VFSArchivingSummarizationMiddleware

MODULE = "app.agents.middleware.vfs_summarization"

# Production divisor used when no `_max_tokens` attribute is present on the instance.
FRACTION_DIVISOR = 128000


def _make_middleware(**kwargs: Any) -> VFSArchivingSummarizationMiddleware:
    """Construct the middleware through the REAL parent __init__.

    The only thing mocked is the model itself (the LLM I/O boundary): a fake chat
    model carrying a profile so the parent accepts a ("fraction", ...) trigger without
    contacting any model registry or network. This wires the genuine trigger/keep
    defaults so they are observable behaviour, not test fixtures.
    """
    model = GenericFakeChatModel(
        messages=iter([]),
        profile={"max_input_tokens": FRACTION_DIVISOR},
    )
    return VFSArchivingSummarizationMiddleware(model=model, **kwargs)


def _make_runtime(
    user_id: str | None = "u1",
    thread_id: str | None = "t1",
    subagent_id: str | None = "executor",
    vfs_session_id: str | None = None,
    agent_name: str | None = "executor",
) -> SimpleNamespace:
    """Build a fake LangGraph runtime carrying the config the middleware reads."""
    metadata: dict[str, Any] = {}
    if agent_name is not None:
        metadata["agent_name"] = agent_name
    config = {
        "configurable": {
            "user_id": user_id,
            "thread_id": thread_id,
            "subagent_id": subagent_id,
            "vfs_session_id": vfs_session_id,
        },
        "metadata": metadata,
    }
    return SimpleNamespace(config=config)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_forwards_default_trigger_and_keep_to_parent(self) -> None:
        mw = _make_middleware()
        # Real parent stored the forwarded defaults verbatim.
        assert mw.trigger == ("fraction", 0.85)
        assert mw.keep == ("messages", 15)

    def test_default_flags(self) -> None:
        mw = _make_middleware()
        assert mw.vfs_enabled is True
        assert mw.excluded_tools == set()
        assert mw._vfs is None

    def test_custom_values(self) -> None:
        mw = _make_middleware(vfs_enabled=False, excluded_tools={"tool_a"})
        assert mw.vfs_enabled is False
        assert mw.excluded_tools == {"tool_a"}


# ---------------------------------------------------------------------------
# _get_vfs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetVFS:
    async def test_lazy_loads_once_and_caches(self) -> None:
        mw = _make_middleware()
        first = MagicMock(name="vfs")
        with patch(f"{MODULE}.get_vfs", new_callable=AsyncMock, return_value=first) as get_vfs:
            result_a = await mw._get_vfs()
            result_b = await mw._get_vfs()

        assert result_a is first
        assert result_b is first
        assert mw._vfs is first
        # Cached after the first call -> get_vfs is hit exactly once, not per-call.
        get_vfs.assert_awaited_once()

    async def test_returns_preexisting_cached_vfs_without_loading(self) -> None:
        mw = _make_middleware()
        cached = MagicMock(name="cached")
        mw._vfs = cached
        with patch(f"{MODULE}.get_vfs", new_callable=AsyncMock) as get_vfs:
            result = await mw._get_vfs()
        assert result is cached
        get_vfs.assert_not_awaited()


# ---------------------------------------------------------------------------
# _should_trigger_summarization
# ---------------------------------------------------------------------------


class TestShouldTriggerSummarization:
    def test_empty_messages_is_false(self) -> None:
        mw = _make_middleware()
        assert mw._should_trigger_summarization({"messages": []}) is False

    def test_missing_messages_key_is_false(self) -> None:
        mw = _make_middleware()
        assert mw._should_trigger_summarization({}) is False

    def test_fraction_uses_128000_divisor_just_below_threshold(self) -> None:
        # 128000 * 0.85 = 108800; equal is NOT greater -> no trigger.
        mw = _make_middleware(trigger=("fraction", 0.85))
        mw.token_counter = MagicMock(return_value=int(FRACTION_DIVISOR * 0.85))
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False

    def test_fraction_uses_128000_divisor_just_above_threshold(self) -> None:
        # 108801 > 108800 -> trigger. If the divisor were 128001, the threshold would
        # be 108850 and 108801 would NOT trigger, so this pins the 128000 constant.
        mw = _make_middleware(trigger=("fraction", 0.85))
        mw.token_counter = MagicMock(return_value=int(FRACTION_DIVISOR * 0.85) + 1)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is True

    def test_tokens_at_threshold_is_false(self) -> None:
        mw = _make_middleware(trigger=("tokens", 5000))
        mw.token_counter = MagicMock(return_value=5000)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False

    def test_tokens_above_threshold_is_true(self) -> None:
        mw = _make_middleware(trigger=("tokens", 5000))
        mw.token_counter = MagicMock(return_value=5001)
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is True

    def test_messages_at_threshold_is_false(self) -> None:
        mw = _make_middleware(trigger=("messages", 3))
        mw.token_counter = MagicMock(return_value=10)
        msgs = [HumanMessage(content=f"m{i}") for i in range(3)]
        assert mw._should_trigger_summarization({"messages": msgs}) is False

    def test_messages_above_threshold_is_true(self) -> None:
        mw = _make_middleware(trigger=("messages", 3))
        mw.token_counter = MagicMock(return_value=10)
        msgs = [HumanMessage(content=f"m{i}") for i in range(4)]
        assert mw._should_trigger_summarization({"messages": msgs}) is True

    def test_excluded_tool_messages_filtered_out_to_empty(self) -> None:
        # Both messages are ToolMessages named in excluded_tools -> filtered to empty
        # -> False even though count (2) > trigger (1).
        mw = _make_middleware(excluded_tools={"big_tool"}, trigger=("messages", 1))
        mw.token_counter = MagicMock(return_value=10)
        msgs = [
            ToolMessage(content="d", tool_call_id="c1", name="big_tool"),
            ToolMessage(content="d", tool_call_id="c2", name="big_tool"),
        ]
        assert mw._should_trigger_summarization({"messages": msgs}) is False

    def test_non_toolmessage_named_like_excluded_is_not_filtered(self) -> None:
        # The filter requires (ToolMessage AND name in excluded). A HumanMessage is not
        # a ToolMessage, so it survives the filter even though there are excluded tools.
        # If the AND were an OR, the HumanMessage would be dropped and the count would
        # fall to 0 -> False; with the real AND it stays at 2 -> True.
        mw = _make_middleware(excluded_tools={"big_tool"}, trigger=("messages", 1))
        mw.token_counter = MagicMock(return_value=10)
        msgs = [HumanMessage(content="a"), HumanMessage(content="b")]
        assert mw._should_trigger_summarization({"messages": msgs}) is True

    def test_excluded_check_uses_message_name_not_blanket_drop(self) -> None:
        # A ToolMessage whose name is NOT excluded must be retained. With OR-instead-of
        # -AND the predicate would drop every ToolMessage, emptying the list -> False.
        mw = _make_middleware(excluded_tools={"big_tool"}, trigger=("messages", 1))
        mw.token_counter = MagicMock(return_value=10)
        msgs = [
            ToolMessage(content="d", tool_call_id="c1", name="other"),
            ToolMessage(content="d", tool_call_id="c2", name="other"),
        ]
        assert mw._should_trigger_summarization({"messages": msgs}) is True

    def test_token_counter_failure_is_swallowed_to_false(self) -> None:
        mw = _make_middleware(trigger=("tokens", 1))
        mw.token_counter = MagicMock(side_effect=RuntimeError("counter down"))
        state = {"messages": [HumanMessage(content="hi")]}
        assert mw._should_trigger_summarization(state) is False


# ---------------------------------------------------------------------------
# _serialize_messages
# ---------------------------------------------------------------------------


class TestSerializeMessages:
    def test_serializes_type_and_content(self) -> None:
        mw = _make_middleware()
        result = mw._serialize_messages([HumanMessage(content="hello")])
        assert result == [{"type": "HumanMessage", "content": "hello"}]

    def test_serializes_tool_message_fields(self) -> None:
        mw = _make_middleware()
        result = mw._serialize_messages(
            [ToolMessage(content="result", tool_call_id="tc1", name="my_tool")]
        )
        assert result[0]["type"] == "ToolMessage"
        assert result[0]["content"] == "result"
        assert result[0]["tool_call_id"] == "tc1"
        assert result[0]["name"] == "my_tool"

    def test_serializes_tool_calls_payload(self) -> None:
        mw = _make_middleware()
        msg = AIMessage(
            content="calling",
            tool_calls=[
                {"id": "tc1", "name": "search", "args": {"q": "test"}, "type": "tool_call"}
            ],
        )
        result = mw._serialize_messages([msg])
        assert result[0]["tool_calls"] == [{"id": "tc1", "name": "search", "args": {"q": "test"}}]

    def test_plain_message_has_no_tool_fields(self) -> None:
        mw = _make_middleware()
        result = mw._serialize_messages([HumanMessage(content="plain")])
        assert "tool_calls" not in result[0]
        assert "tool_call_id" not in result[0]
        assert "name" not in result[0]


# ---------------------------------------------------------------------------
# _inject_archive_path
# ---------------------------------------------------------------------------


class TestInjectArchivePath:
    def test_injects_exact_sentence_and_kwarg(self) -> None:
        mw = _make_middleware()
        summary = HumanMessage(
            content="Summary of conversation",
            additional_kwargs={"is_summary": True},
        )
        result = mw._inject_archive_path({"messages": [summary]}, "/vfs/archive.json")
        injected = result["messages"][0]
        assert (
            injected.content
            == "Summary of conversation\n\n[Full history archived at: /vfs/archive.json]"
        )
        assert injected.additional_kwargs["archive_path"] == "/vfs/archive.json"

    def test_only_summary_message_is_touched(self) -> None:
        mw = _make_middleware()
        normal = HumanMessage(content="regular", additional_kwargs={})
        summary = HumanMessage(content="the summary", additional_kwargs={"is_summary": True})
        result = mw._inject_archive_path({"messages": [normal, summary]}, "/p.json")
        # Non-summary message untouched.
        assert result["messages"][0].content == "regular"
        assert "archive_path" not in result["messages"][0].additional_kwargs
        # Summary message updated.
        assert result["messages"][1].content.endswith("[Full history archived at: /p.json]")
        assert result["messages"][1].additional_kwargs["archive_path"] == "/p.json"

    def test_no_summary_message_is_unchanged(self) -> None:
        mw = _make_middleware()
        msg = HumanMessage(content="regular", additional_kwargs={})
        result = mw._inject_archive_path({"messages": [msg]}, "/vfs/archive.json")
        assert result["messages"][0].content == "regular"
        assert "archive_path" not in result["messages"][0].additional_kwargs

    def test_empty_messages_returns_unchanged(self) -> None:
        mw = _make_middleware()
        result = mw._inject_archive_path({"messages": []}, "/path")
        assert result == {"messages": []}

    def test_non_string_summary_content_skips_text_append_but_sets_kwarg(self) -> None:
        # A summary HumanMessage with list (non-str) content: the guard
        # `hasattr(content) AND isinstance(content, str)` is False, so the text append
        # is skipped (list content left intact) while archive_path is still recorded.
        # An And->Or mutation would attempt `list += str` and raise TypeError.
        mw = _make_middleware()
        summary = HumanMessage(
            content=[{"type": "text", "text": "block"}],
            additional_kwargs={"is_summary": True},
        )
        result = mw._inject_archive_path({"messages": [summary]}, "/vfs/a.json")
        injected = result["messages"][0]
        assert injected.content == [{"type": "text", "text": "block"}]
        assert injected.additional_kwargs["archive_path"] == "/vfs/a.json"


# ---------------------------------------------------------------------------
# _archive_to_vfs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestArchiveToVfs:
    async def test_writes_serialized_history_with_exact_path_and_metadata(self) -> None:
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime(user_id="u1", thread_id="t1", subagent_id="executor")
        messages = [HumanMessage(content="hello"), HumanMessage(content="world")]
        state = {"messages": messages}

        with patch(f"{MODULE}.get_session_path", return_value="/users/u1/sessions/t1") as sess:
            path = await mw._archive_to_vfs(state, runtime)

        sess.assert_called_once_with("u1", "t1")
        # Path template: <session>/archives/pre_summary_<timestamp>.json with a real,
        # non-empty YYYYmmdd_HHMMSS stamp (digits + one underscore).
        prefix = "/users/u1/sessions/t1/archives/pre_summary_"
        assert path.startswith(prefix)
        assert path.endswith(".json")
        timestamp = path[len(prefix) : -len(".json")]
        assert len(timestamp) == len("YYYYmmdd_HHMMSS")
        assert timestamp.replace("_", "").isdigit()

        mock_vfs.write.assert_awaited_once()
        kwargs = mock_vfs.write.call_args.kwargs
        assert kwargs["path"] == path
        assert kwargs["user_id"] == "u1"
        # Content is the serialized message history, not a placeholder, and is written
        # as a human-readable JSON document with 2-space indentation (each list element
        # opens at exactly two leading spaces).
        assert "\n  {" in kwargs["content"]
        assert "\n   {" not in kwargs["content"]
        written = json.loads(kwargs["content"])
        assert written == [
            {"type": "HumanMessage", "content": "hello"},
            {"type": "HumanMessage", "content": "world"},
        ]
        meta = kwargs["metadata"]
        assert meta["type"] == "pre_summarization_archive"
        assert meta["agent_name"] == "executor"
        assert meta["written_by"] == "executor"
        assert meta["agent_thread_id"] == "t1"
        assert meta["conversation_id"] == "t1"
        assert meta["vfs_session_id"] is None
        assert meta["message_count"] == 2
        assert meta["trigger_reason"] == "summarization_middleware"
        # archived_at is recorded as a non-empty ISO-8601 timestamp.
        assert "archived_at" in meta
        assert "T" in meta["archived_at"]

    async def test_prefers_vfs_session_id_over_thread_id(self) -> None:
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime(thread_id="thread_x", vfs_session_id="session_y")
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(f"{MODULE}.get_session_path", return_value="/p") as sess:
            await mw._archive_to_vfs(state, runtime)

        sess.assert_called_once_with("u1", "session_y")
        meta = mock_vfs.write.call_args.kwargs["metadata"]
        assert meta["conversation_id"] == "session_y"
        assert meta["vfs_session_id"] == "session_y"
        # thread_id still recorded separately.
        assert meta["agent_thread_id"] == "thread_x"

    async def test_prefers_subagent_id_over_metadata_agent_name_for_written_by(self) -> None:
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime(subagent_id="sub_agent_7", agent_name="meta_agent")
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(f"{MODULE}.get_session_path", return_value="/p"):
            await mw._archive_to_vfs(state, runtime)

        assert mock_vfs.write.call_args.kwargs["metadata"]["written_by"] == "sub_agent_7"

    async def test_falls_back_to_metadata_agent_name_when_no_subagent_id(self) -> None:
        mw = _make_middleware()
        mock_vfs = AsyncMock()
        mw._vfs = mock_vfs
        runtime = _make_runtime(subagent_id=None, agent_name="meta_agent")
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(f"{MODULE}.get_session_path", return_value="/p"):
            await mw._archive_to_vfs(state, runtime)

        assert mock_vfs.write.call_args.kwargs["metadata"]["written_by"] == "meta_agent"

    async def test_raises_without_user_id(self) -> None:
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(user_id=None)
        with pytest.raises(ValueError, match="user_id"):
            await mw._archive_to_vfs({"messages": []}, runtime)

    async def test_raises_without_conversation_id(self) -> None:
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(thread_id=None, vfs_session_id=None)
        with pytest.raises(ValueError, match="vfs_session_id"):
            await mw._archive_to_vfs({"messages": []}, runtime)

    async def test_raises_without_written_by(self) -> None:
        mw = _make_middleware()
        mw._vfs = AsyncMock()
        runtime = _make_runtime(subagent_id=None, agent_name=None)
        with pytest.raises(ValueError, match="subagent_id"):
            await mw._archive_to_vfs({"messages": []}, runtime)


# ---------------------------------------------------------------------------
# abefore_model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAbeforeModel:
    async def test_vfs_disabled_skips_archive_and_returns_parent_result(self) -> None:
        mw = _make_middleware(vfs_enabled=False)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock()
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            f"{MODULE}.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await mw.abefore_model(state, runtime)

        assert result is None
        mw._archive_to_vfs.assert_not_awaited()

    async def test_archives_then_injects_path_into_summary(self) -> None:
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock(return_value="/vfs/archive.json")

        summary = HumanMessage(content="Summary", additional_kwargs={"is_summary": True})
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            f"{MODULE}.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value={"messages": [summary]},
        ):
            result = await mw.abefore_model(state, runtime)

        assert result is not None
        mw._archive_to_vfs.assert_awaited_once()
        assert (
            result["messages"][0].content
            == "Summary\n\n[Full history archived at: /vfs/archive.json]"
        )
        assert result["messages"][0].additional_kwargs["archive_path"] == "/vfs/archive.json"

    async def test_archive_failure_is_swallowed_parent_still_runs(self) -> None:
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock(side_effect=RuntimeError("VFS down"))

        summary = HumanMessage(content="Summary", additional_kwargs={"is_summary": True})
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            f"{MODULE}.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value={"messages": [summary]},
        ) as parent:
            result = await mw.abefore_model(state, runtime)

        parent.assert_awaited_once()
        # Archive failed -> no archive_path -> summary left untouched.
        assert result["messages"][0].content == "Summary"
        assert "archive_path" not in result["messages"][0].additional_kwargs

    async def test_no_injection_when_summarization_not_triggered(self) -> None:
        # archive_path stays None (no trigger). Even though the parent returns an
        # injectable summary message, the (result is not None AND archive_path) guard
        # must short-circuit on the falsy archive_path -> no injection. An And->Or
        # mutation would inject the literal "None" path here.
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=False)
        mw._archive_to_vfs = AsyncMock()

        summary = HumanMessage(content="Summary", additional_kwargs={"is_summary": True})
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            f"{MODULE}.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value={"messages": [summary]},
        ):
            result = await mw.abefore_model(state, runtime)

        mw._archive_to_vfs.assert_not_awaited()
        assert result["messages"][0].content == "Summary"
        assert "archive_path" not in result["messages"][0].additional_kwargs

    async def test_no_injection_when_parent_returns_none(self) -> None:
        # Archive succeeded (path exists) but parent did NOT summarize (None). The
        # guard's (result is not None) arm must short-circuit -> None returned, no
        # AttributeError from trying to inject into None.
        mw = _make_middleware(vfs_enabled=True)
        mw._should_trigger_summarization = MagicMock(return_value=True)
        mw._archive_to_vfs = AsyncMock(return_value="/vfs/archive.json")
        runtime = _make_runtime()
        state = {"messages": [HumanMessage(content="hi")]}

        with patch(
            f"{MODULE}.SummarizationMiddleware.abefore_model",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await mw.abefore_model(state, runtime)

        assert result is None
        mw._archive_to_vfs.assert_awaited_once()
