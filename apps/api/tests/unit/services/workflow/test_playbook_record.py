"""A playbook built from picks over the run record: what a pick can say, and what it replays.

The property tests are the contract write_playbook stands on. For any run and
any valid picks over it, the built playbook validates, and resolving each step
the way the replay does (with this run's own results, clock and written text)
gives back exactly the calls the run made: tool, args and account.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import string
from unittest.mock import AsyncMock, patch

from hypothesis import given, strategies as st
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel
import pytest

from app.agents.tools.execute.execute_tool import execute
from app.agents.tools.execute.unwrap import execute_call_account, unwrap_execute_call
from app.models.playbook_models import (
    MAX_FOR_EACH_ITEMS,
    ForEachStep,
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
    result_shape,
)

PARSER = "app.services.workflow.playbook.parser"
#: Every day within the offsets below is past the 12th, so no recorded date reads as two layouts.
NOW = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)
USER = PlaybookUser(email="dana@acme.com", name="Dana", timezone="UTC")
TOOL_NAMES = ("tool_a", "tool_b", "tool_c")


class _FakeToolArgs(BaseModel):
    first: object
    second: object
    nested: object


ARG_NAMES = tuple(_FakeToolArgs.model_fields)
EXCLUDED = frozenset({"retrieve_tools"})


def _fake_tool(name: str) -> BaseTool:
    async def run(**kwargs: object) -> str:
        return json.dumps(kwargs, default=str)

    return StructuredTool.from_function(
        coroutine=run, name=name, description=f"{name}.", args_schema=_FakeToolArgs
    )


TOOLS: dict[str, BaseTool] = {name: _fake_tool(name) for name in TOOL_NAMES} | {"execute": execute}


class _Registry:
    def get_tool_dict(self) -> dict[str, BaseTool]:
        return TOOLS


def _validate(body: PlaybookBody, sources: list[RecordedResult]) -> list[str]:
    with patch(f"{PARSER}.get_tool_registry", AsyncMock(return_value=_Registry())):
        validation = asyncio.run(validate_playbook(body, sources))
    return [f"{issue.where}: {issue.problem}" for issue in validation.issues]


def _call(
    tool: str, args: dict[str, object], result: object, **flags: str | bool | None
) -> RecordedCall:
    """Record one call; flags set its proxy, account or failure."""
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


def _all_args(**given: object) -> dict[str, object]:
    """Return a call's args with every arg the fake tools require, the given ones as written."""
    return {name: f"{name} value" for name in ARG_NAMES} | given


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


#: One recorded listing's elements: what a later call reads by index.
_Items = list[dict[str, object]]


def _items(result: object) -> _Items:
    """Return a generated listing's elements, the shape _runs records every call with."""
    assert isinstance(result, dict)
    items = result["items"]
    assert isinstance(items, list)
    return items


