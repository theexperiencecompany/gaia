"""The run record as an author picks from it, and the playbook built from the picks.

A playbook is built from calls this run actually made. The author names them by
number and marks the values that change per run; the tool names and every other
argument come from the record, so none of them can be retyped wrong. What is left to refuse is only what a pick itself says:
a number that is not in the record, a path that is not in the call, a value
that names no placeholder.
"""

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
    PlaybookRefusal,
    TimeSlot,
    ToolStep,
)
from app.models.workflow_execution_models import RecordedCall, parse_result
from app.services.workflow.playbook.parser import PlaybookIssue, RecordedResult
from app.services.workflow.playbook.placeholders import PLACEHOLDER_TOKEN, placeholder_tokens
from app.services.workflow.playbook.time_layouts import (
    renders_inside,
    slot_layout,
    time_slot_layout,
)
from app.utils.json_args import decode_json_container

#: Most keys a result shape lists per object, and how deep it goes.
_SHAPE_MAX_KEYS = 15
_SHAPE_MAX_DEPTH = 3
#: Longest error text a failed call shows in the record.
_FAILURE_MAX_CHARS = 200
#: Most argument paths a refusal lists back.
_MAX_LISTED_PATHS = 20

_TIME_ROOTS = frozenset({"now", "today"})


@dataclass(frozen=True, slots=True)
class RecordEntry:
    """One pickable call: its number, the call as it really ran, and its parsed result."""

    number: int
    call: RecordedCall
    result: object


def number_record(calls: Sequence[RecordedCall], excluded: Collection[str]) -> list[RecordEntry]:
    """Give the calls a playbook may replay their numbers from 1, seen through execute.

    Excluded calls take no number. The record only ever appends, so a number
    stays the same however far the run goes on.
    """
    pickable = [real for real in map(_as_run, calls) if real.tool_name not in excluded]
    return [
        RecordEntry(number=number, call=call, result=parse_result(call.result_digest))
        for number, call in enumerate(pickable, start=1)
    ]


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
            "call": entry.number,
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


def _vary_mapping(value: object) -> object:
    return {} if value is None else decode_json_container(value)


