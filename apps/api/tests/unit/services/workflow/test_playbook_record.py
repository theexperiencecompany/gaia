"""A playbook built from picks over the run record: what a pick can say, and what it replays.

The property tests are the contract write_playbook stands on. For any run and
any valid picks over it, the built playbook validates, and resolving each step
the way the replay does (with this run's own results, clock and written text)
gives back exactly the calls the run made: tool, args, scope and account.
"""

import asyncio
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import string
from unittest.mock import AsyncMock, patch

from hypothesis import given, strategies as st
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import create_model
import pytest

from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.execute.unwrap import execute_call_account, unwrap_execute_call
from app.models.playbook_models import (
    MAX_FOR_EACH_ITEMS,
    ForEachStep,
    HandoffStep,
    PlaybookBody,
    ToolStep,
    is_ask_slot,
)
from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.evaluator import (
    PlaybookUser,
    RunContext,
    StepResult,
    resolve_args,
)
from app.services.workflow.playbook.parser import RecordedResult, validate_playbook
from app.services.workflow.playbook.record import (
    PlaybookPick,
    build_playbook,
    number_record,
    render_record,
)
from app.services.workflow.playbook.tool_space import SubagentTools

PARSER = "app.services.workflow.playbook.parser"
USER_ID = "507f1f77bcf86cd799439011"
#: Every day within the offsets below is past the 12th, so no recorded date reads as two layouts.
NOW = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)
USER = PlaybookUser(email="dana@acme.com", name="Dana", timezone="UTC")
SCOPE = "linear"
TOOL_NAMES = ("tool_a", "tool_b", "tool_c")
ARG_NAMES = ("first", "second", "nested")
EXCLUDED = frozenset({"retrieve_tools"})


def _fake_tool(name: str) -> BaseTool:
    schema = create_model(f"{name}_args", **dict.fromkeys(ARG_NAMES, (object, ...)))

    async def run(**kwargs: object) -> str:
        return json.dumps(kwargs, default=str)

    return StructuredTool.from_function(
        coroutine=run, name=name, description=f"{name}.", args_schema=schema
    )


TOOLS: dict[str, BaseTool] = {name: _fake_tool(name) for name in TOOL_NAMES} | {"execute": execute}


class _Registry:
    def get_tool_dict(self) -> dict[str, BaseTool]:
        return TOOLS


def _validate(body: PlaybookBody, sources: list[RecordedResult]) -> list[str]:
    space = SubagentTools(tools=TOOLS, initial_tool_ids=[])
    with (
        patch(f"{PARSER}.get_tool_registry", AsyncMock(return_value=_Registry())),
        patch(f"{PARSER}.resolve_subagent_tools", AsyncMock(return_value=space)),
    ):
        validation = asyncio.run(validate_playbook(body, USER_ID, sources))
    return [f"{issue.where}: {issue.problem}" for issue in validation.issues]


def _call(
    tool: str, args: dict[str, object], result: object, **flags: str | bool | None
) -> RecordedCall:
    """Record one call; flags set its scope, proxy, account or failure."""
    call = RecordedCall(tool_name=tool, args=args, result_digest=json.dumps(result))
    return RecordedCall.model_validate({**call.model_dump(), **flags})


def _build(calls: Sequence[RecordedCall], picks: Sequence[Mapping[str, object]]):
    return build_playbook(
        "d",
        [PlaybookPick.model_validate(pick) for pick in picks],
        "r",
        number_record(calls, EXCLUDED),
    )


def _problems(calls: Sequence[RecordedCall], picks: Sequence[Mapping[str, object]]) -> list[str]:
    return [f"{issue.where}: {issue.problem}" for issue in _build(calls, picks).issues]


LISTING = {"items": [{"id": "e1", "n": 1}, {"id": "e2", "n": 2}], "total": 2}


# --- the property: picks validate and replay to the calls the run made ------

_TEXT = st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=12).filter(str.strip)
_IDS = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=3, max_size=8)
_TIME_PLACEHOLDERS = (
    "$now",
    "$today",
    "$today + 1d",
    "$today - 2d 08:00",
    "$now + 3h",
    "$today + 1d 09:00",
)
#: Layouts a tool might take, each one readable from a single example.
_LAYOUTS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d %B %Y",
    "%B %d, %Y",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S%:z",
)


def _context(steps: Mapping[str, StepResult], item: object = None) -> RunContext:
    if item is None:
        return RunContext(user=USER, now=NOW, trigger={}, steps=steps)
    return RunContext(user=USER, now=NOW, trigger={}, steps=steps, item=item)


