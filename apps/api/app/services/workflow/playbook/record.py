"""The run record as an author picks from it, and the playbook built from the picks.

A playbook is built from calls this run actually made. The author names them by
the id the record shows (GMAIL_SEND_EMAIL#2: the tool, and which of its calls),
copied, never counted, and marks the values that change per run; the tool names
and every other argument come from the record, so none of them can be retyped
wrong. What is left to refuse is only what a pick itself says: an id that is not
in the record, a path that is not in the call, a value that names no placeholder,
and a rewrite that drops an action the playbook it replaces takes.
"""

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
import copy
from dataclasses import dataclass, field
import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError

from app.agents.tools.execute.unwrap import (
    ExecuteCallArgs,
    execute_call_account,
    unwrap_execute_call,
)
from app.constants.execute import EXECUTE_TOOL_NAME
from app.models.playbook_models import (
    MAX_FOR_EACH_ITEMS,
    TIME_KEY,
    AskSlot,
    ForEachStep,
    PlaybookBody,
    TimeSlot,
    ToolStep,
    is_work_call,
)
from app.models.workflow_execution_models import RecordedCall, parse_result
from app.services.workflow.playbook.parser import PlaybookIssue, RecordedResult
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN, placeholder_tokens
from app.services.workflow.playbook.time_layouts import (
    detect_layout,
    renders_inside,
    time_slot_layout,
    written_in,
)

#: Most keys a result shape lists per object, and how deep it goes.
_SHAPE_MAX_KEYS = 15
_SHAPE_MAX_DEPTH = 3
#: Longest error text a failed call shows in the record.
_FAILURE_MAX_CHARS = 200
#: Most argument paths a refusal lists back.
_MAX_LISTED_PATHS = 20

_TIME_ROOTS = frozenset({"now", "today"})

#: Joins a call id's tool name to which of that tool's calls it is: tool_a#2.
CALL_ID_SEPARATOR = "#"


@dataclass(frozen=True, slots=True)
class RecordEntry:
    """One pickable call: its id, the call as it really ran, and its parsed result."""

    call_id: str
    call: RecordedCall
    result: object


def record_entries(calls: Sequence[RecordedCall], excluded: Collection[str]) -> list[RecordEntry]:
    """Give the calls a playbook may replay their ids, seen through execute.

    An id is the tool and which of its pickable calls this is, from 1. The record
    only ever appends, so an id stays the same however far the run goes on.
    """
    made: Counter[str] = Counter()
    entries: list[RecordEntry] = []
    for call in map(_as_run, calls):
        if call.tool_name in excluded:
            continue
        made[call.tool_name] += 1
        entries.append(
            RecordEntry(
                call_id=f"{call.tool_name}{CALL_ID_SEPARATOR}{made[call.tool_name]}",
                call=call,
                result=parse_result(call.result_digest),
            )
        )
    return entries


def _as_run(call: RecordedCall) -> RecordedCall:
    """Return the call as the tool ran it: a replay records its execute steps as execute."""
    if call.tool_name != EXECUTE_TOOL_NAME:
        return call
    name, args = unwrap_execute_call(call.tool_name, call.args)
    return call.model_copy(
        update={
            "tool_name": name,
            "args": args,
            "proxied": True,
            "account": execute_call_account(call.tool_name, call.args),
        }
    )


def render_record(entries: Sequence[RecordEntry]) -> list[dict[str, object]]:
    """Return the record as the author reads it: args whole, results as their shape."""
    rendered: list[dict[str, object]] = []
    for entry in entries:
        call = entry.call
        line: dict[str, object] = {
            "call": entry.call_id,
            "tool": call.tool_name,
            "args": call.args,
        }
        if call.account:
            line["account"] = call.account
        if call.failed:
            line["failed"] = call.result_digest[:_FAILURE_MAX_CHARS]
        else:
            line["returned"] = result_shape(entry.result)
        rendered.append(line)
    return rendered


def result_shape(value: object, depth: int = 0) -> object:
    """Return a result's structure: keys, list lengths and value types, without the values."""
    if isinstance(value, Mapping):
        if depth >= _SHAPE_MAX_DEPTH:
            return f"object with {len(value)} keys"
        keys = list(value)
        shape: dict[str, object] = {
            str(key): result_shape(value[key], depth + 1) for key in keys[:_SHAPE_MAX_KEYS]
        }
        if len(keys) > _SHAPE_MAX_KEYS:
            shape["..."] = f"{len(keys) - _SHAPE_MAX_KEYS} more keys"
        return shape
    if isinstance(value, list):
        if not value:
            return "empty list"
        return {f"list of {len(value)}": result_shape(value[0], depth + 1)}
    if value is None:
        return "null"
    return type(value).__name__