@dataclass
class _Run:
    """A generated run: its calls in order, and the picks that freeze the work in it."""

    calls: list[RecordedCall]
    picks: list[dict[str, object]]

    def numbered(self, number: int) -> RecordedCall:
        """Return the call a pick names: the number-th call that is not excluded."""
        return [call for call in self.calls if call.tool_name not in EXCLUDED][number - 1]


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
    items = _items(result)
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
        number = sum(call.tool_name not in EXCLUDED for call in calls) + 1
        step_id = draw(st.sampled_from([f"s{number}", ""]))
        listing = {
            "items": [{"id": draw(_IDS), "n": n} for n in range(draw(st.integers(1, 3)))],
            "total": 1,
        }
        args: dict[str, object] = {}
        vary: dict[str, object] = {}
        for_each: dict[str, object] = {}
        if bool(earlier) and draw(st.booleans()):
            source_id, source = draw(st.sampled_from(earlier))
            args["first"] = _items(source)[0]["id"]
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
        proxied = draw(st.booleans())
        calls.append(
            _call(
                draw(st.sampled_from(TOOL_NAMES)),
                args,
                listing,
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
    for step, source in zip(body.steps, sources, strict=True):
        name, args = unwrap_execute_call(step.tool, step.args)
        recorded_args = dict(source.args)
        written = {
            key: _with_written_text(value, recorded_args[key]) for key, value in args.items()
        }
        item = None
        if isinstance(step, ForEachStep):
            listing = steps[str(step.for_each).split(".")[1]].value
            item = _items(listing)[0]
        replayed.append(
            {
                "tool": name,
                "args": resolve_args(written, _context(steps, item)),
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

    stored = {step.id: unwrap_execute_call(step.tool, step.args)[1] for step in built.body.steps}
    for pick in run.picks:
        number = int(str(pick["call"]))
        args = stored[str(pick["id"]) or f"call{number}"]
        vary = pick["vary"]
        assert isinstance(vary, dict)
        for path, marked in vary.items():
            value = _at(args, path)
            if isinstance(marked, dict):
                assert isinstance(value, dict)
                assert {key: value[key] for key in marked} == marked
            elif value != marked:
                assert isinstance(value, dict)
                assert value == {"$time": marked, "format": value["format"]}


@given(_runs())
def test_a_built_playbook_replays_the_calls_the_run_made(run: _Run) -> None:
    built = _build(run.calls, run.picks)
    assert built.body is not None

    picked = sorted(int(str(pick["call"])) for pick in run.picks)
    made = [run.numbered(number) for number in picked]
    assert _replayed(built.body, built.sources) == [
        {
            "tool": call.tool_name,
            "args": call.args,
            "account": call.account,
        }
        for call in made
    ]


# --- what a pick can get wrong, each with the fix in the message -------------


def test_a_number_that_is_not_in_the_record_lists_the_ones_that_are() -> None:
    calls = [_call("retrieve_tools", {}, {}), _call("tool_a", {"first": "x"}, LISTING)]

    assert _problems(calls, [{"call": 2}, {"call": 7}]) == [
        "steps[0].call: call 2 is not in this run's record; the calls you can pick are 1 "
        "(read_run_record lists them)",
        "steps[1].call: call 7 is not in this run's record; the calls you can pick are 1 "
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


def test_a_named_layout_that_cannot_have_produced_the_recorded_value_gives_way_to_it() -> None:
    calls = [_call("tool_a", {"first": "2026-11-20 09:00:00"}, LISTING)]

    built = _build(
        calls, [{"call": 1, "vary": {"first": {"$time": "$today", "format": "%d/%m/%Y"}}}]
    )

    assert built.issues == []
    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == {"$time": "$today", "format": "%Y-%m-%d %H:%M:%S"}


@pytest.mark.parametrize(
    ("recorded", "named", "kept"),
    [
        # prod 2026-09-22: %z reads the Z, but would write +0000 at replay.
        ("2026-10-08T14:50:20Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"),
        # prod 2026-09-10: %z writes -0400 where the tool took -04:00.
        ("2026-09-10T14:50:00-04:00", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S%:z"),
    ],
)
def test_a_named_layout_that_reads_the_value_but_writes_it_otherwise_takes_the_recorded_one(
    recorded: str, named: str, kept: str
) -> None:
    calls = [_call("tool_a", _all_args(first=recorded), LISTING)]

    built = _build(calls, [{"call": 1, "vary": {"first": {"$time": "$now", "format": named}}}])

    assert built.issues == []
    assert built.body is not None
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert step.args["first"] == {"$time": "$now", "format": kept}
    assert _validate(built.body, built.sources) == []


def test_an_ambiguous_date_in_the_authors_layout_validates() -> None:
    calls = [_call("tool_a", _all_args(first="03/11/2026"), LISTING)]

    built = _build(
        calls, [{"call": 1, "vary": {"first": {"$time": "$today", "format": "%m/%d/%Y"}}}]
    )

    assert built.body is not None
    assert _validate(built.body, built.sources) == []


@pytest.mark.parametrize("offset", ["$now + 15min", "$now + 15 minutes", "$now + 15mins"])
def test_an_offset_unit_written_out_is_a_time(offset: str) -> None:
    """Prod 2026-09-24: "$now + 15min" read as $now followed by text, and was refused."""
    calls = [_call("tool_a", _all_args(first="2026-11-20T09:45:00Z"), LISTING)]

    built = _build(calls, [{"call": 1, "vary": {"first": offset}}])

    assert built.issues == []
    assert built.body is not None
    assert _validate(built.body, built.sources) == []
    step = built.body.steps[0]
    assert isinstance(step, ToolStep)
    assert resolve_args(step.args, _context({}))["first"] == "2026-11-20T09:45:00Z"


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
        'changes per element with $item (vary: {"<arg>": "$item.id"}) or with text written per '
        'element (vary: {"<arg>": {"$ask": "..."}}); otherwise every element repeats the '
        "recorded call"
    ]


def test_a_for_each_whose_values_are_written_per_element_is_accepted() -> None:
    """Prod 2026-09-26: a draft per picked email, every arg an $ask, was refused for lacking $item."""
    calls = [
        _call("tool_a", _all_args(), LISTING),
        _call("tool_b", _all_args(first="Hi Dana", second="Re: plan"), {"draft_id": "d1"}),
    ]

    built = _build(
        calls,
        [
            {"call": 1, "id": "list"},
            {
                "call": 2,
                "for_each": {"$ask": "the emails above that expect a reply"},
                "vary": {"first": {"$ask": "the reply"}, "second": {"$ask": "Re: its subject"}},
            },
        ],
    )

    assert built.issues == []
    assert built.body is not None
    assert _validate(built.body, built.sources) == []


# --- what a pick builds ------------------------------------------------------


def test_steps_follow_the_order_the_run_made_the_calls_and_take_default_ids() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING), _call("tool_b", {"first": "y"}, LISTING)]

    built = _build(calls, [{"call": 2}, {"call": 1, "id": "list"}])

    assert built.body is not None
    assert [step.to_document() for step in built.body.steps] == [
        {"id": "list", "tool": "tool_a", "args": {"first": "x"}},
        {"id": "call2", "tool": "tool_b", "args": {"first": "y"}},
    ]


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


def test_calls_that_cannot_be_picked_take_no_number() -> None:
    """The run's own dispatch and discovery come first in a real record; numbering them would leave the author gaps to skip."""
    kept = _call("tool_a", {"first": "x"}, LISTING)
    left_out = _call("retrieve_tools", {}, {})

    entries = number_record([left_out, kept, left_out, kept], EXCLUDED)

    assert [entry.number for entry in entries] == [1, 2]


def test_a_number_holds_as_the_record_grows() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING)]
    before = number_record(calls, EXCLUDED)

    after = number_record([*calls, _call("retrieve_tools", {}, {}), *calls], EXCLUDED)

    assert after[: len(before)] == before


# --- every refusal is reported at once, each where the author wrote it --------


def test_every_bad_pick_is_reported_in_one_answer() -> None:
    """A model told one problem per round trip gives up before the last one."""
    calls = [
        _call("tool_a", {"first": "x"}, "Error: no", failed=True),
        _call("tool_b", {"first": "y"}, LISTING),
        _call("tool_c", {"first": "z"}, LISTING),
    ]

    picks: list[dict[str, object]] = [
        {"call": 1},
        {"call": 2, "vary": {"missing": "$today"}},
        {"call": 2},
        {"call": 9},
        {"call": 3, "id": "call2"},
        {"call": 8},
    ]

    # call2 is pick 2's default id, so naming call 3 that is a clash too.
    assert [problem.split(":")[0] for problem in _problems(calls, picks)] == [
        "steps[2].call",
        "steps[3].call",
        "steps[4].id",
        "steps[5].call",
        "steps[0].call",
        "steps[1].vary.missing",
    ]


def test_picking_nothing_is_refused() -> None:
    assert _problems([_call("tool_a", {"first": "x"}, LISTING)], []) == [
        "steps: pick at least one call that did the work"
    ]


def test_every_number_the_record_has_is_listed() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING), _call("tool_b", {"first": "y"}, LISTING)]

    (problem,) = _problems(calls, [{"call": 5}])

    assert "the calls you can pick are 1, 2 (read_run_record" in problem


