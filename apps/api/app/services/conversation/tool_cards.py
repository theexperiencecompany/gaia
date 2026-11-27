"""The one fold of a run's stream payloads into the tool cards and image a client shows.

Pure: the same payloads always fold to the same cards. A comms reply, finished work, a
running work item on the screen and a replayed workflow playbook all fold through it, so a
card looks the same live, settled and reloaded.

A stored card keeps a bounded share of outputs and thinking (capped_outputs), or none past
its retention (dropped_outputs). A thinking step left with no text is not kept, and a card
left with nothing is removed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import TypeVar, cast

from pydantic import BaseModel, ConfigDict

from app.constants.chat import SUBAGENT_GROUP_TOOL_NAME
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.constants.openui_artifacts import ARTIFACT_DONE_EVENT
from app.constants.summarization import (
    MAX_CARD_TEXT_CHARS,
    MAX_ENTRY_TEXT_CHARS,
    MAX_OUTPUT_CHARS,
)
from app.models.conversation_frame_models import (
    ArtifactDeltaEvent,
    ImageEvent,
    ReasoningEvent,
    StreamPayload,
    SubagentEndEvent,
    SubagentStartEvent,
    TodoProgressEvent,
    ToolDataEvent,
    ToolOutputEvent,
)
from app.models.openui_artifact_models import ArtifactCard, ArtifactDelta, ArtifactStatus
from app.models.stream_events import SubagentEndPayload, SubagentStartPayload, ToolOutputPayload
from shared.py.conversation_wire import ImageData, ToolDataEntry

TOOL_CALLS_CARD = "tool_calls_data"
TODO_PROGRESS_CARD = "todo_progress"
MCP_APP_CARD = "mcp_app"
#: tool_name and tool_category of a thinking step riding the tool-call channel.
REASONING_STEP = "reasoning"
#: On a tool call whose output was cut: how many characters the tool returned.
OUTPUT_ORIGINAL_LENGTH = "output_original_length"
_DEFAULT_TODO_SOURCE = "executor"

_Json = dict[str, object]
_Group = dict[str, object]
_Value = TypeVar("_Value")


class _CardRefs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_call_id: str | None = None
    approval_id: str | None = None
    stream_id: str | None = None


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
            case ArtifactDeltaEvent(artifact_delta=delta):
                _take_artifact_delta(cards, delta)
    return FoldedCards(tool_data=capped_outputs(cards), image=image)


def capped_outputs(cards: Iterable[ToolDataEntry]) -> tuple[ToolDataEntry, ...]:
    """Return cards with their tool outputs and thinking cut to what a log entry stores.

    A call keeps MAX_OUTPUT_CHARS of each, a card MAX_CARD_TEXT_CHARS and the cards together
    MAX_ENTRY_TEXT_CHARS, spent in order; a cut output names its full length. An MCP App's
    tool_result is its app's data and stays whole.
    """
    entry = _Budget(MAX_ENTRY_TEXT_CHARS)
    return _kept_cards(cards, lambda: _Budget(MAX_CARD_TEXT_CHARS, entry))


def dropped_outputs(cards: Iterable[ToolDataEntry]) -> tuple[ToolDataEntry, ...]:
    """Return cards with every tool output and all thinking dropped; a card left with nothing is removed."""
    return _kept_cards(cards, lambda: _Budget(0))


def _kept_cards(
    cards: Iterable[ToolDataEntry], budget_of: Callable[[], _Budget]
) -> tuple[ToolDataEntry, ...]:
    kept = (_capped_card(card, budget_of()) for card in cards)
    return tuple(card for card in kept if card is not None)


@dataclass
class _Budget:
    """Characters of output and thinking still to keep; a card's budget also spends its entry's."""

    remaining: int
    entry: _Budget | None = None

    def kept(self, text: str) -> str:
        room = min(MAX_OUTPUT_CHARS, self.remaining)
        if self.entry is not None:
            room = min(room, self.entry.remaining)
        kept = text[:room]
        self.remaining -= len(kept)
        if self.entry is not None:
            self.entry.remaining -= len(kept)
        return kept


def _capped_card(card: ToolDataEntry, budget: _Budget) -> ToolDataEntry | None:
    """Return the card cut to the budget; None for a calls card the cut left with no step."""
    name, data = card["tool_name"], card["data"]
    if name == TOOL_CALLS_CARD:
        if not isinstance(data, list):
            call = _capped_call(data, budget)
            return None if _is_empty_thinking(call) else cast(ToolDataEntry, {**card, "data": call})
        capped = _capped_calls(data, budget)
        return cast(ToolDataEntry, {**card, "data": capped}) if capped or not data else None
    if name == SUBAGENT_GROUP_TOOL_NAME and isinstance(data, dict):
        return cast(ToolDataEntry, {**card, "data": _capped_group(data, budget)})
    return card


def _capped_group(group: _Group, budget: _Budget) -> _Group:
    return {
        **group,
        "tool_calls": _capped_calls(_calls(group), budget),
        "nested_subagents": [
            _capped_group(nested, budget) if isinstance(nested, dict) else nested
            for nested in _nested(group)
        ],
    }


def _capped_calls(calls: Sequence[object], budget: _Budget) -> list[object]:
    """Cut each call to the budget, leaving out a thinking step with no thinking left."""
    capped = (_capped_call(call, budget) for call in calls)
    return [call for call in capped if not _is_empty_thinking(call)]


def _is_empty_thinking(call: object) -> bool:
    return (
        isinstance(call, dict)
        and call.get("tool_name") == REASONING_STEP
        and call.get("reasoning") == ""
    )


def _capped_call(call: object, budget: _Budget) -> object:
    if not isinstance(call, dict):
        return call
    capped = dict(call)
    if isinstance(reasoning := call.get("reasoning"), str):
        capped["reasoning"] = budget.kept(reasoning)
    if isinstance(output := call.get("output"), str):
        kept = budget.kept(output)
        if len(kept) < len(output):
            # A seed cut before keeps the length its tool really returned.
            whole = call.get(OUTPUT_ORIGINAL_LENGTH)
            capped["output"] = kept
            capped[OUTPUT_ORIGINAL_LENGTH] = whole if isinstance(whole, int) else len(output)
    return capped


def merged_thinking(calls: Iterable[dict[str, _Value]]) -> list[dict[str, _Value]]:
    """Return calls with each run of thinking steps merged into its first."""
    merged: list[dict[str, _Value]] = []
    for call in calls:
        last = merged[-1] if merged else None
        more = call.get("reasoning")
        held = None if last is None else last.get("reasoning")
        if last is None or not isinstance(held, str) or not isinstance(more, str):
            merged.append(call)
        else:
            # Text is a value of either JSON typing a caller holds its steps in.
            merged[-1] = {**last, "reasoning": cast(_Value, held + more)}
    return merged


def _merged_group(group: _Group) -> _Group:
    """Return the subagent group with its thinking merged, and its nested groups' the same way."""
    calls = _calls(group)
    steps = [call for call in calls if isinstance(call, dict)]
    return {
        **group,
        # A call that is no step is kept as stored: nothing reads it, and nothing here guesses at it.
        "tool_calls": merged_thinking(steps) if len(steps) == len(calls) else calls,
        "nested_subagents": [
            _merged_group(nested) if isinstance(nested, dict) else nested
            for nested in _nested(group)
        ],
    }


