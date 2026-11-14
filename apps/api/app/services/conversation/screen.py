"""The one projection of a conversation's log into the screen every client renders.

An item sits at the seq it became visible at, so appending to the log only adds items at
the end or changes items already shown: nothing shown ever moves. Live and reloaded
screens are this same function of the same log.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

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
    Entry,
    Notice,
    Reply,
    ReplyOutcome,
    ReplySettled,
    TodoWoke,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
    WorkStarted,
)
from app.models.conversation_screen_models import (
    NoticeItem,
    ReplyItem,
    ScreenItem,
    TodoWokeItem,
    UserItem,
    WorkflowFiredItem,
    WorkItem,
    WorkStatus,
)
from app.models.message_models import ReplyToMessageData
from app.models.stream_events import ApprovalRequestEntry, ApprovalRequestEntryData
from app.models.tool_data_models import ToolDataEntry
from app.services.conversation.reply_files import reply_files
from shared.py.analytics.catalog.hil import ApprovalOutcome

#: The card a tool call streams; a hand-off is one whose call is call_executor.
TOOL_CALL_CARD = "tool_calls_data"
_STOPPED_WORK = frozenset({WorkOutcome.CANCELLED, WorkOutcome.LOST})


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
                text=notice.text,
                tool_data=notice.tool_data,
                follow_up_actions=notice.follow_up_actions,
            )
        case WorkflowFired() as fired:
            return WorkflowFiredItem(id=fired.id, seq=seq, at=at, workflow=fired.run.workflow)
        case TodoWoke() as woke:
            return TodoWokeItem(id=woke.id, seq=seq, at=at, wake=woke.run.wake)
        case _:
            return None


def _work_item(seq: int, at: AwareDatetime, task_id: str, read: _Log) -> WorkItem:
    started = read.started[task_id]
    finished = read.finished.get(task_id)
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
        approvals=read.approvals(task_id),
        handoff=None if started.handoff is None else read.handoffs.get(started.handoff),
        tool_data=() if finished is None else finished.tool_data,
        image=None if finished is None else finished.image,
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
    return ReplyItem(
        id=reply.reply_id,
        seq=seq,
        at=at,
        text=reply.text,
        tool_data=tuple(own),
        follow_up_actions=reply.follow_up_actions,
        image=reply.image,
        pinned=reply.pinned,
        quote=None
        if quoted is None
        else ReplyToMessageData(id=quoted.id, content=quoted.text, role="user"),
        outcome=None if settle is None else settle.outcome,
        failure=None if settle is None else settle.failure,
        narrates=narrates,
        files=reply_files([*work_cards, *reply.tool_data]),
    )
