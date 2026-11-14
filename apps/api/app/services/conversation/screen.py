"""The one projection of a conversation's log into the screen every client renders.

An item sits at the seq it became visible at, so appending to the log only adds items at
the end or changes items already shown: nothing shown ever moves. Live and reloaded
screens are this same function of the same log.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, assert_never

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
    HIL_APPROVAL_TIMEOUT_SECONDS,
)
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    BargeIn,
    Entry,
    EntryKind,
    IntegrationConnected,
    IntegrationNeeded,
    Notice,
    Reply,
    ReplySettled,
    StopRequested,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_screen_models import (
    NoticeItem,
    ScreenItem,
    TodoWokeItem,
    UserItem,
    WorkflowFiredItem,
    WorkItem,
    WorkStatus,
)
from app.models.stream_events import ApprovalRequestEntry, ApprovalRequestEntryData
from app.services.conversation.reply_files import reply_files
from app.services.conversation.tool_timeline import tool_timeline
from app.utils.message_breaks import split_message_bubbles
from shared.py.approvals import ApprovalOutcome
from shared.py.conversation_wire import (
    ReplyItem,
    ReplyOutcome,
    ReplyToMessageData,
    ToolDataEntry,
    ToolTimeline,
)

#: The card a tool call streams; a hand-off is one whose call is call_executor.
TOOL_CALL_CARD = "tool_calls_data"
_STOPPED_WORK = frozenset({WorkOutcome.CANCELLED, WorkOutcome.LOST})
#: A work item whose cards are still being published.
LIVE_WORK = frozenset({WorkStatus.RUNNING, WorkStatus.AWAITING_APPROVAL})
#: The kinds a lone message's item reads beside it.
RELATED_KINDS: frozenset[str] = frozenset(
    {
        EntryKind.REPLY_SETTLED,
        EntryKind.USER_MESSAGE,
        EntryKind.WORK_STARTED,
        EntryKind.WORK_FINISHED,
    }
)
#: The suffixes of the two entries that can end a task: its result, or the sweeper's lost marker.
_ENDS = ("finished", "lost")


class _CardData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str | None = None
    tool_call_id: str | None = None


class Positioned(Protocol):
    """An entry at its position in the log: a LoggedEntry, or the frame that carries one."""

    @property
    def seq(self) -> int: ...
    @property
    def at(self) -> AwareDatetime: ...
    @property
    def entry(self) -> Entry: ...


def _card_data(card: ToolDataEntry) -> _CardData:
    data = card["data"]
    return _CardData.model_validate(data) if isinstance(data, dict) else _CardData()


def handoff_call_id(card: ToolDataEntry) -> str | None:
    """Return the tool call id when card is a comms hand-off to the executor, else None."""
    if card["tool_name"] != TOOL_CALL_CARD:
        return None
    data = _card_data(card)
    return data.tool_call_id if data.tool_name == CALL_EXECUTOR_NAME else None


def _is_handoff(card: ToolDataEntry) -> bool:
    return card["tool_name"] == TOOL_CALL_CARD and _card_data(card).tool_name == CALL_EXECUTOR_NAME


def work_root(started: Mapping[str, WorkStarted], task_id: str) -> str:
    """Return the task whose item task_id belongs to, through any chain of hand-overs."""
    seen = {task_id}
    while (work := started.get(task_id)) and work.joins in started:
        task_id = work.joins
        if task_id in seen:
            break
        seen.add(task_id)
    return task_id


@dataclass(frozen=True)
class _Settle:
    seq: int
    at: AwareDatetime
    entry: ReplySettled


@dataclass
class _Log:
    """What the items read from entries other than their own."""

    users: dict[str, UserMessage] = field(default_factory=dict)
    settles: dict[str, _Settle] = field(default_factory=dict)
    started: dict[str, WorkStarted] = field(default_factory=dict)
    finished: dict[str, WorkFinished] = field(default_factory=dict)
    requests: dict[str, ApprovalRequested] = field(default_factory=dict)
    request_seqs: dict[str, int] = field(default_factory=dict)
    request_ats: dict[str, AwareDatetime] = field(default_factory=dict)
    decisions: dict[str, ApprovalDecided] = field(default_factory=dict)
    handoffs: dict[str, ToolDataEntry] = field(default_factory=dict)

    @classmethod
    def of(cls, entries: Iterable[Positioned]) -> _Log:
        read = cls()
        for logged in entries:
            match logged.entry:
                case UserMessage() as message:
                    read.users[message.id] = message
                case ReplySettled() as settled:
                    read.settles[settled.reply_id] = _Settle(logged.seq, logged.at, settled)
                case WorkStarted() as started:
                    read.started[started.task_id] = started
                case WorkFinished() as work:
                    read.finished[work.task_id] = work
                case ApprovalRequested() as request:
                    read.requests[request.approval_id] = request
                    read.request_seqs[request.approval_id] = logged.seq
                    read.request_ats[request.approval_id] = logged.at
                case ApprovalDecided() as decision:
                    read.decide(decision)
                case Reply(tool_data=cards):
                    read.handoffs.update(
                        (call_id, card) for card in cards if (call_id := handoff_call_id(card))
                    )
        return read

    def decide(self, decision: ApprovalDecided) -> None:
        """Take the decision; the restatement that carries the approved action's result wins over the bare one."""
        if decision.action is not None or decision.approval_id not in self.decisions:
            self.decisions[decision.approval_id] = decision

    def root(self, task_id: str) -> str:
        return work_root(self.started, task_id)

    def approvals(self, root: str) -> tuple[ApprovalRequestEntry, ...]:
        """Return the card of every approval work under root asked for, as its entries have it now."""
        return tuple(
            self._approval_card(request)
            for request in self.requests.values()
            if self.root(request.task_id) == root
        )

    def _approval_card(self, request: ApprovalRequested) -> ApprovalRequestEntry:
        decision = self.decisions.get(request.approval_id)
        work = self.finished.get(self.root(request.task_id))
        outcome = (
            decision.outcome
            if decision is not None
            else ApprovalOutcome.CANCELLED
            if work is not None and work.outcome in _STOPPED_WORK
            else None
        )
        asked_at = self.request_ats[request.approval_id]
        return ApprovalRequestEntry(
            tool_name=APPROVAL_REQUEST_TOOL_NAME,
            tool_category=APPROVAL_TOOL_CATEGORY,
            data=ApprovalRequestEntryData(
                approval_id=request.approval_id,
                tool_call_id=request.tool_call_id,
                gated_tool_name=request.gated_tool_name,
                integration_name=request.integration_name,
                summary=request.summary,
                args_preview=request.args_preview,
                outcome=outcome,
                decider=None if decision is None else decision.decider,
                action=None if decision is None else decision.action,
                feedback=None if decision is None else decision.feedback,
                auto_reason=request.auto_reason,
                timeout_seconds=HIL_APPROVAL_TIMEOUT_SECONDS,
                asked_at=asked_at,
                always_asks=request.always_asks,
            ),
            timestamp=asked_at.isoformat(),
        )

    def asking(self, root: str) -> tuple[ApprovalRequested, ...]:
        """Return the approvals live work under root waits on, oldest first."""
        if root in self.finished:
            return ()
        return tuple(
            request
            for approval_id, request in self.requests.items()
            if self.root(request.task_id) == root and approval_id not in self.decisions
        )

    def newest_asked(self, answered: Iterable[str]) -> str | None:
        """Return the newest user message among answered: the one a retry sends again."""
        ids = set(answered)
        return next((user for user in reversed(self.users) if user in ids), None)

    def work_status(self, root: str) -> WorkStatus:
        finished = self.finished.get(root)
        if finished is not None:
            return WorkStatus(finished.outcome.value)
        return WorkStatus.AWAITING_APPROVAL if self.asking(root) else WorkStatus.RUNNING


