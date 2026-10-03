"""Loop-guard middleware: repeat refusal, failure tallies and their escalation thresholds.

The guard is the only thing that stops a model burning a run re-issuing a call
whose result will not change. Every threshold here is asserted against the
shipped constants rather than a literal, so a constant change moves the tests
with it instead of silently making them lie.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any, cast

from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.types import Command
import pytest

from app.agents.middleware.loop_guard import LoopGuardMiddleware
from app.constants.agents import TOOL_RESULT_NOTE_SEPARATOR
from app.constants.llm import (
    COMPLETION_NUDGE_MESSAGE,
    LOOP_GUARD_STOP_REPEAT,
    LOOP_GUARD_STOPPED_KEY,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_REPEAT,
    LOOP_GUARD_WARN_SAME_TOOL,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import runtime_configurable
from shared.py.wide_events import log

_TASK = HumanMessage("do the task")
_PAUSE = AIMessage("Let me try that again.")


def _warnings(message: str) -> list[dict[str, Any]]:
    """Return the wide event's warnings whose message is the tagged message."""
    tagged = f"{LogTag.AGENT} {message}"
    return [w for w in log.get().get("warnings", []) if w.get("msg") == tagged]


def _runtime(config: Any) -> ToolRuntime:
    return ToolRuntime(
        state={}, context=None, config=config, stream_writer=None, tool_call_id=None, store=None
    )


def _turn(name: str = "search", args: dict[str, Any] | None = None, n: int = 0) -> AIMessage:
    """One model turn issuing a single call."""
    call_args = args if args is not None else {"q": "x"}
    return AIMessage(content="", tool_calls=[{"name": name, "args": call_args, "id": f"t{n}"}])


def _request(
    *,
    name: str = "search",
    args: dict[str, Any] | None = None,
    call_id: str = "call-1",
    turns: int = 1,
    messages: Sequence[AnyMessage] | None = None,
) -> ToolCallRequest:
    """Build a call on one shared thread whose last turns model turns, this one included, issued it."""
    call_args = args if args is not None else {"q": "x"}
    history = (
        list(messages)
        if messages is not None
        else [_TASK, *(_turn(name, call_args, n) for n in range(turns))]
    )
    return ToolCallRequest(
        tool_call={"name": name, "args": call_args, "id": call_id},
        tool=None,
        state={"messages": history},
        runtime=_runtime({"configurable": {"thread_id": "thread-1"}}),
    )


def _failing(content: str = "boom", *, name: str = "search", call_id: str = "call-1"):
    async def handler(_request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=call_id, name=name, status="error")

    return handler


def _succeeding(content: str = "ok", *, name: str = "search", call_id: str = "call-1"):
    async def handler(_request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=call_id, name=name)

    return handler


class _Counting:
    """A succeeding handler that records whether the tool body ran."""

    def __init__(self) -> None:
        self.executed = 0

    async def __call__(self, _request: ToolCallRequest) -> ToolMessage:
        self.executed += 1
        return ToolMessage(content="ok", tool_call_id="call-1", name="search")


async def _wrap(mw: LoopGuardMiddleware, request: ToolCallRequest, handler: Any) -> ToolMessage:
    """Drive one wrapped call and narrow the union to the ToolMessage branch."""
    result = await mw.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    return result


def _attempt(
    n: int, *, args: dict[str, Any] | None = None, failed: bool = True
) -> list[AnyMessage]:
    """One model turn issuing a search, and the result the tool node recorded for it."""
    result = ToolMessage(
        content="boom" if failed else "ok",
        tool_call_id=f"t{n}",
        name="search",
        status="error" if failed else "success",
    )
    return [_turn(args=args, n=n), result]


def _retries(count: int) -> list[AnyMessage]:
    """Count failed attempts of one search, a text turn after each so no repeat streak builds."""
    return [message for n in range(count) for message in (*_attempt(n), _PAUSE)]


def _distinct(count: int, *, failed: bool = True) -> list[AnyMessage]:
    """Count back-to-back attempts of search, each with its own arguments."""
    return [msg for n in range(count) for msg in _attempt(n, args={"q": str(n)}, failed=failed)]