class TimeValue(BaseModel):
    """A time that changes per run: a placeholder, and the layout when it cannot be read off the call."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    placeholder: str = Field(alias="$time", min_length=1)
    format: str | None = Field(
        default=None, description="strftime layout; leave out to keep the recorded value's"
    )


#: A value that changes per run: placeholder text, model-written text, or a time.
VariedValue = str | AskSlot | TimeValue

_VARY_DESCRIPTION = (
    "The values that change per run, by their path in the call's args: a key, or "
    "dotted keys and list indexes for a nested value (e.g. 'query', 'event.start', "
    "'attendees.0.email'). Each value is placeholder text ($today, $user.email, "
    "$trigger.<path>, $steps.<step_id>.<path>, $item.<path>, $last_run.<TOOL>.<path>, "
    'or prose around them), {"$time": "$today + 1d 09:00"} for a time, or '
    '{"$ask": "what to write"} for text a model writes at replay. Every value '
    "left out is replayed exactly as recorded."
)
_FOR_EACH_DESCRIPTION = (
    "Repeat this call once per element of a list, $item addressing the element. "
    "Either one placeholder naming an earlier step's list ($steps.<step_id>.<path>) "
    'or {"$ask": "which of the above to act on"}. Pick one of the calls that ran '
    "per element and mark its per-element values with $item in vary."
)


def _as_text(value: object) -> object:
    """Read a counted position as text, so it is refused with the ids rather than a type error."""
    return str(value) if isinstance(value, int) else value


class PlaybookPick(BaseModel):
    """One step of a playbook, picked from this run's record."""

    model_config = ConfigDict(extra="ignore")

    call: Annotated[str, BeforeValidator(_as_text)] = Field(
        min_length=1,
        description="The call's id, copied exactly as read_run_record shows it, e.g. "
        f"'GMAIL_FETCH_EMAILS{CALL_ID_SEPARATOR}1'",
    )
    id: str = Field(
        default="",
        description="A name later steps read this call's result by, as $steps.<id>.<path>",
    )
    vary: dict[str, VariedValue] = Field(default_factory=dict, description=_VARY_DESCRIPTION)
    for_each: str | AskSlot | None = Field(default=None, description=_FOR_EACH_DESCRIPTION)
    max_items: int | None = Field(
        default=None,
        ge=1,
        le=MAX_FOR_EACH_ITEMS,
        description=f"With for_each: the most elements it may run for (default {MAX_FOR_EACH_ITEMS})",
    )


@dataclass
class BuiltPlaybook:
    """A body built from picks, the call each tool step came from, and what was refused."""

    body: PlaybookBody | None
    sources: list[RecordedResult] = field(default_factory=list)
    issues: list[PlaybookIssue] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Placed:
    """A pick matched to its record entry, with where the author wrote it."""

    where: str
    pick: PlaybookPick
    entry: RecordEntry


def build_playbook(
    description: str,
    picks: Sequence[PlaybookPick],
    result_brief: str,
    record: Sequence[RecordEntry],
    *,
    replaces: Sequence[ToolStep | ForEachStep] = (),
) -> BuiltPlaybook:
    """Build the playbook body from picks, in the order the run made the calls.

    A call that ran through execute is replayed through it, as the same account.
    replaces is the stored playbook's steps: every action it takes must survive.
    """
    built = BuiltPlaybook(body=None)
    placed = _place(picks, record, built.issues)
    steps: list[ToolStep | ForEachStep] = []
    for item in placed:
        step = _build_step(item, built.issues)
        if step is None:
            continue
        built.sources.append(RecordedResult(args=item.entry.call.args, result=item.entry.result))
        steps.append(step)
    if not built.issues:
        built.issues.extend(_dropped_actions(replaces, steps))
    if built.issues:
        return built
    if not steps:
        built.issues.append(
            PlaybookIssue(where="steps", problem="pick at least one call that did the work")
        )
        return built
    built.body = PlaybookBody(description=description, steps=steps, result_brief=result_brief)
    return built


def _place(
    picks: Sequence[PlaybookPick], record: Sequence[RecordEntry], issues: list[PlaybookIssue]
) -> list[_Placed]:
    """Match each pick to its call, then order them as the run made the calls."""
    order = {entry.call_id: position for position, entry in enumerate(record)}
    placed: list[_Placed] = []
    seen_calls: set[str] = set()
    seen_ids: set[str] = set()
    for index, pick in enumerate(picks):
        where = f"steps[{index}]"
        if pick.call not in order:
            issues.append(
                PlaybookIssue(where=f"{where}.call", problem=_unknown_call(pick.call, record))
            )
            continue
        entry = record[order[pick.call]]
        if pick.call in seen_calls:
            issues.append(
                PlaybookIssue(
                    where=f"{where}.call",
                    problem=f"{pick.call} is picked twice; one recorded call is one "
                    "step, so pick it once",
                )
            )
            continue
        step_id = pick.id or _default_id(pick.call)
        if step_id in seen_ids:
            issues.append(
                PlaybookIssue(
                    where=f"{where}.id",
                    problem=f"id {step_id!r} is already used by another step; give each "
                    "step its own",
                )
            )
            continue
        seen_calls.add(pick.call)
        seen_ids.add(step_id)
        named = pick if pick.id else pick.model_copy(update={"id": step_id})
        placed.append(_Placed(where=where, pick=named, entry=entry))
    return sorted(placed, key=lambda item: order[item.entry.call_id])