def project_screen(entries: Sequence[Positioned]) -> list[ScreenItem]:
    """Return the screen for entries (ascending by seq): every visible item, at the seq it became visible."""
    read = _Log.of(entries)
    items: list[ScreenItem] = []
    for logged in entries:
        item = _item(logged, read)
        if item is not None:
            items.append(item)
    # Only a reply that became visible by failing sits at a later seq than its own entry.
    items.sort(key=lambda item: item.seq)
    return items


def text_item(
    logged: Positioned, related: Iterable[Positioned]
) -> UserItem | ReplyItem | NoticeItem | None:
    """Return the item a message shows on its conversation's screen, reading related for what sits beside it."""
    item = _item(logged, _Log.of([*related, logged]))
    return item if isinstance(item, UserItem | ReplyItem | NoticeItem) else None


def needed_beside(
    window: Sequence[Positioned], related: Sequence[Positioned] = ()
) -> tuple[list[str], list[str]]:
    """Return the entry ids and reply ids the window's text items still read beside related.

    Each answer can name more (a settle's quote, a request's work), so a read asks until none is left.
    """
    read = _Log.of([*window, *related])
    wanted: set[str] = set()
    replies: set[str] = set()
    for logged in window:
        match logged.entry:
            case Reply() as reply:
                settle = read.settles.get(reply.reply_id)
                if settle is None:
                    replies.add(reply.reply_id)
                target = reply.quote_target if settle is None else settle.entry.quote_target
                narrated = (*reply.narrates, *(() if settle is None else settle.entry.narrates))
                wanted |= {target} if target else set()
                wanted |= set(() if settle is None else settle.entry.answers)
                wanted |= {
                    f"work:{task}:{end}" for task in (*narrated, reply.reply_id) for end in _ENDS
                }
            case _:
                pass
    wanted |= {f"work:{work.joins}" for work in read.started.values() if work.joins}
    present = {logged.entry.id for logged in (*window, *related)}
    return sorted(wanted - present), sorted(replies)