def _after(*history: AnyMessage, args: dict[str, Any] | None = None) -> ToolCallRequest:
    """Build the search the model issues next, after history in the same delegation."""
    return _request(args=args, messages=[_TASK, *history, _turn(args=args, n=99)])


# --- warn escalation: identical arguments ------------------------------------ #


async def test_a_first_failure_is_left_untouched() -> None:
    result = await _wrap(LoopGuardMiddleware(), _after(), _failing())

    assert result.content == "boom"
    assert "loop_guard_warned" not in result.additional_kwargs


async def test_identical_failure_at_warn_threshold_appends_in_band_note() -> None:
    request = _after(*_retries(LOOP_GUARD_WARN_IDENTICAL - 1))
    result = await _wrap(LoopGuardMiddleware(), request, _failing())

    assert result.additional_kwargs["loop_guard_warned"] is True
    assert str(result.content).startswith("boom")  # the tool's own error text survives
    assert f"failed {LOOP_GUARD_WARN_IDENTICAL} times in a row" in result.content
    assert "`search`" in result.content


async def test_identical_note_reports_the_growing_streak_count() -> None:
    for failures in range(LOOP_GUARD_WARN_IDENTICAL, LOOP_GUARD_WARN_IDENTICAL + 3):
        request = _after(*_retries(failures - 1))
        result = await _wrap(LoopGuardMiddleware(), request, _failing())
        assert f"failed {failures} times in a row" in result.content


# --- warn escalation: same tool, different arguments ------------------------- #


async def test_same_tool_warn_fires_only_after_its_own_threshold() -> None:
    # Distinct args every call, so the identical streak never leaves 1 and only
    # the weaker same-tool signal can fire.
    history = _distinct(LOOP_GUARD_WARN_SAME_TOOL - 1)
    mw = LoopGuardMiddleware()

    below = await _wrap(mw, _after(*history[:-2], args={"q": "last"}), _failing())
    at = await _wrap(mw, _after(*history, args={"q": "last"}), _failing())

    assert "loop_guard_warned" not in below.additional_kwargs
    assert at.additional_kwargs["loop_guard_warned"] is True
    assert f"failed {LOOP_GUARD_WARN_SAME_TOOL} times this run" in at.content


async def test_identical_note_wins_over_same_tool_note() -> None:
    failures = max(LOOP_GUARD_WARN_IDENTICAL, LOOP_GUARD_WARN_SAME_TOOL)
    result = await _wrap(LoopGuardMiddleware(), _after(*_retries(failures - 1)), _failing())

    assert "times in a row" in result.content
    assert "reconsider your strategy" not in result.content


async def test_failures_of_another_tool_never_count() -> None:
    other: list[AnyMessage] = []
    for n in range(LOOP_GUARD_WARN_SAME_TOOL):
        failure = ToolMessage(content="boom", tool_call_id=f"t{n}", name="other", status="error")
        other += [_turn(name="other", n=n), failure, _PAUSE]

    result = await _wrap(LoopGuardMiddleware(), _after(*other), _failing())

    assert "loop_guard_warned" not in result.additional_kwargs


# --- what resets the failure streak ------------------------------------------ #


async def test_success_breaks_the_consecutive_identical_streak() -> None:
    history = [*_retries(LOOP_GUARD_WARN_IDENTICAL - 1), *_attempt(50, failed=False), _PAUSE]
    result = await _wrap(LoopGuardMiddleware(), _after(*history), _failing())

    # Without the reset this would be the threshold-th consecutive failure.
    assert "loop_guard_warned" not in result.additional_kwargs


async def test_a_different_failing_call_breaks_the_streak() -> None:
    history = [*_retries(LOOP_GUARD_WARN_IDENTICAL - 1), *_attempt(50, args={"q": "other"})]
    result = await _wrap(LoopGuardMiddleware(), _after(*history), _failing())

    # The identical streak restarted; only the weaker same-tool signal can speak.
    assert "times in a row" not in str(result.content)


