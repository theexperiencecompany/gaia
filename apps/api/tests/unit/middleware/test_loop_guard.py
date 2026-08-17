"""Loop-guard middleware: failure tallies, escalation thresholds, hard stop.

The guard is the only thing that stops a model burning a run retrying a tool
that will never succeed. Every threshold here is asserted against the shipped
constants rather than a literal, so a constant change moves the tests with it
instead of silently making them lie.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from langchain.agents.middleware.types import ToolCallRequest
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agents.middleware.loop_guard import _UNKNOWN_RUN, LoopGuardMiddleware, _RunCounters
from app.constants.llm import (
    LOOP_GUARD_STOP_IDENTICAL,
    LOOP_GUARD_STOP_REPEAT,
    LOOP_GUARD_STOP_SAME_TOOL,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_REPEAT,
    LOOP_GUARD_WARN_SAME_TOOL,
)
from app.constants.log_tags import LogTag
from shared.py.wide_events import log


def _warnings(message: str) -> list[dict[str, Any]]:
    """The wide event's warnings whose message is the tagged ``message``."""
    tagged = f"{LogTag.AGENT} {message}"
    return [w for w in log.get().get("warnings", []) if w.get("msg") == tagged]


def _runtime(config: Any) -> ToolRuntime:
    return ToolRuntime(
        state={}, context=None, config=config, stream_writer=None, tool_call_id=None, store=None
    )


def _request(
    *,
    name: str = "search",
    args: dict[str, Any] | None = None,
    call_id: str = "call-1",
    thread_id: str | None = "thread-1",
) -> ToolCallRequest:
    configurable = {"thread_id": thread_id} if thread_id is not None else {}
    return ToolCallRequest(
        tool_call={"name": name, "args": args if args is not None else {"q": "x"}, "id": call_id},
        tool=None,
        state={},
        runtime=_runtime({"configurable": configurable}),
    )


def _failing(content: str = "boom", *, name: str = "search", call_id: str = "call-1"):
    async def handler(_request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=call_id, name=name, status="error")

    return handler


def _succeeding(content: str = "ok", *, name: str = "search", call_id: str = "call-1"):
    async def handler(_request: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content=content, tool_call_id=call_id, name=name)

    return handler


async def _wrap(mw: LoopGuardMiddleware, request: ToolCallRequest, handler: Any) -> ToolMessage:
    """Drive one wrapped call and narrow the union to the ToolMessage branch."""
    result = await mw.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    return result


async def _run(mw: LoopGuardMiddleware, times: int, **kwargs: Any) -> list[ToolMessage]:
    """Drive `times` identical failing calls and return every result."""
    return [await _wrap(mw, _request(**kwargs), _failing()) for _ in range(times)]


# --- warn escalation: identical arguments ------------------------------------ #


async def test_first_failures_below_warn_threshold_are_left_untouched() -> None:
    mw = LoopGuardMiddleware()
    results = await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1)
    for result in results:
        assert result.content == "boom"
        assert "loop_guard_warned" not in result.additional_kwargs


async def test_identical_failure_at_warn_threshold_appends_in_band_note() -> None:
    mw = LoopGuardMiddleware()
    result = (await _run(mw, LOOP_GUARD_WARN_IDENTICAL))[-1]

    assert result.additional_kwargs["loop_guard_warned"] is True
    assert str(result.content).startswith("boom")  # the tool's own error text survives
    assert f"failed {LOOP_GUARD_WARN_IDENTICAL} times in a row" in result.content
    assert "`search`" in result.content


async def test_identical_note_reports_the_growing_streak_count() -> None:
    mw = LoopGuardMiddleware()
    results = await _run(mw, LOOP_GUARD_WARN_IDENTICAL + 2)
    for offset, result in enumerate(results[LOOP_GUARD_WARN_IDENTICAL - 1 :]):
        assert f"failed {LOOP_GUARD_WARN_IDENTICAL + offset} times in a row" in result.content


# --- warn escalation: same tool, different arguments ------------------------- #


async def test_same_tool_warn_fires_only_after_its_own_threshold() -> None:
    # Distinct args every call, so the identical tally never leaves 1 and only
    # the weaker same-tool signal can fire.
    mw = LoopGuardMiddleware()
    results = [
        await _wrap(mw, _request(args={"q": str(i)}), _failing())
        for i in range(LOOP_GUARD_WARN_SAME_TOOL)
    ]

    for result in results[:-1]:
        assert "loop_guard_warned" not in result.additional_kwargs
    assert results[-1].additional_kwargs["loop_guard_warned"] is True
    assert f"failed {LOOP_GUARD_WARN_SAME_TOOL} times this run" in results[-1].content