def _item(logged: Positioned, read: _Log) -> ScreenItem | None:
    seq, at = logged.seq, logged.at
    match logged.entry:
        case UserMessage() as message:
            return UserItem(id=message.id, seq=seq, at=at, message=message)
        case Reply() as reply:
            return _reply_item(seq, at, reply, read)
        case WorkStarted(task_id=task_id) if read.root(task_id) == task_id:
            return _work_item(seq, at, task_id, read)
        case Notice() as notice:
            return NoticeItem(
                id=notice.id,
                seq=seq,
                at=at,
                bubbles=tuple(split_message_bubbles(notice.text)),
                tool_data=notice.tool_data,
                timeline=tool_timeline(notice.tool_data),
                follow_up_actions=notice.follow_up_actions,
            )
        case WorkflowFired() as fired:
            return WorkflowFiredItem(id=fired.id, seq=seq, at=at, workflow=fired.run.workflow)
        case TodoWoke() as woke:
            return TodoWokeItem(id=woke.id, seq=seq, at=at, wake=woke.run.wake)
        # Shown through the items they change, or not at all.
        case (
            WorkStarted()
            | StopRequested()
            | BargeIn()
            | ApprovalRequested()
            | ApprovalDecided()
            | WorkFinished()
            | ReplySettled()
            | IntegrationNeeded()
            | IntegrationConnected()
        ):
            return None
        case unhandled:
            assert_never(unhandled)


def work_timeline(
    handoff: ToolDataEntry | None,
    cards: Iterable[ToolDataEntry],
    approvals: Iterable[ApprovalRequestEntry],
) -> ToolTimeline:
    """Return the timeline a work item shows: its hand-off's card, its work's cards, then its approval cards."""
    asked: list[ToolDataEntry] = [
        {
            "tool_name": approval.tool_name,
            "tool_category": approval.tool_category,
            "data": approval.data.model_dump(mode="json"),
            "timestamp": approval.timestamp,
        }
        for approval in approvals
    ]
    return tool_timeline((*(() if handoff is None else (handoff,)), *cards, *asked))


def _work_item(seq: int, at: AwareDatetime, task_id: str, read: _Log) -> WorkItem:
    started = read.started[task_id]
    finished = read.finished.get(task_id)
    cards = () if finished is None else finished.tool_data
    handoff = None if started.handoff is None else read.handoffs.get(started.handoff)
    approvals = read.approvals(task_id)
    return WorkItem(
        id=f"work:{task_id}",
        seq=seq,
        at=at,
        task_id=task_id,
        status=read.work_status(task_id),
        asking=read.asking(task_id),
        asked_seq=max(
            (read.request_seqs[request.approval_id] for request in read.asking(task_id)),
            default=0,
        ),
        approvals=approvals,
        handoff=handoff,
        tool_data=cards,
        timeline=work_timeline(handoff, cards, approvals),
        image=None if finished is None else finished.image,
        retry_target=read.newest_asked(started.answers),
    )


def _narrates(reply: Reply, settle: ReplySettled | None, read: _Log) -> tuple[str, ...]:
    named = (*reply.narrates, *(settle.narrates if settle is not None else ()))
    # Logs written before narrates was explicit keyed the narrating reply by its task.
    if not named and reply.reply_id in read.finished:
        named = (reply.reply_id,)
    return tuple(dict.fromkeys(named))


def _reply_item(seq: int, at: AwareDatetime, reply: Reply, read: _Log) -> ReplyItem | None:
    settled_at = read.settles.get(reply.reply_id)
    settle = None if settled_at is None else settled_at.entry
    # An imported reply that never settled is a folded emoji_ack's placeholder.
    if reply.imported and settle is None:
        return None
    narrates = _narrates(reply, settle, read)
    work_cards = [
        card for task in narrates if (work := read.finished.get(task)) for card in work.tool_data
    ]
    own = [card for card in reply.tool_data if not _is_handoff(card) and card not in work_cards]
    failed = settle is not None and settle.outcome is ReplyOutcome.FAILED
    if not (reply.text or own or reply.image):
        if not failed or settled_at is None:
            return None
        # Nothing was shown before it failed: it appears where the failure was logged.
        seq, at = settled_at.seq, settled_at.at
    target = reply.quote_target if settle is None else settle.quote_target
    quoted = None if target is None else read.users.get(target)
    shown = tuple(own)
    return ReplyItem(
        id=reply.reply_id,
        seq=seq,
        at=at,
        bubbles=tuple(split_message_bubbles(reply.text)),
        tool_data=shown,
        timeline=tool_timeline(shown),
        follow_up_actions=reply.follow_up_actions,
        image=reply.image,
        pinned=reply.pinned,
        quote=None
        if quoted is None
        else ReplyToMessageData(id=quoted.id, content=quoted.text, role="user"),
        outcome=None if settle is None else settle.outcome,
        failure=None if settle is None else settle.failure,
        narrates=narrates,
        retry_target=read.newest_asked(
            (*(() if settle is None else settle.answers), *(() if target is None else (target,)))
        ),
        files=reply_files([*work_cards, *reply.tool_data]),
    )
