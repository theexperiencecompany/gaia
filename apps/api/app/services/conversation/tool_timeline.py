"""The ordered tool timeline an item's folded cards show: tool calls, subagent groups and reasoning.

Pure: the same cards always give the same timeline, so a running item and its reload show the
same rows under the same keys. Clients render it as given.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import copy
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import JsonValue

from app.constants.chat import (
    BROWSER_GROUP_PREFIX,
    BROWSER_TASK_TOOL_NAME,
    GROUPED_TOOL_CARDS,
    SUBAGENT_GROUP_TOOL_NAME,
)
from app.services.conversation.tool_cards import TOOL_CALLS_CARD
from shared.py.conversation_wire import (
    TimelineCard,
    TimelineStep,
    TimelineStepKind,
    ToolDataEntry,
    ToolProgress,
    ToolTimeline,
)

_Json = dict[str, JsonValue]
_T = TypeVar("_T")
_HANDOFF = "handoff"
_SPAWNED = "spawned"
_SPAWN_TOOL = "spawn_subagent"
_SYNTHETIC = "synthetic"
#: A synthetic group never ran, so its duration and token count were never measured.
_UNMEASURED = None


@dataclass
class _Buckets:
    calls: list[_Json] = field(default_factory=list)
    groups: list[_Json] = field(default_factory=list)
    grouped: dict[str, list[JsonValue]] = field(default_factory=dict)
    single: list[ToolDataEntry] = field(default_factory=list)


def tool_timeline(cards: Sequence[ToolDataEntry]) -> ToolTimeline:
    """Return the thread rows and the stand-alone cards the cards show, each keyed stably."""
    buckets = _bucket(cards)
    if buckets.groups:
        steps = _backend_steps(buckets.calls, buckets.groups)
    else:
        steps = _synthetic_steps(buckets.calls)
    steps = _coalesced_steps(steps)
    shown: list[ToolDataEntry] = [
        {"tool_name": name, "tool_category": "", "data": data, "timestamp": None}
        for name, data in buckets.grouped.items()
    ]
    shown.extend(buckets.single)
    step_keys = _stable_keys(steps, _step_key)
    card_keys = _stable_keys(shown, _card_key)
    return ToolTimeline(
        steps=tuple(
            TimelineStep(kind=kind, key=key, data=_keyed(kind, data))
            for (kind, data), key in zip(steps, step_keys, strict=True)
        ),
        cards=tuple(
            TimelineCard(key=key, card=card) for card, key in zip(shown, card_keys, strict=True)
        ),
        progress=_progress(cards),
    )


def _progress(cards: Sequence[ToolDataEntry]) -> ToolProgress | None:
    """Return the newest tool call's line: the last tool-call card that names one."""
    for card in reversed(cards):
        data = card["data"]
        if card["tool_name"] != TOOL_CALLS_CARD or not isinstance(data, dict):
            continue
        message = _text(data.get("message"))
        if not message:
            continue
        integration, icon = data.get("integration_name"), data.get("icon_url")
        return ToolProgress(
            message=message,
            tool_name=_text(data.get("tool_name")),
            tool_category=_text(data.get("tool_category")),
            integration_name=integration if isinstance(integration, str) else None,
            icon_url=icon if isinstance(icon, str) else None,
            show_category=data.get("show_category") is not False,
        )
    return None


def _bucket(cards: Sequence[ToolDataEntry]) -> _Buckets:
    buckets = _Buckets()
    for card in cards:
        name, data = card["tool_name"], card["data"]
        if name == TOOL_CALLS_CARD:
            calls = data if isinstance(data, list) else [data]
            buckets.calls.extend(copy.deepcopy(call) for call in calls if isinstance(call, dict))
        elif name == SUBAGENT_GROUP_TOOL_NAME and isinstance(data, dict):
            buckets.groups.append(copy.deepcopy(data))
        elif name in GROUPED_TOOL_CARDS:
            buckets.grouped.setdefault(name, []).append(data)
        else:
            buckets.single.append(card)
    return buckets


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _dicts(value: JsonValue) -> list[_Json]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _is_reasoning(call: _Json) -> bool:
    return isinstance(call.get("reasoning"), str)


def _coalesced(calls: list[_Json]) -> list[_Json]:
    """Merge adjacent thinking steps into one, as a nested call dropping out of a level splits them."""
    out: list[_Json] = []
    for call in calls:
        if out and _is_reasoning(call) and _is_reasoning(out[-1]):
            out[-1] = {
                **out[-1],
                "reasoning": _text(out[-1]["reasoning"]) + _text(call["reasoning"]),
            }
            continue
        out.append(call)
    return out


