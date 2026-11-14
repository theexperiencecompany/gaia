"""One way to send a chat message to a running API and read back everything it caused.

A turn is the wire every client uses: POST /api/v1/conversations/{id}/messages with a
client-minted message id (202, with the message's seq), then GET .../events after that
seq until the message is answered. Every eval harness goes through this module, so the
rules that decide what a run measures (which reply text is graded, which tool cards
count, when a delegated answer has landed) live in one place: TurnReader, a pure fold
over the stream's screen frames (the items the server computed and its patches to
them, parsed by the shared wire models) that is tested without an API.

The differences between harnesses are TurnOptions fields rather than forks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import time
from uuid import uuid4

import httpx
from pydantic import BaseModel

from app.models.conversation_frame_models import RetractFrame, StateFrame
from app.models.conversation_log_models import DisplayState
from app.models.conversation_screen_models import (
    ScreenFrame,
    ScreenInsertFrame,
    ScreenItem,
    ScreenStreamFrame,
    ScreenUpdateFrame,
    UserItem,
    WorkItem,
    WorkStatus,
)
from app.models.conversation_send_models import ConversationEvent, MessageAccepted
from shared.py.conversation_wire import (
    NEW_MESSAGE_BREAKER,
    BubblesDelta,
    BubbleTextDelta,
    CardsDelta,
    FollowUpsDelta,
    ReplyDelta,
    ReplyDeltaFrame,
    ReplyItem,
    ReplyOutcome,
    ToolDataEntry,
)

#: A turn that produced no prose at all. Scripts test replies against this
#: sentinel, so it has to be one string, not one per harness.
NO_TEXT_REPLY = "[no text in stream]"
NOTHING_DELIVERED = "\n\n[nothing delivered within budget]"

#: How long a delegated answer may take after the message's own reply settled.
DELIVERY_WAIT_SECONDS = 75.0

TOOL_CALLS_CARD = "tool_calls_data"
APPROVAL_CARD = "approval_request"
SSE_DATA_PREFIX = "data:"

#: How the eval names an approval no outcome has ended yet.
PENDING = "pending"


class ApprovalSeen(BaseModel):
    """One outcome an approval was seen with: requested (pending), ended, or a card's own outcome."""

    approval_id: str
    outcome: str
    decider: str | None = None


class Turn(BaseModel):
    """One message, what answered it, and the evidence GAIA did a thing rather than talked about it."""

    message: str
    message_id: str = ""
    reply: str = ""
    #: Text of each write-up of work the message started, in the order they landed.
    delivered: list[str] = []
    #: tool_name of every card seen; a connect card arrives as
    #: integration_connection_required, a created reminder as the reminder tool's name.
    tools: list[str] = []
    tool_data: list[ToolDataEntry] = []
    approvals: list[ApprovalSeen] = []
    follow_up_actions: list[str] | None = None
    #: The emoji GAIA put on the message, when it reacted instead of (or as well as) writing.
    reaction: str | None = None
    #: Every distinct frame kind seen, collected generically so a kind added
    #: upstream still shows up here instead of being dropped.
    frame_kinds: list[str] = []
    #: True when the message started background work; its write-up is a later reply.
    delegated: bool = False
    #: How the message's own reply settled; None when it never did.
    outcome: ReplyOutcome | None = None
    error: str | None = None
    #: The newest log seq seen, the cursor a later follow resumes after.
    last_seq: int = 0
    #: True when work the message started had not reported within the delivery budget.
    undelivered: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.reply.strip() or self.reply.strip() == NO_TEXT_REPLY

    @property
    def awaiting_approval(self) -> bool:
        latest = {seen.approval_id: seen.outcome for seen in self.approvals}
        return PENDING in latest.values()


def card_tool_names(entry: ToolDataEntry, *, include_nested: bool = True) -> list[str]:
    """The card's tool name, plus the tool a tool_calls_data announcement carries when include_nested."""
    names = [entry["tool_name"]]
    inner = entry["data"]
    if include_nested and entry["tool_name"] == TOOL_CALLS_CARD and isinstance(inner, dict):
        inner_name = inner.get("tool_name") or inner.get("name")
        if isinstance(inner_name, str):
            names.append(inner_name)
    return names


def called_tools(tool_data: list[ToolDataEntry]) -> list[dict[str, object]]:
    """Every tool call a tool_calls_data card announced, once per tool_call_id, as name and args."""
    calls: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in tool_data:
        data = entry["data"]
        if entry["tool_name"] != TOOL_CALLS_CARD or not isinstance(data, dict):
            continue
        call_id = data.get("tool_call_id")
        if isinstance(call_id, str):
            if call_id in seen:
                continue
            seen.add(call_id)
        inputs = data.get("inputs")
        calls.append(
            {"name": data.get("tool_name"), "args": inputs if isinstance(inputs, dict) else {}}
        )
    return calls