@dataclass
class _Run:
    """A generated run: its calls in order, and the picks that freeze the work in it."""

    calls: list[RecordedCall]
    picks: list[dict[str, object]]


@st.composite
def _value(draw: st.DrawFn, earlier: Sequence[tuple[str, object]]) -> tuple[object, object | None]:
    """Draw one argument: what the run sent, and what a pick marks there (None: left as recorded)."""
    kinds = ["literal", "time", "bare_time", "ask", "user"]
    if earlier:
        kinds += ["reference", "embedded_reference"]
    kind = draw(st.sampled_from(kinds))
    if kind == "literal":
        return draw(st.one_of(_TEXT, st.integers(), st.lists(_TEXT, max_size=2))), None
    if kind == "ask":
        return draw(_TEXT), {"$ask": "write this value"}
    if kind == "user":
        return USER.email, "$user.email"
    if kind in ("time", "bare_time"):
        placeholder = draw(st.sampled_from(_TIME_PLACEHOLDERS))
        layout = draw(st.sampled_from(_LAYOUTS))
        recorded = resolve_args({"v": {"$time": placeholder, "format": layout}}, _context({}))["v"]
        return recorded, ({"$time": placeholder} if kind == "time" else placeholder)
    step_id, result = draw(st.sampled_from(list(earlier)))
    items = result["items"]  # type: ignore[index]
    index = draw(st.integers(0, len(items) - 1))
    picked = items[index]["id"]
    if kind == "reference":
        return picked, f"$steps.{step_id}.items.{index}.id"
    return f"Re: {picked}", f"Re: $steps.{step_id}.items.{index}.id"


@st.composite
def _runs(draw: st.DrawFn) -> _Run:
    calls: list[RecordedCall] = []
    picks: list[dict[str, object]] = []
    earlier: list[tuple[str, object]] = []
    for _ in range(draw(st.integers(1, 5))):
        for _noise in range(draw(st.integers(0, 2))):
            calls.append(draw(_noise_call()))
        number = len(calls) + 1
        step_id = draw(st.sampled_from([f"s{number}", ""]))
        listing = {
            "items": [{"id": draw(_IDS), "n": n} for n in range(draw(st.integers(1, 3)))],
            "total": 1,
        }
        args: dict[str, object] = {}
        vary: dict[str, object] = {}
        for_each: dict[str, object] = {}
        if earlier and draw(st.booleans()):
            source_id, source = draw(st.sampled_from(earlier))
            args["first"] = source["items"][0]["id"]  # type: ignore[index]
            vary["first"] = "$item.id"
            for_each = {"for_each": f"$steps.{source_id}.items"}
        for name in ARG_NAMES:
            if name in args:
                continue
            recorded, marked = draw(_value(earlier))
            if name == "nested":
                args[name] = {"inner": recorded, "kept": "as is"}
                if marked is not None:
                    vary["nested.inner"] = marked
            else:
                args[name] = recorded
                if marked is not None:
                    vary[name] = marked
        subagent = draw(st.sampled_from([None, SCOPE]))
        proxied = draw(st.booleans())
        calls.append(
            _call(
                draw(st.sampled_from(TOOL_NAMES)),
                args,
                listing,
                subagent=subagent,
                proxied=proxied,
                account=draw(st.sampled_from([None, "work@acme.com"])) if proxied else None,
            )
        )
        picks.append({"call": number, "id": step_id, "vary": vary, **for_each})
        earlier.append((step_id or f"call{number}", listing))
    return _Run(calls=calls, picks=draw(st.permutations(picks)))


@st.composite
def _noise_call(draw: st.DrawFn) -> RecordedCall:
    """Draw a call no pick names: discovery, a dead end, or one that failed."""
    kind = draw(st.sampled_from(["unpickable", "unpicked", "failed"]))
    if kind == "unpickable":
        return _call("retrieve_tools", {"query": draw(_TEXT)}, {"tools": []})
    return _call(
        draw(st.sampled_from(TOOL_NAMES)),
        {name: draw(_TEXT) for name in ARG_NAMES},
        {"items": []},
        failed=kind == "failed",
    )


def _flatten(
    steps: Sequence[ToolStep | ForEachStep | HandoffStep],
) -> Iterator[tuple[ToolStep | ForEachStep, str | None]]:
    for step in steps:
        if isinstance(step, HandoffStep):
            for child in step.steps:
                yield child, step.handoff
        else:
            yield step, None


