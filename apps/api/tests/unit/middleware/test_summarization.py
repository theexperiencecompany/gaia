"""Workspace-archiving summarization middleware.

The archive is the only way a summarized conversation's detail is recoverable,
so the gate that decides whether to write it must agree with the gate that
decides to summarize — every mismatch is history destroyed with no way back.
These tests assert that agreement directly against the parent's own decision
rather than against a re-derived threshold.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
import pytest

from app.agents.middleware import summarization as summarization_module
from app.agents.middleware.summarization import WorkspaceArchivingSummarizationMiddleware
from app.services.storage import JuiceFSUnavailable
from shared.py.wide_events import log

pytestmark = pytest.mark.unit


MAX_INPUT_TOKENS = 1000


@pytest.fixture(autouse=True)
def _no_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the fake summarization model from shipping traces to LangSmith.

    The dev secret bundle turns tracing on globally, and these tests invoke the
    model for real — without this a unit run makes outbound network calls.
    """
    for var in ("LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"):
        monkeypatch.delenv(var, raising=False)


def _model(replies: int = 20) -> GenericFakeChatModel:
    return GenericFakeChatModel(
        messages=iter([AIMessage(content="SUMMARY") for _ in range(replies)]),
        profile={"max_input_tokens": MAX_INPUT_TOKENS},
    )


def _one_token_per_message(messages: Any) -> int:
    return len(list(messages))


def _middleware(**kwargs: Any) -> WorkspaceArchivingSummarizationMiddleware:
    kwargs.setdefault("model", _model())
    kwargs.setdefault("trigger", ("tokens", 100))
    kwargs.setdefault("keep", ("messages", 2))
    kwargs.setdefault("token_counter", _one_token_per_message)
    return WorkspaceArchivingSummarizationMiddleware(**kwargs)


def _humans(count: int) -> list[AnyMessage]:
    return [HumanMessage(content=f"m{i}") for i in range(count)]


def _graph_config(**configurable: Any) -> AbstractContextManager[None]:
    """Stand in for LangGraph's runnable context var, which `get_config()` reads.

    The `runtime` object a middleware hook receives deliberately carries no
    config, so this — not the runtime — is where the archive's user and
    conversation come from.
    """
    return patch.object(summarization_module, "get_config", lambda: {"configurable": configurable})


def _runtime() -> Runtime[Any]:
    """The real object LangGraph passes to a middleware hook."""
    return Runtime(context=None)


def _gates_agree(
    mw: WorkspaceArchivingSummarizationMiddleware, messages: list[AnyMessage]
) -> tuple[bool, bool]:
    """Return (archive gate, the parent's own summarization decision)."""
    archive = mw._should_trigger_summarization({"messages": messages})
    summarize = mw._should_summarize(messages, mw.token_counter(messages))
    return archive, summarize


# --- the archive gate tracks the summarization gate exactly ------------------- #


@pytest.mark.parametrize("count", [99, 100, 101])
def test_token_trigger_boundary_agrees_with_the_parent(count: int) -> None:
    mw = _middleware(trigger=("tokens", 100))
    archive, summarize = _gates_agree(mw, _humans(count))
    assert archive is summarize


@pytest.mark.parametrize("count", [9, 10, 11])
def test_message_trigger_boundary_agrees_with_the_parent(count: int) -> None:
    mw = _middleware(trigger=("messages", 10))
    archive, summarize = _gates_agree(mw, _humans(count))
    assert archive is summarize


@pytest.mark.parametrize("count", [499, 500, 501])
def test_fraction_trigger_boundary_agrees_with_the_parent(count: int) -> None:
    mw = _middleware(trigger=("fraction", 0.5))  # 0.5 * 1000 == 500 tokens
    archive, summarize = _gates_agree(mw, _humans(count))
    assert archive is summarize