def _unknown_call(named: str, record: Sequence[RecordEntry]) -> str:
    """Say a pick names no recorded call, and list every id it could have named."""
    ids = ", ".join(entry.call_id for entry in record)
    counted = " A call is named by its id, never by its position." if named.isdigit() else ""
    if not ids:
        return f"{named!r} is not in this run's record, which has no call a playbook can replay."
    return (
        f"{named!r} is not in this run's record.{counted} Copy an id exactly as "
        f"read_run_record shows it: {ids}"
    )


def _default_id(call_id: str) -> str:
    """Spell the call id as a step id $steps can address: its separator as an underscore."""
    return call_id.replace(CALL_ID_SEPARATOR, "_")


def _dropped_actions(
    replaces: Sequence[ToolStep | ForEachStep], steps: Sequence[ToolStep | ForEachStep]
) -> list[PlaybookIssue]:
    """Refuse a rewrite that silently stops an action the stored playbook takes for the user."""
    kept = {_step_tool(step) for step in steps}
    return [
        PlaybookIssue(
            where="steps",
            problem=f"the playbook this replaces calls {tool} (step {step.label}), which acts "
            "for the user, and no step here does. Pick that call from read_run_record; if "
            "this run has not made it, make it first. If the workflow should no longer do "
            "it, call disable_playbook instead of dropping it",
        )
        for step in replaces
        if is_work_call(tool := _step_tool(step)) and tool not in kept
    ]


def _step_tool(step: ToolStep | ForEachStep) -> str:
    """Return the tool a step really calls, seen through execute."""
    return unwrap_execute_call(step.tool, step.args)[0]


def _build_step(item: _Placed, issues: list[PlaybookIssue]) -> ToolStep | ForEachStep | None:
    """Return the step one pick stands for, or None with the reasons in issues."""
    pick, call = item.pick, item.entry.call
    if call.failed:
        issues.append(
            PlaybookIssue(
                where=f"{item.where}.call",
                problem=f"{pick.call} failed in this run "
                f"({call.result_digest[:_FAILURE_MAX_CHARS]}); pick the call that succeeded",
            )
        )
        return None
    args = copy.deepcopy(call.args)
    before = len(issues)
    for path, value in pick.vary.items():
        _vary(args, path, value, f"{item.where}.vary.{path}", call, issues)
    if pick.for_each is not None and not _reads_item(pick.vary):
        issues.append(
            PlaybookIssue(
                where=f"{item.where}.vary",
                problem="a for_each step runs its call once per element, so mark the value "
                'that changes per element with $item, e.g. vary: {"<arg>": "$item.id"}; '
                "otherwise every element repeats the recorded call",
            )
        )
    if len(issues) > before:
        return None
    tool, step_args = _addressed(call, args)
    try:
        if pick.for_each is None:
            return ToolStep(id=pick.id, tool=tool, args=step_args)
        return ForEachStep(
            id=pick.id,
            tool=tool,
            args=step_args,
            for_each=pick.for_each,
            max_items=pick.max_items or MAX_FOR_EACH_ITEMS,
        )
    except ValidationError as error:
        issues.append(PlaybookIssue(where=item.where, problem=_first_message(error)))
        return None


def _addressed(call: RecordedCall, args: dict[str, object]) -> tuple[str, dict[str, object]]:
    """Return the tool a step names and its args: a call that ran through execute replays through it."""
    if not call.proxied:
        return call.tool_name, args
    proxied: ExecuteCallArgs = {
        "task_description": call.tool_name,
        "tool_name": call.tool_name,
        "data": args,
    }
    if call.account:
        proxied["account"] = call.account
    return EXECUTE_TOOL_NAME, dict(proxied)


def _reads_item(vary: Mapping[str, VariedValue]) -> bool:
    return any(
        match.group("root") == "item"
        for value in vary.values()
        if isinstance(value, str)
        for match in placeholder_tokens(value)
    )


