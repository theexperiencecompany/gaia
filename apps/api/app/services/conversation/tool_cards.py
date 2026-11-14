"""The one fold of a run's stream payloads into the tool cards and image a client shows.

Pure: the same payloads always fold to the same cards. A comms reply, finished work, a
running work item on the screen and a replayed workflow playbook all fold through it, so a
card looks the same live, settled and reloaded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import cast

from pydantic import BaseModel, ConfigDict

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.conversation_frame_models import (
    ImageEvent,
    ReasoningEvent,
    StreamPayload,
    SubagentEndEvent,
    SubagentStartEvent,
    TodoProgressEvent,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.stream_events import SubagentEndPayload, SubagentStartPayload, ToolOutputPayload
from shared.py.conversation_wire import ImageData, ToolDataEntry

TOOL_CALLS_CARD = "tool_calls_data"
TODO_PROGRESS_CARD = "todo_progress"
MCP_APP_CARD = "mcp_app"
#: tool_name and tool_category of a thinking step riding the tool-call channel.
REASONING_STEP = "reasoning"
_DEFAULT_TODO_SOURCE = "executor"

_Json = dict[str, object]
_Group = dict[str, object]


class _CardRefs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_call_id: str | None = None
    approval_id: str | None = None


class _TodoSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str | None = None


@dataclass(frozen=True)
class _SubagentGroup:
    """A subagent_group card's data as its start opens it; its end fills duration, tokens and completion."""

    subagent_id: str
    subagent: str | None
    subagent_name: str
    agent_type: str
    started_at: str
    icon_url: str | None
    tool_category: str | None
    tool_calls: list[object] = field(default_factory=list)
    duration_ms: int | None = None
    token_count: int | None = None
    completed_at: str | None = None
    nested_subagents: list[object] = field(default_factory=list)


@dataclass(frozen=True)
class FoldedCards:
    """What a run's payloads show besides its words: the cards in order, and the image it made."""

    tool_data: tuple[ToolDataEntry, ...] = ()
    image: ImageData | None = None


def fold_cards(
    payloads: Iterable[StreamPayload], seed: Sequence[ToolDataEntry] = ()
) -> FoldedCards:
    """Fold payloads onto the seed cards; payloads that carry no card (text, follow-ups) change nothing."""
    cards = [_copy(card) for card in seed]
    image: ImageData | None = None
    for payload in payloads:
        match payload:
            case ToolDataEvent(tool_data=card):
                _take_card(cards, _copy(card))
            case ToolOutputEvent(tool_output=output):
                _take_output(cards, output)
            case ReasoningEvent(reasoning=reasoning) if reasoning.content:
                _take_reasoning(cards, reasoning.content, reasoning.subagent_id)
            case SubagentStartEvent(subagent_start=start):
                _take_start(cards, start)
            case SubagentEndEvent(subagent_end=end):
                _update_group(cards, end.subagent_id, lambda group: _ended(group, end))
            case TodoProgressEvent(todo_progress=snapshot):
                _take_todo_progress(cards, snapshot)
            case ImageEvent(image_data=made):
                image = made
    return FoldedCards(tool_data=tuple(cards), image=image)


def _copy(card: ToolDataEntry) -> ToolDataEntry:
    data = card["data"]
    return cast(ToolDataEntry, {**card, "data": dict(data) if isinstance(data, dict) else data})


def _refs(card: ToolDataEntry) -> _CardRefs:
    data = card["data"]
    return _CardRefs.model_validate(data) if isinstance(data, dict) else _CardRefs()


def _approval_id(card: ToolDataEntry) -> str | None:
    return _refs(card).approval_id if card["tool_name"] == APPROVAL_REQUEST_TOOL_NAME else None


def _take_card(cards: list[ToolDataEntry], card: ToolDataEntry) -> None:
    """Route a subagent's call into its group; an approval's later frame replaces its earlier one in place."""
    subagent_id = card.get("subagent_id")
    if subagent_id and card["tool_name"] == TOOL_CALLS_CARD:
        _update_group(
            cards,
            subagent_id,
            lambda group: {**group, "tool_calls": [*_calls(group), card["data"]]},
        )
        return
    approval_id = _approval_id(card)
    if approval_id is not None:
        for index, held in enumerate(cards):
            if _approval_id(held) == approval_id:
                cards[index] = card
                return
    cards.append(card)


def _take_output(cards: list[ToolDataEntry], output: ToolOutputPayload) -> None:
    if output.subagent_id:
        _update_group(
            cards,
            output.subagent_id,
            lambda group: {
                **group,
                "tool_calls": [_with_output(call, output) for call in _calls(group)],
            },
        )
        return
    for index, card in enumerate(cards):
        data = card["data"]
        if isinstance(data, dict) and _refs(card).tool_call_id == output.tool_call_id:
            field = "tool_result" if card["tool_name"] == MCP_APP_CARD else "output"
            cards[index] = cast(ToolDataEntry, {**card, "data": {**data, field: output.output}})