def _enriched(group: _Json) -> _Json:
    group["tool_calls"] = list(_coalesced(_dicts(group.get("tool_calls"))))
    group["nested_subagents"] = [
        _enriched(nested) for nested in _dicts(group.get("nested_subagents"))
    ]
    return group


def _all_groups(groups: list[_Json]) -> list[_Json]:
    every: list[_Json] = []
    for group in groups:
        every.append(group)
        every.extend(_all_groups(_dicts(group.get("nested_subagents"))))
    return every


def _call_ids(groups: list[_Json]) -> set[str]:
    return {
        call_id
        for group in _all_groups(groups)
        for call in _dicts(group.get("tool_calls"))
        if (call_id := _text(call.get("tool_call_id")))
    }


def _nest_root_spawned(groups: list[_Json]) -> list[_Json]:
    """Nest each root spawned group in the next handoff that spawned one; older logs lack parent ids."""
    spawned = [group for group in groups if group.get("agent_type") == _SPAWNED]
    taken = 0
    nested: set[str] = set()
    for group in groups:
        if group.get("agent_type") != _HANDOFF:
            continue
        spawns = any(
            call.get("tool_name") == _SPAWN_TOOL for call in _dicts(group.get("tool_calls"))
        )
        if spawns and taken < len(spawned):
            inner = _dicts(group.get("nested_subagents"))
            group["nested_subagents"] = [*inner, spawned[taken]]
            taken += 1
        nested |= {
            _text(inner.get("subagent_id")) for inner in _dicts(group.get("nested_subagents"))
        }
    return [group for group in groups if _text(group.get("subagent_id")) not in nested]


def _task_of(call: _Json) -> str:
    inputs = call.get("inputs")
    return _text(inputs.get("task")) if isinstance(inputs, dict) else ""


def _attach(group: _Json, call: _Json) -> None:
    if task := _task_of(call):
        group["handoff_input"] = task
    if output := _text(call.get("output")):
        group["handoff_output"] = output


def _is_handoff(call: _Json) -> bool:
    message = _text(call.get("message")).lower()
    return call.get("tool_name") == _HANDOFF or message.startswith("handing off to")


def _is_spawn(call: _Json) -> bool:
    message = _text(call.get("message")).lower()
    return call.get("tool_name") == _SPAWN_TOOL or message == "spawning subagent"


_Step = tuple[TimelineStepKind, _Json]


@dataclass
class _Matcher:
    every: list[_Json]
    spawned: list[_Json]
    taken: int = 0
    emitted: set[str] = field(default_factory=set)

    def browser(self, call: _Json) -> _Json | None:
        call_id = _text(call.get("tool_call_id"))
        wanted = f"{BROWSER_GROUP_PREFIX}{call_id}"
        return next(
            (
                g
                for g in self.every
                if call_id and g.get("subagent_id") == wanted and wanted not in self.emitted
            ),
            None,
        )

    def opened_by(self, call: _Json) -> _Json | None:
        if _is_handoff(call):
            message = _text(call.get("message")).lower()
            return next(
                (
                    g
                    for g in self.every
                    if g.get("agent_type") == _HANDOFF
                    and _text(g.get("subagent_name")).lower() in message
                ),
                None,
            )
        if self.taken < len(self.spawned):
            self.taken += 1
            return self.spawned[self.taken - 1]
        return None


def _backend_steps(calls: list[_Json], raw_groups: list[_Json]) -> list[_Step]:
    """Interleave the streamed groups at the call that opened each; that call is consumed."""
    grouped_calls = _call_ids(raw_groups)
    roots = _nest_root_spawned([_enriched(group) for group in raw_groups])
    every = _all_groups(roots)
    match = _Matcher(every=every, spawned=[g for g in every if g.get("agent_type") == _SPAWNED])
    steps: list[_Step] = []

    def emit(group: _Json) -> None:
        group_id = _text(group.get("subagent_id"))
        if group_id not in match.emitted:
            steps.append((TimelineStepKind.SUBAGENT, group))
            match.emitted.add(group_id)

    for call in calls:
        if _text(call.get("tool_call_id")) in grouped_calls:
            continue
        if call.get("tool_name") == BROWSER_TASK_TOOL_NAME and (browser := match.browser(call)):
            _attach(browser, call)
            emit(browser)
            continue
        if _is_handoff(call) or _is_spawn(call):
            if (opened := match.opened_by(call)) is not None:
                _attach(opened, call)
                emit(opened)
            continue
        steps.append((TimelineStepKind.TOOL, call))
    # A group whose opening call never arrived still shows, after everything else.
    for group in roots:
        emit(group)
    return steps