def _with_written_text(value: object, recorded: object) -> object:
    """Stand the run's own value in where a pick asked a model to write one."""
    if is_ask_slot(value):
        return recorded
    if isinstance(value, Mapping) and isinstance(recorded, Mapping):
        return {key: _with_written_text(item, recorded[key]) for key, item in value.items()}
    return value


def _replayed(body: PlaybookBody, sources: Sequence[RecordedResult]) -> list[dict[str, object]]:
    """Resolve every step as the replay does, against this run's results."""
    replayed: list[dict[str, object]] = []
    steps: dict[str, StepResult] = {}
    for (step, scope), source in zip(_flatten(body.steps), sources, strict=True):
        name, args = unwrap_execute_call(step.tool, step.args)
        recorded_args = dict(source.args)
        written = {
            key: _with_written_text(value, recorded_args[key]) for key, value in args.items()
        }
        item = None
        if isinstance(step, ForEachStep):
            listing = steps[str(step.for_each).split(".")[1]].value
            item = listing["items"][0]  # type: ignore[index]
        replayed.append(
            {
                "tool": name,
                "args": resolve_args(written, _context(steps, item)),
                "subagent": scope,
                "account": execute_call_account(step.tool, step.args),
            }
        )
        steps[step.id] = StepResult(value=source.result)
    return replayed


@given(_runs())
def test_any_valid_picks_build_a_playbook_that_validates(run: _Run) -> None:
    built = _build(run.calls, run.picks)

    assert [f"{issue.where}: {issue.problem}" for issue in built.issues] == []
    assert built.body is not None
    assert _validate(built.body, built.sources) == []


def _at(args: Mapping[str, object], path: str) -> object:
    value: object = args
    for part in path.split("."):
        assert isinstance(value, Mapping)
        value = value[part]
    return value


@given(_runs())
def test_every_marked_value_is_what_the_step_stores(run: _Run) -> None:
    """The other half of replaying the same calls: a step that ignored its marks would replay them too."""
    built = _build(run.calls, run.picks)
    assert built.body is not None

    stored = {
        step.id: unwrap_execute_call(step.tool, step.args)[1]
        for step, _ in _flatten(built.body.steps)
    }
    for pick in run.picks:
        number = int(str(pick["call"]))
        args = stored[str(pick["id"]) or f"call{number}"]
        for path, marked in dict(pick["vary"]).items():  # type: ignore[call-overload]
            value = _at(args, path)
            if isinstance(marked, dict):
                assert {key: value[key] for key in marked} == marked  # type: ignore[index]
            elif value != marked:
                assert value == {"$time": marked, "format": value["format"]}  # type: ignore[index]


@given(_runs())
def test_a_built_playbook_replays_the_calls_the_run_made(run: _Run) -> None:
    built = _build(run.calls, run.picks)
    assert built.body is not None

    picked = sorted(int(str(pick["call"])) for pick in run.picks)
    made = [run.calls[number - 1] for number in picked]
    assert _replayed(built.body, built.sources) == [
        {
            "tool": call.tool_name,
            "args": call.args,
            "subagent": call.subagent,
            "account": call.account,
        }
        for call in made
    ]


# --- what a pick can get wrong, each with the fix in the message -------------


def test_a_number_that_is_not_in_the_record_lists_the_ones_that_are() -> None:
    calls = [_call("retrieve_tools", {}, {}), _call("tool_a", {"first": "x"}, LISTING)]

    assert _problems(calls, [{"call": 1}, {"call": 7}]) == [
        "steps[0].call: call 1 is not in this run's record; the calls you can pick are 2 "
        "(read_run_record lists them)",
        "steps[1].call: call 7 is not in this run's record; the calls you can pick are 2 "
        "(read_run_record lists them)",
    ]


def test_a_call_picked_twice_is_refused() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING)]

    assert _problems(calls, [{"call": 1}, {"call": 1, "id": "again"}]) == [
        "steps[1].call: call 1 is picked twice; one recorded call is one step, so pick it once"
    ]


def test_two_steps_cannot_share_an_id() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING), _call("tool_b", {"first": "y"}, LISTING)]

    assert _problems(calls, [{"call": 1, "id": "s"}, {"call": 2, "id": "s"}]) == [
        "steps[1].id: id 's' is already used by another step; give each step its own"
    ]