def _vary(
    args: dict[str, object],
    path: str,
    value: VariedValue,
    where: str,
    call: RecordedCall,
    issues: list[PlaybookIssue],
) -> None:
    """Replace the recorded value at path with what changes per run."""
    located = _locate(args, path)
    if located is None:
        paths = _arg_paths(call.args)
        listed = ", ".join(paths[:_MAX_LISTED_PATHS]) + (
            ", ..." if len(paths) > _MAX_LISTED_PATHS else ""
        )
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{call.tool_name} was called with no value at {path!r}; its arg "
                f"paths are: {listed or 'none'}",
            )
        )
        return
    stored = _stored_value(value, located.read(), path, issues, where)
    if stored is not None:
        located.write(stored)


def _stored_value(
    value: VariedValue, example: object, path: str, issues: list[PlaybookIssue], where: str
) -> object | None:
    """Return what the step stores for one varied value, or None with the reason in issues."""
    if isinstance(value, AskSlot):
        return value.model_dump(exclude_defaults=True)
    if isinstance(value, TimeValue):
        return _time_slot(value, example, path, issues, where)
    tokens = list(placeholder_tokens(value))
    if not tokens:
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{value!r} holds no placeholder, so it does not change per run; "
                f"leave {path!r} out to replay the recorded {example!r}, or write one "
                "($today, $steps.<step_id>.<path>, $item.<path>, ...)",
            )
        )
        return None
    times = [token for token in tokens if token.group("root") in _TIME_ROOTS]
    if not times:
        return value
    whole = PLACEHOLDER_TOKEN.fullmatch(value)
    if whole is not None:
        layout = time_slot_layout(whole, example)
        if layout is None:
            return value
        return _time_slot_value(whole.group(0), layout)
    if all(renders_inside(token, example) for token in times):
        return value
    issues.append(
        PlaybookIssue(
            where=where,
            problem=f"{path!r} was {example!r}; a time inside other text renders as ISO 8601, "
            f'not that layout. Write the whole value as {{"$time": "{times[0].group(0)}"}}',
        )
    )
    return None


def _time_slot(
    value: TimeValue, example: object, path: str, issues: list[PlaybookIssue], where: str
) -> object | None:
    if value.format is not None and not (
        isinstance(example, str) and written_in(example, value.format)
    ):
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{path!r} was {example!r}, which is not written in {value.format!r}; "
                "leave format out to keep the recorded layout",
            )
        )
        return None
    # A layout the author names wins: 03/11/2026 reads as March or November.
    chosen = value.format or detect_layout(example)
    if chosen is None:
        issues.append(
            PlaybookIssue(
                where=where,
                problem=f"{path!r} was {example!r}, which reads as no date layout; give the "
                'strftime layout the tool takes as "format"',
            )
        )
        return None
    try:
        return _time_slot_value(value.placeholder, chosen)
    except ValidationError as error:
        issues.append(PlaybookIssue(where=where, problem=_first_message(error)))
        return None


def _time_slot_value(placeholder: str, layout: str) -> dict[str, object]:
    return TimeSlot.model_validate({TIME_KEY: placeholder, "format": layout}).model_dump()


_INDEX = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class _ArgSlot:
    """Where one value sits inside a call's args: its container and its key there (an index for a list)."""

    container: dict[str, object] | list[object]
    key: str

    def read(self) -> object:
        if isinstance(self.container, dict):
            return self.container[self.key]
        return self.container[int(self.key)]

    def write(self, value: object) -> None:
        if isinstance(self.container, dict):
            self.container[self.key] = value
        else:
            self.container[int(self.key)] = value


def _locate(args: dict[str, object], path: str) -> _ArgSlot | None:
    """Return where path's value sits in args, or None when the call has no such value."""
    *parents, last = path.split(".")
    node: object = args
    for part in parents:
        slot = _slot_in(node, part)
        if slot is None:
            return None
        node = slot.read()
    return _slot_in(node, last)


def _slot_in(node: object, part: str) -> _ArgSlot | None:
    """Return the slot part names in node: a key of a mapping, or an index within a list."""
    if isinstance(node, dict):
        return _ArgSlot(container=node, key=part) if part in node else None
    if isinstance(node, list) and _INDEX.fullmatch(part) and int(part) < len(node):
        return _ArgSlot(container=node, key=part)
    return None


def _arg_paths(value: object, prefix: str = "") -> list[str]:
    """Every leaf path in a call's args, as a vary key spells it."""
    if isinstance(value, Mapping) and value:
        return [
            path
            for key, item in value.items()
            for path in _arg_paths(item, f"{prefix}.{key}" if prefix else str(key))
        ]
    if isinstance(value, list) and value:
        return [
            path
            for index, item in enumerate(value)
            # A list is never the root: a call's args are a mapping.
            for path in _arg_paths(item, f"{prefix}.{index}")
        ]
    return [prefix] if prefix else []


class _ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    msg: str


def _first_message(error: ValidationError) -> str:
    return _ErrorDetail.model_validate(error.errors()[0]).msg.removeprefix("Value error, ")