def _thinking_step(card: ToolDataEntry) -> _Json | None:
    """Return the step of a card that is one thinking step and nothing else."""
    data = card["data"]
    if card["tool_name"] != TOOL_CALLS_CARD or not isinstance(data, dict):
        return None
    return data if isinstance(data.get("reasoning"), str) else None


def coalesced_thinking(cards: Iterable[ToolDataEntry]) -> tuple[ToolDataEntry, ...]:
    """Return cards with each run of thinking merged into its first step, at the top and inside subagent groups.

    Older logs stored one thinking step per token.
    """
    merged: list[ToolDataEntry] = []
    for card in cards:
        data = card["data"]
        if card["tool_name"] == SUBAGENT_GROUP_TOOL_NAME and isinstance(data, dict):
            merged.append(cast(ToolDataEntry, {**card, "data": _merged_group(data)}))
            continue
        last = merged[-1] if merged else None
        step = _thinking_step(card)
        held = None if last is None or step is None else _thinking_step(last)
        if last is None or held is None or step is None or _subagent(last) != _subagent(card):
            merged.append(card)
            continue
        (both,) = merged_thinking([held, step])
        merged[-1] = cast(ToolDataEntry, {**last, "data": both})
    return tuple(merged)


def _subagent(card: ToolDataEntry) -> str | None:
    return card.get("subagent_id")