def test_a_call_that_failed_cannot_be_frozen() -> None:
    calls = [_call("tool_a", {"first": "x"}, "Error: TimeoutError: slow", failed=True)]

    assert _problems(calls, [{"call": 1}]) == [
        'steps[0].call: call 1 (tool_a) failed in this run ("Error: TimeoutError: slow"); '
        "pick the call that succeeded"
    ]


def test_a_path_the_call_does_not_have_lists_the_ones_it_does() -> None:
    calls = [_call("tool_a", {"first": "x", "nested": {"inner": 1, "list": ["a"]}}, LISTING)]

    assert _problems(calls, [{"call": 1, "vary": {"nested.missing": "$today"}}]) == [
        "steps[0].vary.nested.missing: tool_a was called with no value at 'nested.missing'; "
        "its arg paths are: first, nested.inner, nested.list.0"
    ]


def test_a_marked_value_with_no_placeholder_is_refused() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING)]

    assert _problems(calls, [{"call": 1, "vary": {"first": "y"}}]) == [
        "steps[0].vary.first: 'y' holds no placeholder, so it does not change per run; leave "
        "'first' out to replay the recorded 'x', or write one ($today, $steps.<step_id>.<path>, "
        "$item.<path>, ...)"
    ]


def test_a_time_inside_other_text_is_refused_with_the_slot_to_write() -> None:
    calls = [_call("tool_a", {"first": "Plan for November 20, 2026"}, LISTING)]

    assert _problems(calls, [{"call": 1, "vary": {"first": "Plan for $today"}}]) == [
        "steps[0].vary.first: 'first' was 'Plan for November 20, 2026'; a time inside other "
        'text renders as ISO 8601, not that layout. Write the whole value as {"$time": "$today"}'
    ]


def test_an_iso_date_inside_text_can_vary_beside_other_values() -> None:
    """A title like "Run at 2026-11-20 for Dana" has no $time form, since the name changes too."""
    calls = [_call("tool_a", {"first": "Run at 2026-11-20 for someone"}, LISTING)]

    built = _build(calls, [{"call": 1, "vary": {"first": "Run at $today for $user.name"}}])

    assert built.issues == []
    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == "Run at $today for $user.name"


def test_a_time_with_no_layout_to_read_needs_one() -> None:
    calls = [_call("tool_a", {"first": "soon"}, LISTING)]

    assert _problems(calls, [{"call": 1, "vary": {"first": {"$time": "$today"}}}]) == [
        "steps[0].vary.first: 'first' was 'soon', which reads as no date layout; give the "
        'strftime layout the tool takes as "format"'
    ]


def test_a_layout_that_cannot_have_produced_the_recorded_value_is_refused() -> None:
    calls = [_call("tool_a", {"first": "2026-11-20 09:00:00"}, LISTING)]

    assert _problems(
        calls, [{"call": 1, "vary": {"first": {"$time": "$today", "format": "%d/%m/%Y"}}}]
    ) == [
        "steps[0].vary.first: 'first' was '2026-11-20 09:00:00', which is not written in "
        "'%d/%m/%Y'; leave format out to keep the recorded layout"
    ]


def test_an_ambiguous_date_takes_the_layout_the_author_names() -> None:
    """03/11/2026 reads as March or as November; only the author knows which the tool meant."""
    calls = [_call("tool_a", {"first": "03/11/2026"}, LISTING)]

    built = _build(
        calls, [{"call": 1, "vary": {"first": {"$time": "$today", "format": "%m/%d/%Y"}}}]
    )

    assert built.issues == []
    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == {"$time": "$today", "format": "%m/%d/%Y"}


def test_a_for_each_must_mark_what_changes_per_element() -> None:
    calls = [
        _call("tool_a", {"first": "x"}, LISTING),
        _call("tool_b", {"first": "e1"}, {"ok": True}),
    ]

    assert _problems(
        calls, [{"call": 1, "id": "list"}, {"call": 2, "for_each": "$steps.list.items"}]
    ) == [
        "steps[1].vary: a for_each step runs its call once per element, so mark the value that "
        'changes per element with $item, e.g. vary: {"<arg>": "$item.id"}; otherwise every '
        "element repeats the recorded call"
    ]


# --- what a pick builds ------------------------------------------------------


def test_steps_follow_the_order_the_run_made_the_calls_and_take_default_ids() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING), _call("tool_b", {"first": "y"}, LISTING)]

    built = _build(calls, [{"call": 2}, {"call": 1, "id": "list"}])

    assert built.body is not None
    assert [step.to_document() for step in built.body.steps] == [
        {"id": "list", "tool": "tool_a", "args": {"first": "x"}},
        {"id": "call2", "tool": "tool_b", "args": {"first": "y"}},
    ]