def test_the_archive_fires_exactly_at_the_threshold_not_one_past_it() -> None:
    # Regression: a strict `>` here meant the run that summarized at exactly the
    # threshold wrote no archive at all.
    mw = _middleware(trigger=("tokens", 100))
    assert mw._should_trigger_summarization({"messages": _humans(100)}) is True
    assert mw._should_trigger_summarization({"messages": _humans(99)}) is False


def test_a_list_of_triggers_is_honoured() -> None:
    mw = _middleware(trigger=[("tokens", 5000), ("messages", 10)])
    archive, summarize = _gates_agree(mw, _humans(12))
    assert (archive, summarize) == (True, True)


def test_a_conjunctive_trigger_clause_is_honoured() -> None:
    mw = _middleware(trigger={"tokens": 10, "messages": 5})
    assert _gates_agree(mw, _humans(12)) == (True, True)
    assert _gates_agree(mw, _humans(4)) == (False, False)


def test_provider_reported_tokens_trigger_the_archive_too() -> None:
    # The approximate counter says 2 tokens; the provider says the context is
    # already 1000. The parent summarizes on the reported figure, so the archive
    # must be written on it as well.
    mw = _middleware(trigger=("tokens", 100))
    reported = AIMessage(
        content="hi",
        usage_metadata={"input_tokens": 900, "output_tokens": 100, "total_tokens": 1000},
        response_metadata={"model_provider": mw.model._get_ls_params().get("ls_provider")},
    )
    messages: list[AnyMessage] = [HumanMessage(content="x"), reported]
    assert _gates_agree(mw, messages) == (True, True)


def test_an_empty_history_never_triggers_an_archive() -> None:
    assert _middleware()._should_trigger_summarization({"messages": []}) is False
    assert _middleware()._should_trigger_summarization({}) is False


def test_a_failing_token_counter_surfaces_instead_of_silently_skipping() -> None:
    def broken(_messages: Any) -> int:
        raise RuntimeError("token counter unavailable")

    mw = _middleware(token_counter=broken)
    with pytest.raises(RuntimeError, match="token counter unavailable"):
        mw._should_trigger_summarization({"messages": _humans(5)})


# --- excluded tools ----------------------------------------------------------- #


def test_excluded_tool_output_does_not_push_the_archive_gate_over() -> None:
    # 3 real messages + 10 excluded tool results. Counting everything would clear
    # a threshold of 5; counting only what is not excluded must not.
    mw = _middleware(trigger=("messages", 5), excluded_tools={"noisy"})
    mixed: list[AnyMessage] = [
        *_humans(3),
        *[ToolMessage(content="x", tool_call_id=str(i), name="noisy") for i in range(10)],
    ]
    assert mw._should_trigger_summarization({"messages": mixed}) is False


def test_a_history_of_nothing_but_excluded_output_never_triggers() -> None:
    mw = _middleware(trigger=("messages", 5), excluded_tools={"noisy"})
    noisy: list[AnyMessage] = [
        ToolMessage(content="x", tool_call_id=str(i), name="noisy") for i in range(10)
    ]
    assert mw._should_trigger_summarization({"messages": noisy}) is False


def test_other_tool_output_still_counts_towards_the_archive_gate() -> None:
    mw = _middleware(trigger=("messages", 5), excluded_tools={"noisy"})
    quiet: list[AnyMessage] = [
        ToolMessage(content="x", tool_call_id=str(i), name="quiet") for i in range(10)
    ]
    assert mw._should_trigger_summarization({"messages": quiet}) is True


def test_no_exclusions_are_configured_by_default() -> None:
    assert _middleware().excluded_tools == set()


# --- _archive ----------------------------------------------------------------- #