def _with_output(call: object, output: ToolOutputPayload) -> object:
    if isinstance(call, dict) and call.get("tool_call_id") == output.tool_call_id:
        return {**call, "output": output.output}
    return call


def _reasoning_step(content: str) -> _Json:
    return {
        "tool_name": REASONING_STEP,
        "tool_category": REASONING_STEP,
        "message": "",
        "reasoning": content,
    }


def _with_reasoning(steps: list[object], content: str) -> list[object]:
    """Merge into a trailing thinking step, or start one after a real tool call."""
    last = steps[-1] if steps else None
    if isinstance(last, dict) and isinstance(reasoning := last.get("reasoning"), str):
        return [*steps[:-1], {**last, "reasoning": reasoning + content}]
    return [*steps, _reasoning_step(content)]


def _take_reasoning(cards: list[ToolDataEntry], content: str, subagent_id: str | None) -> None:
    if subagent_id:
        _update_group(
            cards,
            subagent_id,
            lambda group: {**group, "tool_calls": _with_reasoning(_calls(group), content)},
        )
        return
    last = cards[-1] if cards else None
    if (
        last is not None
        and last["tool_name"] == TOOL_CALLS_CARD
        and isinstance(steps := last["data"], list)
        and steps
        and isinstance(steps[-1], dict)
        and "reasoning" in steps[-1]
    ):
        cards[-1] = cast(ToolDataEntry, {**last, "data": _with_reasoning(list(steps), content)})
        return
    cards.append(
        {
            "tool_name": TOOL_CALLS_CARD,
            "tool_category": REASONING_STEP,
            "data": [_reasoning_step(content)],
        }
    )


def _take_start(cards: list[ToolDataEntry], start: SubagentStartPayload) -> None:
    group = asdict(
        _SubagentGroup(
            subagent_id=start.subagent_id,
            subagent=start.subagent,
            subagent_name=start.subagent_name,
            agent_type=start.agent_type,
            started_at=start.started_at,
            icon_url=start.icon_url,
            tool_category=start.tool_category,
        )
    )
    if start.parent_subagent_id:
        _update_group(
            cards,
            start.parent_subagent_id,
            lambda parent: {**parent, "nested_subagents": [*_nested(parent), group]},
        )
        return
    cards.append(
        {
            "tool_name": SUBAGENT_GROUP_TOOL_NAME,
            "tool_category": "subagent",
            "data": group,
            "timestamp": start.started_at,
        }
    )


def _ended(group: _Group, end: SubagentEndPayload) -> _Group:
    started = group.get("started_at")
    completed = (
        (datetime.fromisoformat(started) + timedelta(milliseconds=end.duration_ms)).isoformat()
        if isinstance(started, str)
        else None
    )
    return {
        **group,
        "duration_ms": end.duration_ms,
        "token_count": end.token_count,
        "completed_at": completed,
    }


def _take_todo_progress(cards: list[ToolDataEntry], snapshot: dict[str, object]) -> None:
    """Keep one todo card, first in the list, holding each source's newest snapshot."""
    source = _TodoSource.model_validate(snapshot).source or _DEFAULT_TODO_SOURCE
    for index, card in enumerate(cards):
        if card["tool_name"] == TODO_PROGRESS_CARD:
            held = card["data"] if isinstance(card["data"], dict) else {}
            cards[index] = {**card, "data": {**held, source: snapshot}}
            return
    cards.insert(0, {"tool_name": TODO_PROGRESS_CARD, "data": {source: snapshot}})


def _calls(group: _Group) -> list[object]:
    calls = group.get("tool_calls")
    return list(calls) if isinstance(calls, list) else []


def _nested(group: _Group) -> list[object]:
    nested = group.get("nested_subagents")
    return list(nested) if isinstance(nested, list) else []


def _in_group(group: _Group, subagent_id: str, change: Callable[[_Group], _Group]) -> _Group:
    if group.get("subagent_id") == subagent_id:
        return change(group)
    return {
        **group,
        "nested_subagents": [
            _in_group(cast(_Group, nested), subagent_id, change)
            if isinstance(nested, dict)
            else nested
            for nested in _nested(group)
        ],
    }


def _holds(group: _Group, subagent_id: str) -> bool:
    return group.get("subagent_id") == subagent_id or any(
        isinstance(nested, dict) and _holds(cast(_Group, nested), subagent_id)
        for nested in _nested(group)
    )


def _update_group(
    cards: list[ToolDataEntry], subagent_id: str, change: Callable[[_Group], _Group]
) -> bool:
    """Change the subagent's group wherever it nests; False when its start never arrived."""
    for index, card in enumerate(cards):
        data = card["data"]
        if card["tool_name"] == SUBAGENT_GROUP_TOOL_NAME and isinstance(data, dict):
            if _holds(data, subagent_id):
                cards[index] = {**card, "data": _in_group(data, subagent_id, change)}
                return True
    return False