class PlaybookPick(BaseModel):
    """One step of a playbook, picked from this run's record."""

    model_config = ConfigDict(extra="ignore")

    call: int = Field(ge=1, description="The call's number in read_run_record")
    id: str = Field(
        default="",
        description="A name later steps read this call's result by, as $steps.<id>.<path>",
    )
    # Models send "no values vary" as null and the mapping as JSON text; both mean the mapping.
    vary: Annotated[dict[str, VariedValue], BeforeValidator(_vary_mapping)] = Field(
        default_factory=dict, description=_VARY_DESCRIPTION
    )
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
) -> BuiltPlaybook:
    """Build the playbook body from picks, in the order the run made the calls.

    A call that ran through execute is replayed through it, as the same account.
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
    if built.issues:
        return built
    if not steps:
        built.issues.append(
            PlaybookIssue(
                kind=PlaybookRefusal.NO_STEPS,
                where="steps",
                problem="pick at least one call that did the work",
            )
        )
        return built
    built.body = PlaybookBody(description=description, steps=steps, result_brief=result_brief)
    return built


def _place(
    picks: Sequence[PlaybookPick], record: Sequence[RecordEntry], issues: list[PlaybookIssue]
) -> list[_Placed]:
    """Match each pick to its call, then order them as the run made the calls."""
    by_number = {entry.number: entry for entry in record}
    numbers = ", ".join(str(entry.number) for entry in record) or "none"
    placed: list[_Placed] = []
    seen_calls: set[int] = set()
    seen_ids: set[str] = set()
    for index, pick in enumerate(picks):
        where = f"steps[{index}]"
        entry = by_number.get(pick.call)
        if entry is None:
            issues.append(
                PlaybookIssue(
                    kind=PlaybookRefusal.NOT_IN_RECORD,
                    where=f"{where}.call",
                    problem=f"call {pick.call} is not in this run's record; the calls you "
                    f"can pick are {numbers} (read_run_record lists them)",
                )
            )
            continue
        if pick.call in seen_calls:
            issues.append(
                PlaybookIssue(
                    kind=PlaybookRefusal.PICKED_TWICE,
                    where=f"{where}.call",
                    problem=f"call {pick.call} is picked twice; one recorded call is one "
                    "step, so pick it once",
                )
            )
            continue
        step_id = pick.id or _default_id(pick.call)
        if step_id in seen_ids:
            issues.append(
                PlaybookIssue(
                    kind=PlaybookRefusal.DUPLICATE_ID,
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
    return sorted(placed, key=lambda item: item.entry.number)


def _default_id(number: int) -> str:
    return f"call{number}"


def _build_step(item: _Placed, issues: list[PlaybookIssue]) -> ToolStep | ForEachStep | None:
    """Return the step one pick stands for, or None with the reasons in issues."""
    pick, call = item.pick, item.entry.call
    if call.failed:
        issues.append(
            PlaybookIssue(
                kind=PlaybookRefusal.FAILED_CALL,
                where=f"{item.where}.call",
                problem=f"call {pick.call} ({call.tool_name}) failed in this run "
                f"({call.result_digest[:_FAILURE_MAX_CHARS]}); pick the call that succeeded",
            )
        )
        return None
    args = copy.deepcopy(call.args)
    before = len(issues)
    for path, value in pick.vary.items():
        _vary(args, path, value, f"{item.where}.vary.{path}", call, issues)
    if pick.for_each is not None and not _varies_per_element(pick.vary):
        issues.append(
            PlaybookIssue(
                kind=PlaybookRefusal.FOR_EACH_UNMARKED,
                where=f"{item.where}.vary",
                problem="a for_each step runs its call once per element, so mark the value "
                'that changes per element with $item (vary: {"<arg>": "$item.id"}) or with '
                'text written per element (vary: {"<arg>": {"$ask": "..."}}); otherwise every '
                "element repeats the recorded call",
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
        issues.append(
            PlaybookIssue(
                kind=PlaybookRefusal.FOR_EACH_SOURCE,
                where=item.where,
                problem=_first_message(error),
            )
        )
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


def _varies_per_element(vary: Mapping[str, VariedValue]) -> bool:
    """Whether a for_each call changes per element: an $item value, or text a model writes for each."""
    return any(
        isinstance(value, AskSlot)
        or (
            isinstance(value, str)
            and any(match.group("root") == "item" for match in placeholder_tokens(value))
        )
        for value in vary.values()
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
                kind=PlaybookRefusal.NO_SUCH_ARG,
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
                kind=PlaybookRefusal.NO_PLACEHOLDER,
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
            kind=PlaybookRefusal.TIME_LAYOUT,
            where=where,
            problem=f"{path!r} was {example!r}; a time inside other text renders as ISO 8601, "
            f'not that layout. Write the whole value as {{"$time": "{times[0].group(0)}"}}',
        )
    )
    return None


def _time_slot(
    value: TimeValue, example: object, path: str, issues: list[PlaybookIssue], where: str
) -> object | None:
    """Return the slot a varied time stores, in the layout the recorded value is written in.

    A layout the author names wins when it writes the recorded value back
    (03/11/2026 reads as March or November); otherwise the record's own layout does.
    """
    named = value.format
    chosen = slot_layout(example, named)
    if chosen is None:
        problem = (
            f"{path!r} was {example!r}, which is not written in {named!r}; give the "
            "strftime layout that writes it"
            if named is not None
            else f"{path!r} was {example!r}, which reads as no date layout; give the "
            'strftime layout the tool takes as "format"'
        )
        issues.append(PlaybookIssue(kind=PlaybookRefusal.TIME_LAYOUT, where=where, problem=problem))
        return None
    try:
        return _time_slot_value(value.placeholder, chosen)
    except ValidationError as error:
        issues.append(
            PlaybookIssue(
                kind=PlaybookRefusal.TIME_EXPRESSION, where=where, problem=_first_message(error)
            )
        )
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