async def test_archive_writes_the_history_and_returns_the_sandbox_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_write(
        *, user_id: str, conversation_id: str, relative_path: str, content: str
    ) -> tuple[str, str]:
        captured.update(
            user_id=user_id,
            conversation_id=conversation_id,
            relative_path=relative_path,
            content=content,
        )
        return "/mnt/jfs/x", f"/workspace/sessions/{conversation_id}/{relative_path}"

    monkeypatch.setattr(summarization_module, "write_session_file", fake_write)
    mw = _middleware()
    with _graph_config(user_id="u1", thread_id="c1"):
        path = await mw._archive({"messages": _humans(3)})

    assert captured["user_id"] == "u1"
    assert captured["conversation_id"] == "c1"
    assert captured["relative_path"].startswith("archives/pre_summary_")
    assert captured["relative_path"].endswith(".json")
    assert path == f"/workspace/sessions/c1/{captured['relative_path']}"
    assert [entry["content"] for entry in json.loads(captured["content"])] == ["m0", "m1", "m2"]


async def test_archive_prefers_the_vfs_session_over_the_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_write(**kwargs: Any) -> tuple[str, str]:
        captured.update(kwargs)
        return "/mnt/jfs/x", "/workspace/x"

    monkeypatch.setattr(summarization_module, "write_session_file", fake_write)
    with _graph_config(user_id="u1", thread_id="executor_c1", vfs_session_id="c1"):
        await _middleware()._archive({"messages": _humans(1)})
    assert captured["conversation_id"] == "c1"


async def test_archive_refuses_to_run_without_a_user() -> None:
    with _graph_config(thread_id="c1"), pytest.raises(ValueError, match="user_id"):
        await _middleware()._archive({"messages": _humans(1)})


async def test_archive_refuses_to_run_without_a_conversation() -> None:
    with _graph_config(user_id="u1"), pytest.raises(ValueError, match="vfs_session_id"):
        await _middleware()._archive({"messages": _humans(1)})


async def test_archive_refuses_to_run_on_an_empty_configurable() -> None:
    with _graph_config(), pytest.raises(ValueError, match="user_id"):
        await _middleware()._archive({"messages": _humans(1)})


async def test_the_archive_does_not_read_its_config_off_the_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: this used to read `runtime.config`, which LangGraph's Runtime
    # deliberately does not have. Every real run therefore raised "requires
    # 'user_id'" into the caller's except handler and no history was ever
    # archived. Passing the real, config-less Runtime must still archive.
    captured: dict[str, Any] = {}

    async def fake_write(**kwargs: Any) -> tuple[str, str]:
        captured.update(kwargs)
        return "/mnt/jfs/x", "/workspace/sessions/c1/archives/a.json"

    monkeypatch.setattr(summarization_module, "write_session_file", fake_write)
    assert not hasattr(_runtime(), "config")

    mw = _middleware(trigger=("messages", 4), keep=("messages", 2))
    with _graph_config(user_id="u1", thread_id="c1"):
        result = await mw.abefore_model({"messages": _humans(10)}, _runtime())

    assert captured["user_id"] == "u1"
    assert result is not None
    summary = next(
        m
        for m in result["messages"]
        if getattr(m, "additional_kwargs", {}).get("lc_source") == "summarization"
    )
    assert "/workspace/sessions/c1/archives/a.json" in summary.content


# --- _serialize_messages ------------------------------------------------------ #


def test_serialization_records_type_and_text_for_each_message() -> None:
    entries = _middleware()._serialize_messages([HumanMessage(content="hello")])
    assert entries == [{"type": "HumanMessage", "content": "hello"}]


def test_serialization_keeps_tool_calls_with_their_arguments() -> None:
    message = AIMessage(content="", tool_calls=[{"id": "t1", "name": "search", "args": {"q": "z"}}])
    entry = _middleware()._serialize_messages([message])[0]
    assert entry["tool_calls"] == [{"id": "t1", "name": "search", "args": {"q": "z"}}]


def test_serialization_links_tool_results_back_to_their_call() -> None:
    message = ToolMessage(content="result", tool_call_id="t1", name="search")
    entry = _middleware()._serialize_messages([message])[0]
    assert entry["tool_call_id"] == "t1"
    assert entry["name"] == "search"