async def test_success_does_not_clear_the_same_tool_tally() -> None:
    history = [
        *_distinct(LOOP_GUARD_WARN_SAME_TOOL - 1),
        *_attempt(50, args={"q": "fine"}, failed=False),
    ]
    result = await _wrap(LoopGuardMiddleware(), _after(*history, args={"q": "last"}), _failing())

    assert f"failed {LOOP_GUARD_WARN_SAME_TOOL} times this run" in result.content


async def test_a_success_midway_resets_the_identical_run_without_ending_the_tally() -> None:
    """The success clears the identical streak; the failures after it are still this run's."""
    history = [
        *_attempt(0, args={"q": "a"}),
        *_attempt(1, args={"q": "fine"}, failed=False),
        *_attempt(2, args={"q": "b"}),
        *_attempt(3, args={"q": "c"}),
    ]
    result = await _wrap(LoopGuardMiddleware(), _after(*history, args={"q": "d"}), _failing())

    assert f"failed {LOOP_GUARD_WARN_SAME_TOOL + 1} times this run" in result.content


async def test_a_result_this_delegation_never_issued_is_skipped_not_fatal() -> None:
    """A ToolMessage whose call predates the delegation is skipped, not fatal.

    It is not one of this run's failures, and the failures after it still are.
    """
    orphan = ToolMessage(content="boom", tool_call_id="t-elsewhere", name="search", status="error")
    history = [orphan, *_retries(LOOP_GUARD_WARN_IDENTICAL - 1)]
    result = await _wrap(LoopGuardMiddleware(), _after(*history), _failing())

    assert f"failed {LOOP_GUARD_WARN_IDENTICAL} times in a row" in result.content


async def test_successes_never_count_as_failures() -> None:
    history = _distinct(LOOP_GUARD_WARN_SAME_TOOL, failed=False)
    result = await _wrap(LoopGuardMiddleware(), _after(*history, args={"q": "last"}), _failing())

    assert "loop_guard_warned" not in result.additional_kwargs


async def test_a_refusal_neither_counts_nor_breaks_the_streak() -> None:
    refusal = ToolMessage(
        content="refused",
        tool_call_id="t50",
        name="search",
        status="error",
        additional_kwargs={LOOP_GUARD_STOPPED_KEY: True},
    )
    history = [*_retries(LOOP_GUARD_WARN_IDENTICAL - 1), _turn(n=50), refusal, _PAUSE]
    result = await _wrap(LoopGuardMiddleware(), _after(*history), _failing())

    assert f"failed {LOOP_GUARD_WARN_IDENTICAL} times in a row" in result.content


async def test_successful_result_is_returned_unmodified() -> None:
    request = _after(*_retries(LOOP_GUARD_WARN_IDENTICAL), args={"q": "different"})
    result = await _wrap(LoopGuardMiddleware(), request, _succeeding())

    assert result.content == "ok"
    assert result.additional_kwargs == {}


async def test_non_tool_message_result_passes_through_untouched() -> None:
    command: Command[Any] = Command(update={"messages": []})

    async def handler(_request: ToolCallRequest) -> Command[Any]:
        return command

    request = _after(*_retries(LOOP_GUARD_WARN_IDENTICAL))
    assert await LoopGuardMiddleware().awrap_tool_call(request, handler) is command


async def test_a_failing_tool_is_never_blocked_on_its_failures() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="boom", tool_call_id="call-1", name="search", status="error")

    history = _distinct(LOOP_GUARD_WARN_SAME_TOOL * 3)
    result = await _wrap(LoopGuardMiddleware(), _after(*history, args={"q": "last"}), handler)

    assert executed == 1
    assert LOOP_GUARD_STOPPED_KEY not in result.additional_kwargs


# --- the failure tallies are scoped to the current delegation ----------------- #