#: Work still under way: its write-up has not landed.
_LIVE_WORK = frozenset({WorkStatus.RUNNING, WorkStatus.AWAITING_APPROVAL})


class TurnReader:
    """Fold a conversation's screen frames into what one message caused.

    The turn is every item past the message's own. The message is answered once a reply
    of the turn that narrates none of its work has settled, or once the conversation has
    moved past it without thinking; it is settled once every piece of its work has
    ended and a settled reply narrates each (its write-up). done says when a follower
    stops reading: at the answer, at the settle with wait_for_work, or at a pending
    approval with stop_at_approval.
    """

    def __init__(
        self,
        message: str,
        message_id: str,
        *,
        collect_frame_kinds: bool = False,
        wait_for_work: bool = True,
        stop_at_approval: bool = False,
    ) -> None:
        self._turn = Turn(message=message, message_id=message_id)
        self._collect_frame_kinds = collect_frame_kinds
        self._wait_for_work = wait_for_work
        self._stop_at_approval = stop_at_approval
        self._kinds: set[str] = set()
        self._items: dict[str, ScreenItem] = {}
        self._attempt_reply: dict[str, str] = {}
        self._attempt_text: dict[str, list[str]] = {}
        self._delta_cards: dict[str, ToolDataEntry] = {}
        self._state: StateFrame | None = None

    @property
    def answered(self) -> bool:
        if any(reply.outcome is not None for reply in self._own_replies()):
            return True
        own_seq = self._message_seq()
        state = self._state
        return (
            own_seq is not None
            and state is not None
            and state.head > own_seq
            and state.display is not DisplayState.THINKING
        )

    @property
    def settled(self) -> bool:
        work = self._work()
        if not self.answered or any(item.status in _LIVE_WORK for item in work):
            return False
        narrated = {task for reply in self._written_up() for task in reply.narrates}
        return all(item.task_id in narrated for item in work)

    @property
    def awaiting_approval(self) -> bool:
        return self.turn().awaiting_approval

    @property
    def done(self) -> bool:
        if self._stop_at_approval and self.awaiting_approval:
            return True
        return self.settled if self._wait_for_work else self.answered

    def feed(self, frame: ScreenStreamFrame) -> None:
        self._kind(frame.kind.value)
        match frame:
            case ScreenFrame(items=items):
                for item in items:
                    self._take(item)
            case ScreenInsertFrame(item=item) | ScreenUpdateFrame(item=item):
                self._take(item)
            case ReplyDeltaFrame():
                self._kind(f"{frame.kind.value}:{frame.payload.type}")
                if frame.reply_id is not None:
                    self._attempt_reply[frame.attempt_id] = frame.reply_id
                self._reply_delta(frame.attempt_id, frame.payload)
            case RetractFrame():
                self._attempt_text.pop(frame.attempt_id, None)
            case StateFrame():
                self._state = frame
            case _:
                pass

    def _kind(self, kind: str) -> None:
        if self._collect_frame_kinds:
            self._kinds.add(kind)

    def _take(self, item: ScreenItem) -> None:
        self._kind(f"item:{item.kind.value}")
        self._items[item.id] = item
        self._turn.last_seq = max(self._turn.last_seq, item.seq)
        if isinstance(item, WorkItem) and item in self._work():
            self._work_approvals(item)

    def _reply_delta(self, attempt_id: str, payload: ReplyDelta) -> None:
        bubbles = self._attempt_text.setdefault(attempt_id, [])
        match payload:
            case BubbleTextDelta(bubble=bubble, text=text):
                if bubble == len(bubbles):
                    bubbles.append("")
                bubbles[bubble] += text
            case BubblesDelta(bubbles=now):
                self._attempt_text[attempt_id] = list(now)
            case CardsDelta(tool_data=cards):
                for card in cards:
                    self._delta_cards.setdefault(_card_key(card), card)
            case FollowUpsDelta(follow_up_actions=actions):
                self._turn.follow_up_actions = list(actions)

    def _work_approvals(self, item: WorkItem) -> None:
        for asked in item.asking:
            self._approval(asked.approval_id, PENDING)
        for card in item.approvals:
            data = card.data
            outcome = PENDING if data.outcome is None else data.outcome.value
            decider = None if data.decider is None else data.decider.value
            self._approval(data.approval_id, outcome, decider)

    def _approval(self, approval_id: str, outcome: str, decider: str | None = None) -> None:
        seen = ApprovalSeen(approval_id=approval_id, outcome=outcome, decider=decider)
        if seen not in self._turn.approvals:
            self._turn.approvals.append(seen)

    def _message(self) -> UserItem | None:
        item = self._items.get(self._turn.message_id)
        return item if isinstance(item, UserItem) else None

    def _message_seq(self) -> int | None:
        message = self._message()
        return None if message is None else message.seq

    def _turn_items(self) -> list[ScreenItem]:
        own_seq = self._message_seq()
        if own_seq is None:
            return []
        return sorted((i for i in self._items.values() if i.seq > own_seq), key=lambda i: i.seq)

    def _work(self) -> list[WorkItem]:
        return [item for item in self._turn_items() if isinstance(item, WorkItem)]

    def _replies(self) -> list[ReplyItem]:
        return [item for item in self._turn_items() if isinstance(item, ReplyItem)]

    def _tasks(self) -> set[str]:
        return {item.task_id for item in self._work()}

    def _own_replies(self) -> list[ReplyItem]:
        tasks = self._tasks()
        return [reply for reply in self._replies() if not tasks.intersection(reply.narrates)]

    def _written_up(self) -> list[ReplyItem]:
        tasks = self._tasks()
        return [
            reply
            for reply in self._replies()
            if reply.outcome is not None and tasks.intersection(reply.narrates)
        ]

    def _text(self, reply: ReplyItem) -> str:
        text = NEW_MESSAGE_BREAKER.join(reply.bubbles).strip()
        if text:
            return text
        streamed = [
            NEW_MESSAGE_BREAKER.join(bubbles)
            for attempt, bubbles in self._attempt_text.items()
            if self._attempt_reply.get(attempt) == reply.id
        ]
        return "".join(streamed).strip()

    def _cards(self) -> list[ToolDataEntry]:
        cards = dict(self._delta_cards)
        for item in self._turn_items():
            if isinstance(item, ReplyItem | WorkItem):
                for card in item.tool_data:
                    cards.setdefault(_card_key(card), card)
        for card in cards.values():
            data = card["data"]
            if card["tool_name"] == APPROVAL_CARD and isinstance(data, dict):
                approval_id, outcome = data.get("approval_id"), data.get("outcome") or PENDING
                decider = data.get("decider")
                if isinstance(approval_id, str) and isinstance(outcome, str):
                    self._approval(
                        approval_id, outcome, decider if isinstance(decider, str) else None
                    )
        return list(cards.values())

    def turn(self, *, include_nested_tool_names: bool = True) -> Turn:
        """The turn as read so far: reply is the message's own answer (or the sentinel), delivered its work's write-ups."""
        own = [reply for reply in self._own_replies() if reply.outcome is not None]
        message = self._message()
        reaction = None if message is None else message.message.reaction
        first = own[0] if own else None
        if first is not None and first.follow_up_actions:
            self._turn.follow_up_actions = list(first.follow_up_actions)
        tool_data = self._cards()
        return self._turn.model_copy(
            update={
                "reply": "\n".join(text for r in own if (text := self._text(r))) or NO_TEXT_REPLY,
                "delivered": [text for r in self._written_up() if (text := self._text(r))],
                "tool_data": tool_data,
                "tools": [
                    name
                    for entry in tool_data
                    for name in card_tool_names(entry, include_nested=include_nested_tool_names)
                ],
                "reaction": None if reaction is None else reaction.emoji,
                "delegated": bool(self._work()),
                "outcome": None if first is None else first.outcome,
                "error": (
                    None
                    if first is None or first.failure is None or first.outcome is None
                    else f"reply {first.outcome.value}: {first.failure.value}"
                ),
                "frame_kinds": sorted(self._kinds),
            }
        )