def test_a_run_with_nothing_to_pick_says_so() -> None:
    assert _problems([], [{"call": 1}]) == [
        "steps[0].call: call 1 is not in this run's record; the calls you can pick are none "
        "(read_run_record lists them)"
    ]


def test_a_for_each_source_woven_into_text_is_refused_where_it_was_written() -> None:
    calls = [_call("tool_a", {"first": "x"}, LISTING), _call("tool_b", {"first": "e1"}, LISTING)]

    assert _problems(
        calls,
        [
            {"call": 1, "id": "list"},
            {"call": 2, "for_each": "all-$steps.list.items", "vary": {"first": "$item.id"}},
        ],
    ) == [
        "steps[1]: for_each must be the whole value, either one placeholder naming a list "
        "($steps.<step_id>.<field>) or an $ask slot, but it is 'all-$steps.list.items'; a "
        "placeholder inside a longer string resolves to text, and text is not a list"
    ]


def test_a_time_slot_naming_no_time_is_refused_with_the_grammar() -> None:
    calls = [_call("tool_a", {"first": "2026-11-20"}, LISTING)]

    assert _problems(
        calls, [{"call": 1, "vary": {"first": {"$time": "$user.name", "format": "%Y-%m-%d"}}}]
    ) == [
        "steps[0].vary.first: $time takes one time placeholder ($now or $today, with an "
        "optional offset and clock such as $today + 1d 09:00), not '$user.name'"
    ]