async def test_identical_note_wins_over_same_tool_note() -> None:
    mw = LoopGuardMiddleware()
    result = (await _run(mw, max(LOOP_GUARD_WARN_IDENTICAL, LOOP_GUARD_WARN_SAME_TOOL)))[-1]
    assert "times in a row" in result.content
    assert "reconsider your strategy" not in result.content


# --- what resets the streak -------------------------------------------------- #


async def test_success_breaks_the_consecutive_identical_streak() -> None:
    mw = LoopGuardMiddleware()
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1)
    await _wrap(mw, _request(), _succeeding())
    result = await _wrap(mw, _request(), _failing())

    # Without the reset this would be the threshold-th consecutive failure.
    assert "loop_guard_warned" not in result.additional_kwargs


async def test_a_different_failing_call_breaks_the_streak() -> None:
    mw = LoopGuardMiddleware()
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1)
    await _wrap(mw, _request(args={"q": "other"}), _failing())
    result = await _wrap(mw, _request(), _failing())

    # The identical streak restarted; only the weaker same-tool signal can speak.
    assert "times in a row" not in str(result.content)


async def test_success_does_not_clear_the_same_tool_tally() -> None:
    mw = LoopGuardMiddleware()
    for i in range(LOOP_GUARD_WARN_SAME_TOOL - 1):
        await _wrap(mw, _request(args={"q": str(i)}), _failing())
    await _wrap(mw, _request(args={"q": "fine"}), _succeeding())
    result = await _wrap(mw, _request(args={"q": "last"}), _failing())

    assert f"failed {LOOP_GUARD_WARN_SAME_TOOL} times this run" in result.content


async def test_successful_result_is_returned_unmodified() -> None:
    mw = LoopGuardMiddleware()
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL)
    # Different arguments: a success that is ALSO the n-th identical call in a
    # row now carries the repeat note (see the repeat tests below), so this one
    # varies the args to isolate "a success is not decorated with a failure note".
    result = await _wrap(mw, _request(args={"q": "different"}), _succeeding())

    assert result.content == "ok"
    assert result.additional_kwargs == {}


async def test_non_tool_message_result_passes_through_and_clears_the_streak() -> None:
    mw = LoopGuardMiddleware()
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1)
    command: Command[Any] = Command(update={"messages": []})

    async def handler(_request: ToolCallRequest) -> Command[Any]:
        return command

    assert await mw.awrap_tool_call(_request(), handler) is command
    follow_up = await _wrap(mw, _request(), _failing())
    assert "loop_guard_warned" not in follow_up.additional_kwargs


async def test_a_successful_tool_message_never_feeds_the_counters() -> None:
    mw = LoopGuardMiddleware()
    for _ in range(LOOP_GUARD_STOP_SAME_TOOL + 5):
        await _wrap(mw, _request(), _succeeding())

    counters = mw._runs["thread-1"]
    assert counters.per_tool == {} and counters.identical == {}


# --- hard stop ---------------------------------------------------------------- #


async def test_warn_only_mode_never_blocks_execution() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="boom", tool_call_id="call-1", name="search", status="error")

    mw = LoopGuardMiddleware(hard_stop=False)
    total = LOOP_GUARD_STOP_IDENTICAL + LOOP_GUARD_STOP_SAME_TOOL + 3
    for _ in range(total):
        result = await _wrap(mw, _request(), handler)
        assert "loop_guard_stopped" not in result.additional_kwargs
    assert executed == total


async def test_hard_stop_blocks_the_call_after_the_identical_limit() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="boom", tool_call_id="call-1", name="search", status="error")

    mw = LoopGuardMiddleware(hard_stop=True)
    results = [await _wrap(mw, _request(), handler) for _ in range(LOOP_GUARD_STOP_IDENTICAL + 1)]

    assert executed == LOOP_GUARD_STOP_IDENTICAL  # the last call never reached the tool
    for result in results[:-1]:
        assert "loop_guard_stopped" not in result.additional_kwargs
    blocked = results[-1]
    assert blocked.additional_kwargs["loop_guard_stopped"] is True
    assert blocked.status == "error"
    assert blocked.tool_call_id == "call-1" and blocked.name == "search"
    assert f"already failed {LOOP_GUARD_STOP_IDENTICAL} times" in blocked.content
    assert "identical arguments" in blocked.content


