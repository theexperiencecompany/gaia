"""Re-express a hand-written write_playbook attempt as picks over its run's record.

Before picks, the model retyped each step (tool and args) and the validator
matched it back to the run. Each retyped step is matched here to the recorded
call it was written from, and only what the author meant to change per run
survives: a value holding a placeholder, an $ask or a $time. A retyped literal
that disagrees with the record is dropped, because the record holds what the
tool really took. An attempt that cannot be said as picks says why.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.core.subagents.call_record import is_error_envelope
from app.agents.tools.execute.unwrap import unwrap_execute_call
from app.models.playbook_models import TIME_KEY, AskSlot, is_ask_slot, is_time_slot
from app.services.workflow.playbook.placeholders import placeholder_tokens
from app.services.workflow.playbook.record import (
    PlaybookPick,
    RecordEntry,
    TimeValue,
    VariedValue,
)
from app.utils.json_args import decode_json_container


class Unmappable(StrEnum):
    """Why an old attempt has no picks: what the author asked for is not a call this run made."""

    #: steps missing, empty or not a list of steps.
    NO_STEPS = "no_steps"
    #: a step names a tool the run never called before the write.
    STEP_NEVER_RAN = "step_never_ran"
    #: a handoff step with no children: no call to pick.
    HANDOFF_WITHOUT_STEPS = "handoff_without_steps"
    #: for_each on a handoff over several children: one call cannot repeat a group.
    FOR_EACH_OVER_SEVERAL_CALLS = "for_each_over_several_calls"
    #: every recorded call of the step's tool failed in this run.
    ONLY_FAILED_CALLS = "only_failed_calls"
    #: the run made no pickable call at all before the write.
    EMPTY_RECORD = "empty_record"


class _OldStep(BaseModel):
    """One hand-written step as models sent it, older signatures included."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    tool: str | None = None
    args: dict[str, object] = Field(default_factory=dict)
    handoff: str | None = None
    steps: list[_OldStep] = Field(default_factory=list)
    for_each: object = None
    max_items: int | None = None


@dataclass(frozen=True, slots=True)
class _Wanted:
    """One call the attempt asked to freeze."""

    step: _OldStep
    tool: str
    args: dict[str, object]


@dataclass
class Translation:
    """The picks an attempt stands for, or why it has none, and what was left out."""

    picks: list[PlaybookPick] = field(default_factory=list)
    unmappable: Unmappable | None = None
    detail: str = ""
    #: What the attempt said that the record replaces (retyped literals).
    dropped: list[str] = field(default_factory=list)


def translate(
    attempt: Mapping[str, object], record: Sequence[RecordEntry], unpickable: frozenset[str]
) -> Translation:
    """Re-express one old write_playbook call's steps as picks over the record before it."""
    if not record:
        return Translation(unmappable=Unmappable.EMPTY_RECORD, detail="no pickable call ran")
    raw = decode_json_container(attempt.get("steps"))
    if not isinstance(raw, list) or not raw:
        return Translation(unmappable=Unmappable.NO_STEPS, detail=f"steps was {type(raw).__name__}")
    try:
        steps = [_OldStep.model_validate(decode_json_container(item)) for item in raw]
    except ValidationError as error:
        return Translation(unmappable=Unmappable.NO_STEPS, detail=str(error.errors()[0]["msg"]))

    translation = Translation()
    wanted = _flatten(steps, translation, unpickable)
    if translation.unmappable is not None:
        return translation
    if not wanted:
        return Translation(unmappable=Unmappable.NO_STEPS, detail="every step was bookkeeping")
    used: set[int] = set()
    for item in wanted:
        position = _match(item, record, used, after=max(used, default=-1))
        if position is None:
            ran = [e for e in record if e.call.tool_name == item.tool]
            reason = Unmappable.ONLY_FAILED_CALLS if ran else Unmappable.STEP_NEVER_RAN
            return Translation(unmappable=reason, detail=item.tool)
        used.add(position)
        entry = record[position]
        translation.picks.append(_pick(item, entry, translation.dropped))
    return translation