@pytest.mark.parametrize(
    ("path", "found"),
    [
        ("people.0.email", True),
        ("people.1.email", False),
        ("people.x.email", False),
        ("first.0", False),
        ("people", True),
        ("", False),
    ],
)
def test_a_path_reads_keys_and_list_indexes_that_exist(path: str, found: bool) -> None:
    calls = [_call("tool_a", {"first": "x", "people": [{"email": "a@b.c"}]}, LISTING)]

    problems = _problems(calls, [{"call": 1, "vary": {path: "$user.email"}}])

    assert (problems == []) is found


def test_a_call_with_many_args_lists_the_first_twenty_paths() -> None:
    args: dict[str, object] = {f"arg{index:02}": "x" for index in range(25)}
    calls = [_call("tool_a", args, LISTING)]

    (problem,) = _problems(calls, [{"call": 1, "vary": {"nope": "$today"}}])

    assert problem.endswith(", ".join(f"arg{index:02}" for index in range(20)) + ", ...")


def test_a_call_with_exactly_twenty_args_lists_them_all() -> None:
    args: dict[str, object] = {f"arg{index:02}": "x" for index in range(20)}

    (problem,) = _problems(
        [_call("tool_a", args, LISTING)], [{"call": 1, "vary": {"no": "$today"}}]
    )

    assert problem.endswith(", ".join(f"arg{index:02}" for index in range(20)))


def test_a_call_with_no_args_says_it_has_no_paths() -> None:
    (problem,) = _problems([_call("tool_a", {}, LISTING)], [{"call": 1, "vary": {"x": "$today"}}])

    assert problem.endswith("its arg paths are: none")


def test_a_nested_list_is_listed_down_to_its_leaves() -> None:
    calls = [_call("tool_a", {"people": [{"email": "a"}, {"email": "b"}]}, LISTING)]

    (problem,) = _problems(calls, [{"call": 1, "vary": {"x": "$today"}}])

    assert problem.endswith("its arg paths are: people.0.email, people.1.email")


# --- the record as the author reads it --------------------------------------


def test_the_record_names_the_account_a_call_ran_as() -> None:
    calls = [_call("GMAIL_SEND", {"to": "x"}, {"id": "m"}, proxied=True, account="w@acme.com")]

    (line,) = render_record(number_record(calls, EXCLUDED))

    assert line["account"] == "w@acme.com"


def test_a_shape_goes_three_levels_deep_and_says_how_much_is_below() -> None:
    deep = {"a": {"b": {"c": {"d": 1}}, "list": [{"x": [1]}]}}

    assert result_shape(deep) == {
        "a": {"b": {"c": "object with 1 keys"}, "list": {"list of 1": "object with 1 keys"}}
    }


def test_a_wide_object_shows_its_first_fifteen_keys_and_counts_the_rest() -> None:
    wide = {f"k{index:02}": index for index in range(18)}

    shape = result_shape(wide)

    assert isinstance(shape, dict)
    assert list(shape)[:15] == [f"k{index:02}" for index in range(15)]
    assert shape["..."] == "3 more keys"
    assert len(shape) == 16


def test_an_object_of_exactly_fifteen_keys_is_shown_whole() -> None:
    shape = result_shape({f"k{index:02}": index for index in range(15)})

    assert isinstance(shape, dict)
    assert "..." not in shape


@pytest.mark.parametrize("vary", [None, "{}", '{"first": "$today"}'])
def test_vary_sent_as_null_or_as_json_text_reads_as_the_mapping_it_means(vary: object) -> None:
    """Live gpt-5.6-luna, 2026-11-03: vary: null was refused as not a dictionary."""
    calls = [_call("tool_a", _all_args(first="2026-11-20"), LISTING)]

    assert _problems(calls, [{"call": 1, "vary": vary}]) == []


def test_a_for_each_marking_a_value_without_item_is_still_refused() -> None:
    calls = [
        _call("tool_a", _all_args(), LISTING),
        _call("tool_b", _all_args(first="2026-11-20"), {"draft_id": "d1"}),
    ]

    problems = _problems(
        calls,
        [
            {"call": 1, "id": "list"},
            {"call": 2, "for_each": "$steps.list.items", "vary": {"first": "$today"}},
        ],
    )

    assert [problem.split(":")[0] for problem in problems] == ["steps[1].vary"]


def test_a_named_layout_over_a_value_with_no_date_says_it_does_not_write_it() -> None:
    calls = [_call("tool_a", _all_args(first="soon"), LISTING)]

    assert _problems(
        calls, [{"call": 1, "vary": {"first": {"$time": "$today", "format": "%Y"}}}]
    ) == [
        "steps[0].vary.first: 'first' was 'soon', which is not written in '%Y'; give the "
        "strftime layout that writes it"
    ]