async def test_failures_from_an_earlier_turn_on_the_thread_never_count() -> None:
    """A comms thread spans user turns; last turn's failures are not this run's."""
    mw = LoopGuardMiddleware()
    earlier: list[AnyMessage] = [_TASK]
    for n in range(LOOP_GUARD_WARN_SAME_TOOL - 1):
        request = _request(args={"q": str(n)}, messages=[*earlier, _turn(args={"q": str(n)}, n=n)])
        await _wrap(mw, request, _failing())
        earlier += _attempt(n, args={"q": str(n)})

    later = [*earlier, AIMessage("Search is down."), HumanMessage("try once more"), _turn(n=99)]
    result = await _wrap(mw, _request(messages=later), _failing())

    assert result.content == "boom"
    assert "loop_guard_warned" not in result.additional_kwargs


async def test_an_identical_failure_from_an_earlier_delegation_never_counts() -> None:
    earlier = [_TASK, *_retries(LOOP_GUARD_WARN_IDENTICAL)]
    request = _request(messages=[*earlier, HumanMessage("check again"), _turn(n=99)])

    result = await _wrap(LoopGuardMiddleware(), request, _failing())

    assert "loop_guard_warned" not in result.additional_kwargs


# --- argument keying ----------------------------------------------------------- #


def test_argument_key_ignores_key_ordering() -> None:
    key = LoopGuardMiddleware._args_key
    assert key({"a": 1, "b": 2}) == key({"b": 2, "a": 1})


def test_argument_key_separates_different_arguments() -> None:
    key = LoopGuardMiddleware._args_key
    assert key({"q": "a"}) != key({"q": "b"})


def test_argument_key_survives_unserializable_arguments() -> None:
    circular: dict[str, Any] = {}
    circular["self"] = circular  # json.dumps raises ValueError on this
    assert LoopGuardMiddleware._args_key(circular)


async def test_differently_ordered_arguments_extend_the_same_streak() -> None:
    history = [*_attempt(0, args={"a": 1, "b": 2}), _PAUSE]
    request = _after(*history, args={"b": 2, "a": 1})
    result = await _wrap(LoopGuardMiddleware(), request, _failing())

    # Same call semantically, so it must count as a repeat rather than resetting.
    assert f"failed {LOOP_GUARD_WARN_IDENTICAL} times in a row" in result.content


# --- note appending against the possible content shapes ----------------------- #


def test_note_is_appended_to_string_content() -> None:
    message = ToolMessage(content="original", tool_call_id="1", name="t", status="error")
    LoopGuardMiddleware._append_note(message, "NOTE")
    assert message.content == "originalNOTE"
    assert message.additional_kwargs["loop_guard_warned"] is True


def test_note_becomes_an_extra_block_for_list_content() -> None:
    blocks: list[str | dict[Any, Any]] = [{"type": "text", "text": "original"}]
    message = ToolMessage(content=blocks, tool_call_id="1", name="t", status="error")
    LoopGuardMiddleware._append_note(message, "NOTE")
    assert message.content == [{"type": "text", "text": "original"}, "NOTE"]


def test_note_appending_preserves_existing_additional_kwargs() -> None:
    message = ToolMessage(
        content="original",
        tool_call_id="1",
        name="t",
        status="error",
        additional_kwargs={"keep": "me"},
    )
    LoopGuardMiddleware._append_note(message, "NOTE")
    assert message.additional_kwargs == {"keep": "me", "loop_guard_warned": True}


def test_note_appending_stringifies_unexpected_content() -> None:
    message = ToolMessage(content="original", tool_call_id="1", name="t", status="error")
    object.__setattr__(message, "content", 42)  # neither str nor list
    LoopGuardMiddleware._append_note(message, "NOTE")
    assert message.content == "42NOTE"


# --- threshold helpers, exercised directly ------------------------------------ #


def test_no_warning_note_below_both_limits() -> None:
    mw = LoopGuardMiddleware()
    assert (
        mw._warning_note("search", LOOP_GUARD_WARN_IDENTICAL - 1, LOOP_GUARD_WARN_SAME_TOOL - 1)
        is None
    )


# --- repeats: the same call on consecutive model turns, whatever the outcome --- #