def test_a_subagents_consecutive_calls_become_one_handoff() -> None:
    calls = [
        _call("tool_a", {"first": "x"}, LISTING, subagent=SCOPE),
        _call("tool_b", {"first": "y"}, LISTING, subagent=SCOPE),
        _call("tool_c", {"first": "z"}, LISTING),
        _call("tool_a", {"first": "w"}, LISTING, subagent=SCOPE),
    ]

    built = _build(calls, [{"call": n} for n in (1, 2, 3, 4)])

    assert built.body is not None
    assert [
        (step.handoff, [child.tool for child in step.steps])
        if isinstance(step, HandoffStep)
        else (None, [step.tool])
        for step in built.body.steps
    ] == [(SCOPE, ["tool_a", "tool_b"]), (None, ["tool_c"]), (SCOPE, ["tool_a"])]


def test_a_call_made_through_execute_replays_through_it_as_its_account() -> None:
    calls = [_call("GMAIL_SEND", {"to": "x"}, {"id": "m"}, proxied=True, account="work@acme.com")]

    built = _build(calls, [{"call": 1, "vary": {"to": "$user.email"}}])

    assert built.body is not None
    assert built.body.steps[0].to_document() == {
        "id": "call1",
        "tool": "execute",
        "args": {
            "task_description": "GMAIL_SEND",
            "tool_name": "GMAIL_SEND",
            "data": {"to": "$user.email"},
            "account": "work@acme.com",
        },
    }


def test_a_bare_time_over_a_tool_layout_is_stored_as_a_slot_in_that_layout() -> None:
    calls = [_call("tool_a", {"first": "2026-11-21 09:00:00"}, LISTING)]

    built = _build(calls, [{"call": 1, "vary": {"first": "$today + 1d 09:00"}}])

    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == {"$time": "$today + 1d 09:00", "format": "%Y-%m-%d %H:%M:%S"}


def test_a_bare_time_over_an_iso_value_stays_bare() -> None:
    calls = [_call("tool_a", {"first": "2026-11-20"}, LISTING)]

    built = _build(calls, [{"call": 1, "vary": {"first": "$today"}}])

    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == "$today"


def test_a_for_each_without_a_ceiling_takes_the_most_a_replay_allows() -> None:
    calls = [
        _call("tool_a", {"first": "x"}, LISTING),
        _call("tool_b", {"first": "e1"}, {"ok": True}),
    ]

    built = _build(
        calls,
        [
            {"call": 1, "id": "list"},
            {"call": 2, "for_each": "$steps.list.items", "vary": {"first": "$item.id"}},
        ],
    )

    assert built.body is not None
    step = built.body.steps[1]
    assert isinstance(step, ForEachStep)
    assert step.max_items == MAX_FOR_EACH_ITEMS


def test_a_replays_execute_call_is_numbered_as_the_tool_it_ran() -> None:
    replayed = _call(
        "execute",
        {
            "task_description": "x",
            "tool_name": "GMAIL_SEND",
            "data": {"to": "x"},
            "account": "a@b.c",
        },
        {"id": "m"},
    )

    (entry,) = number_record([replayed], EXCLUDED)

    assert (entry.call.tool_name, entry.call.args, entry.call.proxied, entry.call.account) == (
        "GMAIL_SEND",
        {"to": "x"},
        True,
        "a@b.c",
    )


def test_the_record_shows_shapes_not_values() -> None:
    calls = [
        _call("tool_a", {"first": "x"}, {"items": [{"id": "e1"}], "next": None, "total": 3}),
        _call("tool_b", {}, {"items": []}),
    ]

    assert [line["returned"] for line in render_record(number_record(calls, EXCLUDED))] == [
        {"items": {"list of 1": {"id": "str"}}, "next": "null", "total": "int"},
        {"items": "empty list"},
    ]


@pytest.mark.parametrize("excluded_first", [True, False])
def test_numbers_do_not_move_when_calls_are_left_out(excluded_first: bool) -> None:
    kept = _call("tool_a", {"first": "x"}, LISTING)
    left_out = _call("retrieve_tools", {}, {})
    calls = [left_out, kept] if excluded_first else [kept, left_out]

    assert [entry.number for entry in number_record(calls, EXCLUDED)] == [
        2 if excluded_first else 1
    ]