def test_serialization_strips_inline_media_to_text() -> None:
    # A single inline image would otherwise add ~1.4MB of base64 to the archive.
    message = HumanMessage(
        content=[
            {"type": "text", "text": "look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAABBBB"}},
        ]
    )
    entry = _middleware()._serialize_messages([message])[0]
    assert "AAAABBBB" not in json.dumps(entry)
    assert "look at this" in entry["content"]


def test_serialization_omits_tool_call_keys_for_plain_messages() -> None:
    entry = _middleware()._serialize_messages([AIMessage(content="plain")])[0]
    assert "tool_calls" not in entry
    assert "tool_call_id" not in entry


def test_serialization_falls_back_to_str_for_a_contentless_object() -> None:
    entry = _middleware()._serialize_messages(cast(Any, [SimpleNamespace()]))[0]
    assert entry["type"] == "SimpleNamespace"
    assert entry["content"] == "namespace()"


# --- _inject_archive_path ----------------------------------------------------- #


def test_the_archive_path_is_appended_to_the_summary_message() -> None:
    summary = HumanMessage(
        content="Here is a summary", additional_kwargs={"lc_source": "summarization"}
    )
    _middleware()._inject_archive_path({"messages": [summary]}, "/workspace/a.json")

    assert summary.content.startswith("Here is a summary")
    assert "/workspace/a.json" in summary.content
    assert "`read` tool" in summary.content
    assert summary.additional_kwargs["archive_path"] == "/workspace/a.json"


def test_preserved_user_messages_are_left_alone() -> None:
    preserved = HumanMessage(content="my actual question")
    summary = HumanMessage(content="summary", additional_kwargs={"lc_source": "summarization"})
    _middleware()._inject_archive_path({"messages": [preserved, summary]}, "/workspace/a.json")

    assert preserved.content == "my actual question"
    assert preserved.additional_kwargs == {}
    assert "/workspace/a.json" in summary.content


def test_only_the_newest_summary_is_annotated() -> None:
    newest = HumanMessage(content="new", additional_kwargs={"lc_source": "summarization"})
    older = HumanMessage(content="old", additional_kwargs={"lc_source": "summarization"})
    _middleware()._inject_archive_path({"messages": [newest, older]}, "/workspace/a.json")

    assert "/workspace/a.json" in newest.content
    assert older.content == "old"


def test_only_a_human_summary_message_is_annotated() -> None:
    # The summary the parent builds is always a HumanMessage. Another message
    # carrying the same marker must not swallow the annotation.
    impostor = AIMessage(
        content="not the summary", additional_kwargs={"lc_source": "summarization"}
    )
    summary = HumanMessage(content="summary", additional_kwargs={"lc_source": "summarization"})
    _middleware()._inject_archive_path({"messages": [impostor, summary]}, "/workspace/a.json")

    assert impostor.content == "not the summary"
    assert "archive_path" not in impostor.additional_kwargs
    assert "/workspace/a.json" in summary.content


def test_injection_is_a_no_op_without_a_summary_message() -> None:
    plain = HumanMessage(content="untouched")
    _middleware()._inject_archive_path({"messages": [plain]}, "/workspace/a.json")
    assert plain.content == "untouched"
    assert plain.additional_kwargs == {}


def test_injection_records_the_path_even_for_block_style_content() -> None:
    summary = HumanMessage(
        content=[{"type": "text", "text": "summary"}],
        additional_kwargs={"lc_source": "summarization"},
    )
    _middleware()._inject_archive_path({"messages": [summary]}, "/workspace/a.json")

    assert summary.content == [{"type": "text", "text": "summary"}]
    assert summary.additional_kwargs["archive_path"] == "/workspace/a.json"


def test_injection_tolerates_a_result_without_messages() -> None:
    _middleware()._inject_archive_path({}, "/workspace/a.json")