async def test_a_repeated_successful_call_is_warned_on_its_warn_turn() -> None:
    mw = LoopGuardMiddleware()
    first = await _wrap(mw, _request(turns=LOOP_GUARD_WARN_REPEAT - 1), _succeeding())
    warned = await _wrap(mw, _request(turns=LOOP_GUARD_WARN_REPEAT), _succeeding())

    assert "[Loop guard:" not in first.content
    # The note rides after the separator the record reads through, so the
    # result stays a JSON document to everything that parses it.
    assert warned.content == (
        "ok"
        f"{TOOL_RESULT_NOTE_SEPARATOR}[Loop guard: `search` has now been called "
        f"{LOOP_GUARD_WARN_REPEAT} times in a row with identical arguments. The result won't "
        "change — reuse it and move on; an identical call made "
        f"{LOOP_GUARD_STOP_REPEAT} times in a row will not be run.]"
    )
    assert warned.additional_kwargs["loop_guard_warned"] is True


async def test_the_repeat_turn_is_refused_without_running() -> None:
    """Regression: warn-only runs re-ran one identical edit 28 times until the step limit."""
    handler = _Counting()

    refused = await _wrap(LoopGuardMiddleware(), _request(turns=LOOP_GUARD_STOP_REPEAT), handler)

    assert handler.executed == 0
    assert refused.status == "error"
    assert refused.additional_kwargs["loop_guard_stopped"] is True
    assert refused.tool_call_id == "call-1"
    assert refused.name == "search"  # the frontend keys the tool card off this
    assert refused.content == (
        "[Loop guard] This `search` call was not run: it repeats your last "
        f"{LOOP_GUARD_STOP_REPEAT - 1} calls with identical arguments, and its result will not "
        "change. Your next step must be a different action or your final answer."
    )


async def test_a_failing_call_is_refused_on_the_repeat_turn_too() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="boom", tool_call_id="call-1", name="search", status="error")

    mw = LoopGuardMiddleware()
    refused = await _wrap(mw, _request(turns=LOOP_GUARD_STOP_REPEAT), handler)

    assert executed == 0
    assert refused.additional_kwargs["loop_guard_stopped"] is True


async def test_the_turn_before_the_repeat_limit_still_runs() -> None:
    handler = _Counting()
    await _wrap(LoopGuardMiddleware(), _request(turns=LOOP_GUARD_STOP_REPEAT - 1), handler)
    assert handler.executed == 1


async def test_a_refusal_is_reported_with_the_tool_and_the_streak() -> None:
    # The wide event is the only trace a call was refused; without the tool name
    # and the streak an operator cannot tell which tool the guard is capping.
    log.reset()
    await _wrap(LoopGuardMiddleware(), _request(turns=LOOP_GUARD_STOP_REPEAT), _succeeding())

    refusals = _warnings("Loop guard refused a repeated call — not executed")
    assert len(refusals) == 1
    assert refusals[0]["tool_name"] == "search"
    assert refusals[0]["repeat"] == LOOP_GUARD_STOP_REPEAT


async def test_the_repeat_warning_is_reported_with_the_tool_and_the_streak() -> None:
    log.reset()
    await _wrap(LoopGuardMiddleware(), _request(turns=LOOP_GUARD_WARN_REPEAT), _succeeding())

    notes = _warnings("Loop guard repeat-warning appended for tool")
    assert len(notes) == 1
    assert notes[0]["tool_name"] == "search"
    assert notes[0]["repeat"] == LOOP_GUARD_WARN_REPEAT


async def test_earlier_turns_with_different_arguments_never_count() -> None:
    history = [_TASK, *(_turn(args={"q": str(n)}, n=n) for n in range(LOOP_GUARD_STOP_REPEAT))]
    handler = _Counting()

    result = await _wrap(LoopGuardMiddleware(), _request(messages=[*history, _turn(n=99)]), handler)

    assert handler.executed == 1
    assert "[Loop guard" not in result.content


async def test_a_different_turn_in_between_breaks_the_streak() -> None:
    other = _turn(name="other", n=50)
    history = [_TASK, *(_turn(n=n) for n in range(LOOP_GUARD_STOP_REPEAT)), other, _turn(n=99)]
    handler = _Counting()

    await _wrap(LoopGuardMiddleware(), _request(messages=history), handler)

    assert handler.executed == 1