def _synthetic_group(call: _Json, index: int, *, handoff: bool) -> _Json:
    inputs = call.get("inputs")
    subagent = _text(inputs.get("subagent_id")) if isinstance(inputs, dict) else ""
    named = _text(call.get("message"))
    prefix = "handing off to "
    group: _Json = {
        "subagent_id": _text(call.get("tool_call_id"))
        or f"synth-{'' if handoff else 'spawn-'}{index}",
        "subagent_name": (named[len(prefix) :] if named.lower().startswith(prefix) else "Subagent")
        if handoff
        else "Task Agent",
        "agent_type": _HANDOFF if handoff else _SPAWNED,
        "tool_calls": [],
        "duration_ms": _UNMEASURED,
        "token_count": _UNMEASURED,
        "started_at": "",
        "completed_at": _SYNTHETIC,
        "icon_url": None,
        "tool_category": (subagent.removeprefix("subagent:").removesuffix("_agent") or None)
        if handoff
        else _SPAWN_TOOL,
        "nested_subagents": [],
    }
    _attach(group, call)
    return group


def _synthetic_steps(calls: list[_Json]) -> list[_Step]:
    """Build groups from the calls alone, for logs written before subagent groups streamed."""
    steps: list[_Step] = []
    current: _Json | None = None
    made = 0
    for call in calls:
        if _is_handoff(call):
            current = _synthetic_group(call, made, handoff=True)
            made += 1
            steps.append((TimelineStepKind.SUBAGENT, current))
            # A hand-off that failed at once already has its output: later calls are not in it.
            if "handoff_output" in current:
                current = None
        elif _is_spawn(call):
            spawned = _synthetic_group(call, made, handoff=False)
            made += 1
            if current is None:
                steps.append((TimelineStepKind.SUBAGENT, spawned))
            else:
                current["nested_subagents"] = [*_dicts(current["nested_subagents"]), spawned]
        elif current is not None:
            current["tool_calls"] = [*_dicts(current["tool_calls"]), call]
        else:
            steps.append((TimelineStepKind.TOOL, call))
    return [
        (kind, _enriched(data) if kind is TimelineStepKind.SUBAGENT else data)
        for kind, data in steps
    ]


def _coalesced_steps(steps: list[_Step]) -> list[_Step]:
    out: list[_Step] = []
    for kind, data in steps:
        if out and kind is TimelineStepKind.TOOL and out[-1][0] is TimelineStepKind.TOOL:
            previous = out[-1][1]
            if _is_reasoning(data) and _is_reasoning(previous):
                merged = _text(previous["reasoning"]) + _text(data["reasoning"])
                out[-1] = (kind, {**previous, "reasoning": merged})
                continue
        out.append((kind, data))
    return out


def _stable_keys(items: Sequence[_T], key_of: Callable[[_T], str | None]) -> list[str]:
    """Key each item by its stream-stable id, else by a slot after the nearest identified one."""
    keys: list[str] = []
    anchor, unanchored = "head", 0
    for item in items:
        key = key_of(item)
        if key is None:
            keys.append(f"{anchor}#{unanchored}")
            unanchored += 1
        else:
            anchor, unanchored = key, 0
            keys.append(key)
    return keys


def _step_key(step: _Step) -> str | None:
    kind, data = step
    if kind is TimelineStepKind.SUBAGENT:
        return f"sa-{_text(data.get('subagent_id'))}"
    call_id = _text(data.get("tool_call_id"))
    return f"tc-{call_id}" if call_id else None


def _card_key(card: ToolDataEntry) -> str | None:
    name = card["tool_name"]
    if name in GROUPED_TOOL_CARDS:
        return f"grouped-{name}"
    data = card["data"]
    call_id = _text(data.get("tool_call_id")) if isinstance(data, dict) else ""
    if call_id:
        return f"{name}-{call_id}"
    stamp = card.get("timestamp")
    return f"{name}-{stamp}" if stamp else None


def _with_step_keys(group: _Json) -> _Json:
    """Key the group's calls within it, and its nested groups' the same way."""
    scope = _text(group.get("subagent_id"))
    calls = _dicts(group.get("tool_calls"))
    group["step_keys"] = list(
        _stable_keys(
            calls,
            lambda call: f"{scope}-tc-{i}" if (i := _text(call.get("tool_call_id"))) else None,
        )
    )
    group["nested_subagents"] = [
        _with_step_keys(nested) for nested in _dicts(group.get("nested_subagents"))
    ]
    return group


def _keyed(kind: TimelineStepKind, data: _Json) -> _Json:
    return _with_step_keys(data) if kind is TimelineStepKind.SUBAGENT else data