# --- abefore_model wiring ----------------------------------------------------- #


class _RecordingMiddleware(WorkspaceArchivingSummarizationMiddleware):
    """Records archive calls and stands in for the parent's summarization step."""

    def __init__(self, *, parent_result: dict[str, Any] | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._parent_result = parent_result
        self.archive_calls = 0

    async def _archive(self, state: Any) -> str:
        self.archive_calls += 1
        return "/workspace/sessions/c1/archives/pre_summary_x.json"

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        return "SUMMARY"


def _summary_result() -> dict[str, Any]:
    return {
        "messages": [
            HumanMessage(content="summary", additional_kwargs={"lc_source": "summarization"})
        ]
    }


async def test_history_is_archived_before_it_is_summarized() -> None:
    mw = _RecordingMiddleware(
        parent_result=_summary_result(),
        model=_model(),
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=_one_token_per_message,
    )
    result = await mw.abefore_model({"messages": _humans(10)}, _runtime())

    assert mw.archive_calls == 1
    assert result is not None
    summary = next(
        m
        for m in result["messages"]
        if isinstance(m, HumanMessage) and m.additional_kwargs.get("lc_source") == "summarization"
    )
    assert "archives/pre_summary_x.json" in summary.content


async def test_a_short_history_is_neither_archived_nor_summarized() -> None:
    mw = _RecordingMiddleware(
        parent_result=None,
        model=_model(),
        trigger=("messages", 50),
        keep=("messages", 2),
        token_counter=_one_token_per_message,
    )
    assert await mw.abefore_model({"messages": _humans(3)}, _runtime()) is None
    assert mw.archive_calls == 0


async def test_archiving_can_be_switched_off_without_disabling_summarization() -> None:
    mw = _RecordingMiddleware(
        parent_result=_summary_result(),
        model=_model(),
        trigger=("messages", 4),
        keep=("messages", 2),
        token_counter=_one_token_per_message,
        enable_archive=False,
    )
    result = await mw.abefore_model({"messages": _humans(10)}, _runtime())

    assert mw.archive_calls == 0
    assert result is not None  # summarization still happened
    summary = next(
        m for m in result["messages"] if getattr(m, "content", None) and "summary" in str(m.content)
    )
    assert "archives/" not in str(summary.content)


async def test_an_unavailable_workspace_downgrades_to_a_warning_and_still_summarizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log.reset()

    async def unavailable(**_kwargs: Any) -> tuple[str, str]:
        raise JuiceFSUnavailable("mount missing")

    monkeypatch.setattr(summarization_module, "write_session_file", unavailable)
    mw = _middleware(trigger=("messages", 4), keep=("messages", 2))
    with _graph_config(user_id="u1", thread_id="c1"):
        result = await mw.abefore_model({"messages": _humans(10)}, _runtime())

    assert result is not None
    assert any("Archive skipped" in w["msg"] for w in log.get()["warnings"])
    assert "errors" not in log.get()


async def test_an_unexpected_archive_failure_is_reported_as_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log.reset()

    async def broken(**_kwargs: Any) -> tuple[str, str]:
        raise OSError("disk full")

    monkeypatch.setattr(summarization_module, "write_session_file", broken)
    mw = _middleware(trigger=("messages", 4), keep=("messages", 2))
    with _graph_config(user_id="u1", thread_id="c1"):
        result = await mw.abefore_model({"messages": _humans(10)}, _runtime())

    assert result is not None  # summarization is never blocked by a failed archive
    assert any(
        e["msg"].endswith("Archive failed") and e.get("error_type") == "OSError"
        for e in log.get()["errors"]
    )


async def test_the_default_configuration_matches_the_documented_contract() -> None:
    mw = WorkspaceArchivingSummarizationMiddleware(model=_model())
    assert mw.trigger == ("fraction", 0.85)
    assert mw.keep == ("messages", 15)
    assert mw.enable_archive is True
