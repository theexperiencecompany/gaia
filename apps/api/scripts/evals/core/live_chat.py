"""One way to send a chat message to a running API and read back everything it caused.

A turn is the wire every client uses: POST /api/v1/conversations/{id}/messages with a
client-minted message id (202, with the message's seq), then GET .../events after that
seq until the message is answered. Every eval harness goes through this module, so the
rules that decide what a run measures (which reply text is graded, which tool cards
count, when a delegated answer has landed) live in one place: TurnReader, a pure fold
over the stream's frames that is tested without an API.

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

from app.models.conversation_frame_models import (
    EntryFrame,
    EntryUpdatedFrame,
    FollowUpActionsEvent,
    OutputFrame,
    ReplyDeltaFrame,
    ResponseEvent,
    RetractFrame,
    ToolDataEvent,
    WorkDeltaFrame,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    Entry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    UserMessage,
    WorkFinished,
    WorkStarted,
)
from app.models.conversation_send_models import ConversationEvent, MessageAccepted
from app.models.tool_data_models import ToolDataEntry

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


class TurnReader:
    """Fold a conversation's frames into what one message caused.

    The message is answered once a ReplySettled lists it; it is settled once every piece
    of work it started has finished and a reply has answered that finish (its write-up,
    which also lists the message). done says when a follower stops reading: at the
    answer, at the settle with wait_for_work, or at a pending approval with
    stop_at_approval.
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
        self._reply_order: list[str] = []
        self._reply_text: dict[str, str] = {}
        self._attempt_reply: dict[str, str] = {}
        self._attempt_text: dict[str, list[str]] = {}
        self._answering: list[str] = []
        self._cards: dict[str, ToolDataEntry] = {}
        self._tasks: set[str] = set()
        self._live_tasks: set[str] = set()
        self._unreported: set[str] = set()
        self._answered = False

    @property
    def answered(self) -> bool:
        return self._answered

    @property
    def settled(self) -> bool:
        return self._answered and not self._live_tasks and not self._unreported

    @property
    def awaiting_approval(self) -> bool:
        return self._turn.awaiting_approval

    @property
    def done(self) -> bool:
        if self._stop_at_approval and self.awaiting_approval:
            return True
        return self.settled if self._wait_for_work else self._answered

    def feed(self, frame: OutputFrame) -> None:
        if self._collect_frame_kinds:
            self._kinds.add(frame.kind.value)
        match frame:
            case EntryFrame() | EntryUpdatedFrame():
                self._turn.last_seq = max(self._turn.last_seq, frame.seq)
                self._entry(frame.entry)
            case ReplyDeltaFrame():
                self._kind(f"{frame.kind.value}:{frame.payload.type.value}")
                if isinstance(frame.payload, ResponseEvent):
                    self._attempt_text.setdefault(frame.attempt_id, []).append(
                        frame.payload.response
                    )
                self._payload(frame.payload)
            case WorkDeltaFrame():
                self._kind(f"{frame.kind.value}:{frame.payload.type.value}")
                if frame.task_id in self._live_tasks:
                    self._payload(frame.payload)
            case RetractFrame():
                self._attempt_text.pop(frame.attempt_id, None)
            case _:
                pass

    def _kind(self, kind: str) -> None:
        if self._collect_frame_kinds:
            self._kinds.add(kind)

    def _payload(self, payload: object) -> None:
        if isinstance(payload, ToolDataEvent):
            self._card(payload.tool_data)
        elif isinstance(payload, FollowUpActionsEvent):
            self._turn.follow_up_actions = list(payload.follow_up_actions)

    def _card(self, entry: ToolDataEntry) -> None:
        self._cards.setdefault(json.dumps(entry, sort_keys=True, default=str), entry)
        data = entry["data"]
        if entry["tool_name"] == APPROVAL_CARD and isinstance(data, dict):
            approval_id, outcome = data.get("approval_id"), data.get("outcome") or PENDING
            decider = data.get("decider")
            if isinstance(approval_id, str) and isinstance(outcome, str):
                self._approval(approval_id, outcome, decider if isinstance(decider, str) else None)

    def _approval(self, approval_id: str, outcome: str, decider: str | None = None) -> None:
        seen = ApprovalSeen(approval_id=approval_id, outcome=outcome, decider=decider)
        if seen not in self._turn.approvals:
            self._turn.approvals.append(seen)

    def _entry(self, entry: Entry) -> None:
        self._kind(f"entry:{entry.kind.value}")
        match entry:
            case UserMessage(id=self._turn.message_id, reaction=reaction) if reaction is not None:
                self._turn.reaction = reaction.emoji
            case WorkStarted() | ApprovalRequested() | ApprovalDecided() | WorkFinished():
                self._work_entry(entry)
            case Reply():
                self._reply(entry)
            case ReplySettled():
                self._settle(entry)
            case _:
                pass

    def _work_entry(
        self, entry: WorkStarted | ApprovalRequested | ApprovalDecided | WorkFinished
    ) -> None:
        match entry:
            case WorkStarted() if (
                self._turn.message_id in entry.answers or entry.joins in self._live_tasks
            ):
                self._turn.delegated = True
                self._tasks.add(entry.task_id)
                self._live_tasks.add(entry.task_id)
            case ApprovalRequested() if entry.task_id in self._live_tasks:
                self._approval(entry.approval_id, PENDING)
            case ApprovalDecided() if any(
                seen.approval_id == entry.approval_id for seen in self._turn.approvals
            ):
                self._approval(entry.approval_id, entry.outcome, entry.decider)
            case WorkFinished() if entry.task_id in self._live_tasks:
                self._live_tasks.discard(entry.task_id)
                self._unreported.add(entry.id)
                for card in entry.tool_data:
                    self._card(card)
            case _:
                pass

    def _reply(self, entry: Reply) -> None:
        if entry.reply_id not in self._reply_text:
            self._reply_order.append(entry.reply_id)
        self._attempt_reply[entry.attempt_id] = entry.reply_id
        self._reply_text[entry.reply_id] = entry.text
        for card in entry.tool_data:
            self._card(card)
        if entry.follow_up_actions:
            self._turn.follow_up_actions = list(entry.follow_up_actions)

    def _settle(self, entry: ReplySettled) -> None:
        self._unreported.difference_update(entry.answers)
        if self._turn.message_id not in entry.answers:
            return
        self._answering.append(entry.reply_id)
        if not self._answered:
            self._turn.outcome = entry.outcome
            if entry.failure is not None:
                self._turn.error = f"reply {entry.outcome.value}: {entry.failure.value}"
        self._answered = True

    def _text(self, reply_id: str) -> str:
        text = self._reply_text.get(reply_id, "")
        if text.strip():
            return text.strip()
        streamed = [
            "".join(chunks)
            for attempt, chunks in self._attempt_text.items()
            if self._attempt_reply.get(attempt) == reply_id
        ]
        return "".join(streamed).strip()

    def turn(self, *, include_nested_tool_names: bool = True) -> Turn:
        """The turn as read so far: reply is the message's own answer (or the sentinel), delivered its work's write-ups."""
        answering = [reply_id for reply_id in self._reply_order if reply_id in set(self._answering)]
        own = [self._text(reply_id) for reply_id in answering if reply_id not in self._tasks]
        delivered = [self._text(reply_id) for reply_id in answering if reply_id in self._tasks]
        tool_data = list(self._cards.values())
        return self._turn.model_copy(
            update={
                "reply": "\n".join(text for text in own if text) or NO_TEXT_REPLY,
                "delivered": [text for text in delivered if text],
                "tool_data": tool_data,
                "tools": [
                    name
                    for entry in tool_data
                    for name in card_tool_names(entry, include_nested=include_nested_tool_names)
                ],
                "frame_kinds": sorted(self._kinds),
            }
        )


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
