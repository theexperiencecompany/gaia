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
    LOOP_GUARD_STOP_SAME_TOOL,
    LOOP_GUARD_WARN_IDENTICAL,
    LOOP_GUARD_WARN_SAME_TOOL,
)


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
    result = await _wrap(mw, _request(), _succeeding())

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
    for _ in range(LOOP_GUARD_STOP_SAME_TOOL + 5):
        result = await _wrap(mw, _request(), _succeeding())
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
    counters = _RunCounters()
    assert counters.identical == {}
    assert counters.per_tool == {}
    assert counters.last_failure_key is None