async def test_a_plain_text_turn_breaks_the_streak() -> None:
    """A model that stopped, was nudged, and resumed is not re-issuing on autopilot."""
    stop = AIMessage(content="All done.")
    nudge = HumanMessage(COMPLETION_NUDGE_MESSAGE)
    history = [_TASK, *(_turn(n=n) for n in range(LOOP_GUARD_STOP_REPEAT)), stop, nudge]
    handler = _Counting()

    await _wrap(LoopGuardMiddleware(), _request(messages=[*history, _turn(n=99)]), handler)

    assert handler.executed == 1


async def test_the_same_call_twice_in_one_turn_is_one_turn() -> None:
    """Parallel identical calls are one decision, not a loop across turns."""
    doubled = AIMessage(
        content="",
        tool_calls=[
            {"name": "search", "args": {"q": "x"}, "id": "a"},
            {"name": "search", "args": {"q": "x"}, "id": "b"},
        ],
    )
    handler = _Counting()

    result = await _wrap(LoopGuardMiddleware(), _request(messages=[_TASK, doubled]), handler)

    assert handler.executed == 1
    assert "[Loop guard" not in result.content


async def test_a_new_delegation_on_the_same_thread_starts_clean() -> None:
    """The executor thread spans delegations; a fresh request for the same read must run."""
    earlier = [_TASK, *(_turn(n=n) for n in range(LOOP_GUARD_STOP_REPEAT))]
    handler = _Counting()

    result = await _wrap(
        LoopGuardMiddleware(),
        _request(messages=[*earlier, HumanMessage("check again"), _turn(n=99)]),
        handler,
    )

    assert handler.executed == 1
    assert "[Loop guard" not in result.content


async def test_a_resume_clock_message_does_not_reset_the_streak() -> None:
    clock = HumanMessage("now", additional_kwargs={"time_context": True})
    history = [_TASK, *(_turn(n=n) for n in range(LOOP_GUARD_STOP_REPEAT - 1)), clock]
    handler = _Counting()

    await _wrap(LoopGuardMiddleware(), _request(messages=[*history, _turn(n=99)]), handler)

    assert handler.executed == 0


async def test_differently_ordered_arguments_on_earlier_turns_still_count() -> None:
    reordered = [_turn(args={"b": 2, "a": 1}, n=n) for n in range(LOOP_GUARD_STOP_REPEAT - 1)]
    current = _turn(args={"a": 1, "b": 2}, n=99)
    handler = _Counting()

    await _wrap(
        LoopGuardMiddleware(),
        _request(args={"a": 1, "b": 2}, messages=[_TASK, *reordered, current]),
        handler,
    )

    assert handler.executed == 0


async def test_the_attribute_style_tool_call_is_read_correctly() -> None:
    tool_call = SimpleNamespace(name="objtool", id="obj-1", args={"k": "v"})
    history = [_TASK, *(_turn("objtool", {"k": "v"}, n) for n in range(LOOP_GUARD_STOP_REPEAT))]
    request = ToolCallRequest(
        tool_call=cast(Any, tool_call),
        tool=None,
        state={"messages": history},
        runtime=_runtime({"configurable": {"thread_id": "t"}}),
    )

    refused = await _wrap(LoopGuardMiddleware(), request, _succeeding(name="objtool"))

    assert refused.additional_kwargs["loop_guard_stopped"] is True
    assert refused.tool_call_id == "obj-1"
    assert "`objtool`" in refused.content


async def test_a_state_that_is_not_the_graph_dict_fails_loudly() -> None:
    request = ToolCallRequest(
        tool_call={"name": "search", "args": {}, "id": "call-1"},
        tool=None,
        state=[_TASK],
        runtime=_runtime({"configurable": {}}),
    )

    with pytest.raises(TypeError, match="graph state dict") as caught:
        await LoopGuardMiddleware().awrap_tool_call(request, _succeeding())

    # The message names the type it actually got: "NoneType" would send an operator
    # looking for a missing state instead of the list the framework really passed.
    assert "got list" in str(caught.value)