def _flatten(
    steps: Sequence[_OldStep], translation: Translation, unpickable: frozenset[str]
) -> list[_Wanted]:
    """Every call the attempt names, in order, a handoff group's children in its place."""
    wanted: list[_Wanted] = []
    for step in steps:
        if step.handoff is None:
            wanted.extend(_wanted(step, unpickable))
            continue
        children = list(step.steps)
        if not children and step.tool is not None:
            children = [step.model_copy(update={"handoff": None, "steps": []})]
        if not children:
            translation.unmappable = Unmappable.HANDOFF_WITHOUT_STEPS
            translation.detail = step.handoff
            return []
        if step.for_each is not None:
            if len(children) > 1:
                translation.unmappable = Unmappable.FOR_EACH_OVER_SEVERAL_CALLS
                translation.detail = step.handoff
                return []
            children = [
                children[0].model_copy(
                    update={"for_each": step.for_each, "max_items": step.max_items}
                )
            ]
        for child in children:
            wanted.extend(_wanted(child, unpickable))
    return wanted


def _wanted(step: _OldStep, unpickable: frozenset[str]) -> list[_Wanted]:
    if step.tool is None:
        return []
    name, args = unwrap_execute_call(step.tool, dict(step.args))
    if name in unpickable:
        return []
    return [_Wanted(step=step, tool=name, args=args)]


def _match(
    item: _Wanted, record: Sequence[RecordEntry], used: set[int], *, after: int
) -> int | None:
    """The record position of the call the step was written from: same tool, unused, succeeded.

    A call after the previous pick wins, so the steps keep the order they were
    written in; then the one whose args agree most, then the earliest.
    """
    candidates = [
        position
        for position, entry in enumerate(record)
        if entry.call.tool_name == item.tool
        and position not in used
        and not entry.call.failed
        and not is_error_envelope(entry.result)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda position: (
            position > after,
            _agreement(item.args, record[position].call.args),
            -position,
        ),
    )


def _agreement(written: Mapping[str, object], recorded: Mapping[str, object]) -> int:
    return sum(1 for key, value in written.items() if recorded.get(key) == value)


def _pick(item: _Wanted, entry: RecordEntry, dropped: list[str]) -> PlaybookPick:
    vary: dict[str, VariedValue] = {}
    for path, value in _leaves(item.args):
        recorded = _read(entry.call.args, path)
        if recorded is _MISSING:
            if _varies(value):
                dropped.append(f"{item.tool}.{path}: not an arg the call was made with")
            continue
        if value == recorded:
            continue
        varied = _as_varied(value)
        if varied is None:
            dropped.append(f"{item.tool}.{path}: retyped literal, the record's value replays")
            continue
        vary[path] = varied
    for_each = _for_each(item.step.for_each)
    return PlaybookPick(
        call=entry.call_id,
        id=item.step.id or "",
        vary=vary,
        for_each=for_each,
        max_items=item.step.max_items if for_each is not None else None,
    )


_MISSING = object()


def _leaves(value: object, prefix: str = "") -> list[tuple[str, object]]:
    """Every leaf of authored args by vary path; a slot is a leaf."""
    if isinstance(value, Mapping) and value and not is_ask_slot(value) and not is_time_slot(value):
        return [
            leaf
            for key, item in value.items()
            for leaf in _leaves(item, f"{prefix}.{key}" if prefix else str(key))
        ]
    if isinstance(value, list) and value and prefix:
        return [
            leaf for index, item in enumerate(value) for leaf in _leaves(item, f"{prefix}.{index}")
        ]
    return [(prefix, value)] if prefix else []


def _read(args: object, path: str) -> object:
    node = args
    for part in path.split("."):
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return _MISSING
    return node


def _varies(value: object) -> bool:
    return is_ask_slot(value) or is_time_slot(value) or any(placeholder_tokens(value))


def _as_varied(value: object) -> VariedValue | None:
    """The vary value an authored value stands for, or None for a literal."""
    if is_ask_slot(value):
        try:
            return AskSlot.model_validate(value)
        except ValidationError:
            return None
    if is_time_slot(value):
        placeholder = value.get(TIME_KEY)
        layout = value.get("format")
        if not isinstance(placeholder, str):
            return None
        return TimeValue.model_validate(
            {TIME_KEY: placeholder, "format": layout if isinstance(layout, str) else None}
        )
    if isinstance(value, str) and any(placeholder_tokens(value)):
        return value
    return None


def _for_each(value: object) -> str | AskSlot | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if is_ask_slot(value):
        return AskSlot.model_validate(value)
    return None