async def test_hard_stop_blocks_the_call_after_the_same_tool_limit() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="boom", tool_call_id="call-1", name="search", status="error")

    mw = LoopGuardMiddleware(hard_stop=True)
    # Fresh args each call keeps the identical tally at 1 so only the same-tool
    # limit can be the thing that trips.
    results = [
        await _wrap(mw, _request(args={"q": str(i)}), handler)
        for i in range(LOOP_GUARD_STOP_SAME_TOOL + 1)
    ]

    assert executed == LOOP_GUARD_STOP_SAME_TOOL
    blocked = results[-1]
    assert blocked.additional_kwargs["loop_guard_stopped"] is True
    assert f"already failed {LOOP_GUARD_STOP_SAME_TOOL} times this run" in blocked.content
    assert "identical arguments" not in blocked.content


async def test_hard_stop_leaves_a_healthy_tool_alone() -> None:
    mw = LoopGuardMiddleware(hard_stop=True)
    # Fresh arguments each call: a tool doing real work is never blocked, however
    # often it runs. Re-issuing the SAME call is the loop the repeat guard exists
    # to catch, and is covered separately.
    for i in range(LOOP_GUARD_STOP_SAME_TOOL + 5):
        result = await _wrap(mw, _request(args={"q": str(i)}), _succeeding())
        assert result.content == "ok"


async def test_hard_stop_keeps_blocking_while_the_model_retries() -> None:
    mw = LoopGuardMiddleware(hard_stop=True)
    for _ in range(LOOP_GUARD_STOP_IDENTICAL):
        await _wrap(mw, _request(), _failing())

    for _ in range(3):
        blocked = await _wrap(mw, _request(), _failing())
        assert blocked.additional_kwargs["loop_guard_stopped"] is True


async def test_hard_stop_never_blocks_a_different_tool() -> None:
    mw = LoopGuardMiddleware(hard_stop=True)
    for _ in range(LOOP_GUARD_STOP_IDENTICAL):
        await _wrap(mw, _request(name="broken"), _failing(name="broken"))

    healthy = await _wrap(mw, _request(name="healthy"), _succeeding(name="healthy"))
    assert healthy.content == "ok"


async def test_a_success_elsewhere_reopens_a_hard_stopped_tool() -> None:
    # The consecutive streak is global, not per tool: any successful call clears
    # it, so the identical hard stop lifts even for an unrelated tool. Only the
    # same-tool tally survives, and it is the thing that eventually stops it.
    mw = LoopGuardMiddleware(hard_stop=True)
    for _ in range(LOOP_GUARD_STOP_IDENTICAL):
        await _wrap(mw, _request(name="broken"), _failing(name="broken"))
    await _wrap(mw, _request(name="healthy"), _succeeding(name="healthy"))

    reopened = await _wrap(mw, _request(name="broken"), _failing(name="broken"))
    assert "loop_guard_stopped" not in reopened.additional_kwargs
    assert mw._runs["thread-1"].per_tool["broken"] == LOOP_GUARD_STOP_IDENTICAL + 1


# --- per-run isolation -------------------------------------------------------- #


async def test_counters_do_not_leak_between_threads() -> None:
    mw = LoopGuardMiddleware()
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1, thread_id="thread-a")
    result = await _wrap(mw, _request(thread_id="thread-b"), _failing())

    assert "loop_guard_warned" not in result.additional_kwargs
    assert set(mw._runs) == {"thread-a", "thread-b"}


async def test_missing_thread_id_falls_back_to_a_single_bucket() -> None:
    mw = LoopGuardMiddleware()
    await _wrap(mw, _request(thread_id=None), _failing())
    assert list(mw._runs) == [_UNKNOWN_RUN]


async def test_thread_id_survives_a_request_without_a_runtime() -> None:
    request = ToolCallRequest(
        tool_call={"name": "search", "args": {}, "id": "call-1"},
        tool=None,
        state={},
        runtime=None,
    )
    assert LoopGuardMiddleware._thread_id(request) == _UNKNOWN_RUN


async def test_thread_id_survives_a_non_mapping_config() -> None:
    request = ToolCallRequest(
        tool_call={"name": "search", "args": {}, "id": "call-1"},
        tool=None,
        state={},
        runtime=_runtime(SimpleNamespace(configurable={"thread_id": "t"})),
    )
    assert LoopGuardMiddleware._thread_id(request) == _UNKNOWN_RUN