def _copy(card: ToolDataEntry) -> ToolDataEntry:
    data = card["data"]
    return cast(ToolDataEntry, {**card, "data": dict(data) if isinstance(data, dict) else data})


def _refs(card: ToolDataEntry) -> _CardRefs:
    data = card["data"]
    return _CardRefs.model_validate(data) if isinstance(data, dict) else _CardRefs()


def _replaced_by(card: ToolDataEntry) -> tuple[str, str] | None:
    """Return what a later frame of the same card replaces it by: its approval, or its artifact run."""
    name, refs = card["tool_name"], _refs(card)
    if name == APPROVAL_REQUEST_TOOL_NAME and refs.approval_id:
        return name, refs.approval_id
    if name == ARTIFACT_DONE_EVENT and refs.stream_id:
        return name, refs.stream_id
    return None


def _take_card(cards: list[ToolDataEntry], card: ToolDataEntry) -> None:
    """Route a subagent's call into its group; an approval's or artifact's later frame replaces its earlier one in place."""
    subagent_id = card.get("subagent_id")
    if subagent_id and card["tool_name"] == TOOL_CALLS_CARD:
        _update_group(
            cards,
            subagent_id,
            lambda group: {**group, "tool_calls": [*_calls(group), card["data"]]},
        )
        return
    key = _replaced_by(card)
    if key is not None:
        for index, held in enumerate(cards):
            if _replaced_by(held) == key:
                cards[index] = card
                return
    cards.append(card)


def _take_artifact_delta(cards: list[ToolDataEntry], delta: ArtifactDelta) -> None:
    """Append a draft chunk to its artifact's streaming card, opening the card on the first chunk."""
    key = (ARTIFACT_DONE_EVENT, delta.stream_id)
    index = next((i for i, held in enumerate(cards) if _replaced_by(held) == key), None)
    held = None if index is None else ArtifactCard.model_validate(cards[index]["data"])
    if held is not None and held.status is not ArtifactStatus.STREAMING:
        return  # The run already ended: a late chunk changes nothing.
    draft = ArtifactCard(
        stream_id=delta.stream_id,
        kind=delta.kind,
        title=delta.title,
        status=ArtifactStatus.STREAMING,
        program=(held.program if held is not None and held.program else "") + delta.delta,
    )
    card: ToolDataEntry = {
        "tool_name": ARTIFACT_DONE_EVENT,
        "data": draft.model_dump(exclude_none=True),
    }
    if index is None:
        cards.append(card)
    else:
        cards[index] = card


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
) -> None:
    """Change the subagent's group wherever it nests; nothing when its start never arrived."""
    for index, card in enumerate(cards):
        data = card["data"]
        if card["tool_name"] == SUBAGENT_GROUP_TOOL_NAME and isinstance(data, dict):
            if _holds(data, subagent_id):
                cards[index] = {**card, "data": _in_group(data, subagent_id, change)}
                return