def _card_key(card: ToolDataEntry) -> str:
    return json.dumps(card, sort_keys=True, default=str)


@dataclass(frozen=True)
class TurnOptions:
    """How one harness wants a turn read back.

    Frozen because a harness's turn shape is fixed for the whole run: a mutable
    options object shared across turns is a way for turn 7 to be read differently
    from turn 1 and for nobody to notice.
    """

    #: Budget for the whole turn, delegated answer included.
    timeout: float = 180.0
    #: Also count the tool a tool_calls_data announcement carries.
    include_nested_tool_names: bool = True
    #: Record every distinct frame kind on the Turn.
    collect_frame_kinds: bool = False
    #: Wait for the write-up of work the message started, not just its own reply.
    wait_for_work: bool = True
    #: Separator between the comms reply and the later delivered answer.
    delivered_prefix: str = "\n\n[delivered later] "
    #: Drop the "no text" sentinel when a delivered answer replaces it.
    drop_sentinel_before_delivery: bool = False
    delivery_wait_seconds: float = DELIVERY_WAIT_SECONDS


async def open_conversation(client: httpx.AsyncClient, api_url: str, description: str) -> str:
    """Create a conversation the caller owns, titled description, and return its id."""
    conversation_id = str(uuid4())
    response = await client.post(
        f"{api_url}/api/v1/conversations",
        json={"conversation_id": conversation_id, "description": description},
        timeout=30.0,
    )
    response.raise_for_status()
    return conversation_id