async def test_oldest_run_is_evicted_once_the_cap_is_passed() -> None:
    mw = LoopGuardMiddleware(max_tracked_runs=2)
    for thread_id in ("a", "b", "c"):
        await _wrap(mw, _request(thread_id=thread_id), _failing())

    assert list(mw._runs) == ["b", "c"]


async def test_touching_a_run_protects_it_from_eviction() -> None:
    mw = LoopGuardMiddleware(max_tracked_runs=2)
    for thread_id in ("a", "b"):
        await _wrap(mw, _request(thread_id=thread_id), _failing())
    await _wrap(mw, _request(thread_id="a"), _failing())  # refreshes "a"
    await _wrap(mw, _request(thread_id="c"), _failing())

    assert list(mw._runs) == ["a", "c"]  # "b" was the least recently used


async def test_evicting_a_run_forgets_its_tally() -> None:
    mw = LoopGuardMiddleware(max_tracked_runs=1)
    await _run(mw, LOOP_GUARD_WARN_IDENTICAL - 1, thread_id="a")
    await _wrap(mw, _request(thread_id="b"), _failing())  # evicts "a"
    result = await _wrap(mw, _request(thread_id="a"), _failing())

    assert "loop_guard_warned" not in result.additional_kwargs


# --- tool-call shapes and argument keying ------------------------------------- #


async def test_attribute_style_tool_call_is_read_correctly() -> None:
    tool_call = SimpleNamespace(name="objtool", id="obj-1", args={"k": "v"})
    request = ToolCallRequest(
        tool_call=cast(Any, tool_call),
        tool=None,
        state={},
        runtime=_runtime({"configurable": {"thread_id": "t"}}),
    )
    mw = LoopGuardMiddleware(hard_stop=True)
    for _ in range(LOOP_GUARD_STOP_IDENTICAL):
        await _wrap(mw, request, _failing(name="objtool"))
    blocked = await _wrap(mw, request, _failing(name="objtool"))

    assert blocked.additional_kwargs["loop_guard_stopped"] is True
    assert blocked.tool_call_id == "obj-1"
    assert "`objtool`" in blocked.content


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
    mw = LoopGuardMiddleware()
    await _wrap(mw, _request(args={"a": 1, "b": 2}), _failing())
    result = await _wrap(mw, _request(args={"b": 2, "a": 1}), _failing())

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


def test_no_hard_stop_message_below_both_limits() -> None:
    mw = LoopGuardMiddleware(hard_stop=True)
    assert (
        mw._hard_stop_message(
            "search", "1", LOOP_GUARD_STOP_IDENTICAL - 1, LOOP_GUARD_STOP_SAME_TOOL - 1
        )
        is None
    )


def test_no_warning_note_below_both_limits() -> None:
    mw = LoopGuardMiddleware()
    assert (
        mw._warning_note("search", LOOP_GUARD_WARN_IDENTICAL - 1, LOOP_GUARD_WARN_SAME_TOOL - 1)
        is None
    )


def test_fresh_run_counters_start_empty() -> None:
    # Every slot, not just the tallies: a run that started mid-streak would
    # warn or hard-stop a tool on its first call of the run.
    counters = _RunCounters()
    assert counters.identical == {}
    assert counters.per_tool == {}
    assert counters.last_failure_key is None
    assert counters.last_call_key is None
    assert counters.repeat == 0


# --- repeat detection: identical calls regardless of outcome ------------------ #
#
# Everything above tallies failures only. A call re-issued with identical
# arguments that SUCCEEDS is still a loop — a re-sent handoff, the same search
# fired twice — and is caught by its own counter.


async def test_identical_successful_calls_are_warned_at_the_repeat_threshold() -> None:
    mw = LoopGuardMiddleware()
    results = [await _wrap(mw, _request(), _succeeding()) for _ in range(LOOP_GUARD_WARN_REPEAT)]

    assert "[Loop guard:" not in results[0].content
    assert f"called {LOOP_GUARD_WARN_REPEAT} times in a row" in results[-1].content
    assert results[-1].additional_kwargs["loop_guard_warned"] is True


async def test_different_arguments_never_trip_the_repeat_warning() -> None:
    mw = LoopGuardMiddleware()
    for i in range(LOOP_GUARD_WARN_REPEAT + 2):
        result = await _wrap(mw, _request(args={"q": str(i)}), _succeeding())
        assert "[Loop guard:" not in result.content