async def follow(
    client: httpx.AsyncClient,
    api_url: str,
    conversation_id: str,
    reader: TurnReader,
    *,
    after: int,
    delivery_wait_seconds: float = DELIVERY_WAIT_SECONDS,
) -> bool:
    """Feed the events after seq after into reader until it is done; False when the delivery budget ran out.

    The delivery budget starts when the message's own reply settles.
    """
    delivery_deadline: float | None = None
    async with client.stream(
        "GET",
        f"{api_url}/api/v1/conversations/{conversation_id}/events",
        params={"after": str(after)},
        timeout=httpx.Timeout(30.0, read=None),
    ) as response:
        if response.status_code != 200:
            await response.aread()
            raise httpx.HTTPStatusError(
                f"events HTTP {response.status_code}: {response.text[:300]}",
                request=response.request,
                response=response,
            )
        async for line in response.aiter_lines():
            if line.startswith(SSE_DATA_PREFIX):
                event = ConversationEvent.model_validate_json(line.removeprefix(SSE_DATA_PREFIX))
                reader.feed(event.frame)
            if reader.done:
                return True
            if reader.answered and delivery_deadline is None:
                delivery_deadline = time.monotonic() + delivery_wait_seconds
            if delivery_deadline is not None and time.monotonic() > delivery_deadline:
                return False
    raise httpx.RemoteProtocolError("the events stream closed before the message was answered")


async def send_message(
    client: httpx.AsyncClient, api_url: str, conversation_id: str, text: str
) -> MessageAccepted:
    """Send text with a minted message id; raises httpx.HTTPStatusError when the API refuses it."""
    response = await client.post(
        f"{api_url}/api/v1/conversations/{conversation_id}/messages",
        json={"message_id": str(uuid4()), "text": text},
        timeout=30.0,
    )
    response.raise_for_status()
    return MessageAccepted.model_validate(response.json())


async def read_turn(
    client: httpx.AsyncClient,
    api_url: str,
    message: str,
    conversation_id: str,
    options: TurnOptions = TurnOptions(),
) -> Turn:
    """Send one message and read what answered it, as the reader saw it; the log carries the history."""
    accepted = await send_message(client, api_url, conversation_id, message)
    reader = TurnReader(
        message,
        accepted.message_id,
        collect_frame_kinds=options.collect_frame_kinds,
        wait_for_work=options.wait_for_work,
    )
    async with asyncio.timeout(options.timeout):
        delivered_in_time = await follow(
            client,
            api_url,
            conversation_id,
            reader,
            after=accepted.seq - 1,
            delivery_wait_seconds=options.delivery_wait_seconds,
        )
    turn = reader.turn(include_nested_tool_names=options.include_nested_tool_names)
    return turn.model_copy(update={"undelivered": not delivered_in_time})


async def send_turn(
    client: httpx.AsyncClient,
    api_url: str,
    message: str,
    conversation_id: str,
    options: TurnOptions = TurnOptions(),
) -> Turn:
    """read_turn, with the delivered answer joined onto reply the way the harness asks.

    A refused send comes back as a Turn whose reply carries the status and body rather than
    as an exception: one persona hitting a 402 should be one bad row, not a dead run.
    """
    try:
        turn = await read_turn(client, api_url, message, conversation_id, options)
    except httpx.HTTPStatusError as refused:
        response = refused.response
        return Turn(message=message, reply=f"[HTTP {response.status_code}] {response.text[:300]}")
    if not (turn.delegated and options.wait_for_work):
        return turn
    if turn.delivered:
        head = "" if options.drop_sentinel_before_delivery and turn.is_empty else turn.reply
        reply = (head + options.delivered_prefix + "\n".join(turn.delivered)).strip()
    else:
        reply = turn.reply + (NOTHING_DELIVERED if turn.undelivered else "")
    return turn.model_copy(update={"reply": reply})