async def test_hard_stop_blocks_a_repeated_successful_call_without_executing() -> None:
    executed = 0

    async def handler(_request: ToolCallRequest) -> ToolMessage:
        nonlocal executed
        executed += 1
        return ToolMessage(content="ok", tool_call_id="call-1", name="search")

    mw = LoopGuardMiddleware(hard_stop=True)
    results = [await _wrap(mw, _request(), handler) for _ in range(LOOP_GUARD_STOP_REPEAT)]

    assert executed == LOOP_GUARD_STOP_REPEAT - 1  # the last call never reached the tool
    blocked = results[-1]
    assert blocked.additional_kwargs["loop_guard_stopped"] is True
    assert blocked.status == "error"
    assert f"limit {LOOP_GUARD_STOP_REPEAT}" in blocked.content


async def test_the_repeat_streak_is_per_thread() -> None:
    mw = LoopGuardMiddleware()
    # Each thread stops one short of the threshold while the combined count goes
    # past it — a shared counter would warn here, a per-thread one cannot.
    for _ in range(LOOP_GUARD_WARN_REPEAT - 1):
        for thread in ("thread-a", "thread-b"):
            result = await _wrap(mw, _request(thread_id=thread), _succeeding())
            assert "[Loop guard:" not in result.content


async def test_the_repeat_block_spells_out_the_count_the_limit_and_the_way_out() -> None:
    """The blocked call's text is all the model gets — it never sees the guard.

    Asserted verbatim rather than by keyword: a message that dropped the count,
    the limit or the instruction would still contain "Loop guard" and still
    read as a working stop, while telling the model nothing it can act on.
    """
    log.reset()
    mw = LoopGuardMiddleware(hard_stop=True)
    blocked = [await _wrap(mw, _request(), _succeeding()) for _ in range(LOOP_GUARD_STOP_REPEAT)][
        -1
    ]

    assert blocked.content == (
        "[Loop guard] Blocked without executing: `search` has already been "
        f"called {LOOP_GUARD_STOP_REPEAT} times in a row with identical arguments (limit "
        f"{LOOP_GUARD_STOP_REPEAT}). Re-running it will return the same result — "
        "reuse the earlier result, or if the task is done, stop and report it."
    )
    assert blocked.name == "search"  # the frontend keys the tool card off this


async def test_a_repeat_block_is_reported_with_the_tool_and_the_streak() -> None:
    # The wide event is the only trace a call was refused; without the tool name
    # and the streak an operator cannot tell which tool the guard is capping.
    log.reset()
    mw = LoopGuardMiddleware(hard_stop=True)
    for _ in range(LOOP_GUARD_STOP_REPEAT):
        await _wrap(mw, _request(), _succeeding())

    blocks = _warnings("Loop guard hard-stopped tool — redundant duplicate call not executed")
    assert len(blocks) == 1
    assert blocks[0]["tool_name"] == "search"
    assert blocks[0]["repeat"] == LOOP_GUARD_STOP_REPEAT


async def test_the_repeat_warning_note_is_appended_verbatim() -> None:
    log.reset()
    mw = LoopGuardMiddleware()
    warned = [await _wrap(mw, _request(), _succeeding()) for _ in range(LOOP_GUARD_WARN_REPEAT)][-1]

    assert warned.content == (
        "ok"
        f"\n\n[Loop guard: `search` has now been called {LOOP_GUARD_WARN_REPEAT} times in a row "
        "with identical arguments. The result won't change — reuse the earlier result "
        "and move on instead of repeating this call.]"
    )

    notes = _warnings("Loop guard repeat-warning appended for tool")
    assert len(notes) == 1
    assert notes[0]["tool_name"] == "search"
    assert notes[0]["repeat"] == LOOP_GUARD_WARN_REPEAT


async def test_an_identical_failing_run_reports_the_failure_stop_not_the_repeat_one() -> None:
    """Both counters trip on the same call; the specific diagnosis has to win."""
    mw = LoopGuardMiddleware(hard_stop=True)
    results = [
        await _wrap(mw, _request(), _failing()) for _ in range(LOOP_GUARD_STOP_IDENTICAL + 1)
    ]

    blocked = results[-1]
    assert f"already failed {LOOP_GUARD_STOP_IDENTICAL} times" in blocked.content
