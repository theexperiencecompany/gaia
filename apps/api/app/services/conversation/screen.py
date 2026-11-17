"""The one projection of a conversation's log into the screen every client renders.

An item sits at the seq it became visible at, so appending to the log only adds items at
the end or changes items already shown: nothing shown ever moves. Live and reloaded
screens are this same function of the same log.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, assert_never

from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.constants.conversation import REPLY_FAILURE_LINE
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.hil import (
    APPROVAL_REQUEST_TOOL_NAME,
    APPROVAL_TOOL_CATEGORY,
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
from app.services.conversation.reply_text import screen_bubbles
from app.services.conversation.tool_timeline import tool_timeline
from app.utils.file_links import FileLinks
from shared.py.approvals import ApprovalOutcome, ApprovalStatus
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
#: The log's time before its first entry.
_BEFORE_ANY_ENTRY = datetime.min.replace(tzinfo=UTC)


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
    stopped_through: int = 0
    # The newest entry's time: the screen is a function of the log alone, so its clock is the log's.
    latest: AwareDatetime = _BEFORE_ANY_ENTRY

    @classmethod
    def of(cls, entries: Iterable[Positioned]) -> _Log:
        read = cls()
        for logged in entries:
            read.latest = max(read.latest, logged.at)
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
                case StopRequested(covers_through=covers):
                    through = logged.seq - 1 if covers is None else covers
                    read.stopped_through = max(read.stopped_through, through)
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
        asked_at = self.request_ats[request.approval_id]
        return ApprovalRequestEntry(
            tool_name=APPROVAL_REQUEST_TOOL_NAME,
            tool_category=APPROVAL_TOOL_CATEGORY,
            data=ApprovalRequestEntryData(
                approval_id=request.approval_id,
                tool_call_id=request.tool_call_id,
                gated_tool_name=request.gated_tool_name,
                integration_name=request.integration_name,
                description=request.description,
                args_preview=request.args_preview,
                status=self.status(request),
                outcome=None if decision is None else decision.outcome,
                decider=None if decision is None else decision.decider,
                action=None if decision is None else decision.action,
                feedback=None if decision is None else decision.feedback,
                auto_reason=request.auto_reason,
                asked_at=asked_at,
                always_asks=request.always_asks,
            ),
            timestamp=asked_at.isoformat(),
        )

    def status(self, request: ApprovalRequested) -> ApprovalStatus:
        return approval_status(
            request,
            self.decisions.get(request.approval_id),
            ended_by=self._ended_by(self.root(request.task_id)),
            now=self.latest,
        )

    def _ended_by(self, root: str) -> ApprovalStatus | None:
        """Return how work under root let its undecided approvals go: a Stop cancels them, a failed run withdraws them.

        A run done while they wait leaves them to the user: the decision carries them out.
        """
        finished = self.finished.get(root)
        if self._stopped(root) or (finished is not None and finished.outcome in _STOPPED_WORK):
            return ApprovalStatus.CANCELLED
        if finished is not None and finished.outcome is not WorkOutcome.DONE:
            return ApprovalStatus.WITHDRAWN
        return None

    def _stopped(self, root: str) -> bool:
        started = self.started.get(root)
        return started is not None and started.cause_through <= self.stopped_through

    def asking(self, root: str) -> tuple[ApprovalRequested, ...]:
        """Return the approvals work under root waits on, oldest first, its run ended or not."""
        return tuple(
            request
            for request in self.requests.values()
            if self.root(request.task_id) == root and self.status(request) is ApprovalStatus.WAITING
        )

    def original(self, message_id: str) -> str:
        """Return the user message a retry answers again, or message_id when it is no retry."""
        message = self.users.get(message_id)
        return message.retry_of if message is not None and message.retry_of else message_id

    def newest_asked(self, answered: Iterable[str]) -> str | None:
        """Return the newest user message among answered: the one a retry sends again."""
        ids = {self.original(message_id) for message_id in answered}
        return next((user for user in reversed(self.users) if user in ids), None)

    def work_status(self, root: str) -> WorkStatus:
        if self.asking(root):
            return WorkStatus.AWAITING_APPROVAL
        finished = self.finished.get(root)
        return WorkStatus.RUNNING if finished is None else WorkStatus(finished.outcome.value)


def decided_status(decision: ApprovalDecided) -> ApprovalStatus:
    """Return the status a logged decision gives its approval: a yes that carries a change is approved with it."""
    if decision.outcome is ApprovalOutcome.APPROVED and decision.feedback:
        return ApprovalStatus.APPROVED_WITH_CHANGE
    return ApprovalStatus(decision.outcome.value)


def approval_status(
    request: ApprovalRequested,
    decision: ApprovalDecided | None,
    *,
    ended_by: ApprovalStatus | None,
    now: datetime,
) -> ApprovalStatus:
    """Return where an approval stands: its decision, else how its work let it go, else whether its time ran out.

    ended_by is None while the work still waits on the approval.
    """
    if decision is not None:
        return decided_status(decision)
    if ended_by is not None:
        return ended_by
    if request.expires_at is not None and request.expires_at < now:
        return ApprovalStatus.EXPIRED
    return ApprovalStatus.WAITING


def project_screen(
    conversation_id: str, entries: Sequence[Positioned], links: FileLinks
) -> list[ScreenItem]:
    """Return the screen for entries (ascending by seq): every visible item, at the seq it became visible."""
    read = _Log.of(entries)
    items: list[ScreenItem] = []
    for logged in entries:
        item = _item(conversation_id, logged, read, links)
        if item is not None:
            items.append(item)
    # Only a reply that became visible by failing sits at a later seq than its own entry.
    items.sort(key=lambda item: item.seq)
    return items


def text_item(
    conversation_id: str, logged: Positioned, related: Iterable[Positioned], links: FileLinks
) -> UserItem | ReplyItem | NoticeItem | None:
    """Return the item a message shows on its conversation's screen, reading related for what sits beside it."""
    item = _item(conversation_id, logged, _Log.of([*related, logged]), links)
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
    wanted |= {message.retry_of for message in read.users.values() if message.retry_of}
    present = {logged.entry.id for logged in (*window, *related)}
    return sorted(wanted - present), sorted(replies)


def _item(
    conversation_id: str, logged: Positioned, read: _Log, links: FileLinks
) -> ScreenItem | None:
    seq, at = logged.seq, logged.at
    match logged.entry:
        case UserMessage(retry_of=None) as message:
            return UserItem(id=message.id, seq=seq, at=at, message=message)
        case Reply() as reply:
            return _reply_item(conversation_id, seq, at, reply, read, links)
        case WorkStarted(task_id=task_id) if read.root(task_id) == task_id:
            return _work_item(seq, at, task_id, read)
        case Notice() as notice:
            return NoticeItem(
                id=notice.id,
                seq=seq,
                at=at,
                bubbles=screen_bubbles(notice.text, conversation_id, links),
                tool_data=notice.tool_data,
                timeline=tool_timeline(notice.tool_data),
                follow_up_actions=notice.follow_up_actions,
            )
        case WorkflowFired() as fired:
            return WorkflowFiredItem(id=fired.id, seq=seq, at=at, workflow=fired.run.workflow)
        case TodoWoke() as woke:
            return TodoWokeItem(id=woke.id, seq=seq, at=at, wake=woke.run.wake)
        # Shown through the items they change, or not at all.
        # A retry answers its message again in that message's bubble.
        case (
            UserMessage()
            | WorkStarted()
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
        case _:
            assert_never(logged.entry)


def work_timeline(
    handoff: ToolDataEntry | None,
    cards: Iterable[ToolDataEntry],
    approvals: Iterable[ApprovalRequestEntry],
) -> ToolTimeline:
    """Return the timeline a work item shows: its hand-off's card, its work's cards, then its approval cards."""
    asked: list[ToolDataEntry] = [
        {
            "tool_name": approval.tool_name,
            # Approval cards are grouped: tool_timeline keeps only their data.
            "tool_category": approval.tool_category,  # pragma: no mutate — never read
            "data": approval.data.model_dump(mode="json"),
            "timestamp": approval.timestamp,  # pragma: no mutate — never read
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


def _reply_item(
    conversation_id: str,
    seq: int,
    at: AwareDatetime,
    reply: Reply,
    read: _Log,
    links: FileLinks,
) -> ReplyItem | None:
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
    quoted = None if target is None else read.users.get(read.original(target))
    shown = tuple(own)
    failure = None if settle is None else settle.failure
    return ReplyItem(
        id=reply.reply_id,
        seq=seq,
        at=at,
        bubbles=screen_bubbles(reply.text, conversation_id, links),
        tool_data=shown,
        timeline=tool_timeline(shown),
        follow_up_actions=reply.follow_up_actions,
        image=reply.image,
        pinned=reply.pinned,
        quote=None
        if quoted is None
        else ReplyToMessageData(id=quoted.id, content=quoted.text, role="user"),
        outcome=None if settle is None else settle.outcome,
        failure=failure,
        failure_line=None if failure is None else REPLY_FAILURE_LINE[failure],
        narrates=narrates,
        retry_target=read.newest_asked(
            (*(() if settle is None else settle.answers), *(() if target is None else (target,)))
        ),
        files=reply_files(
            [*work_cards, *reply.tool_data], links.conversation_page(conversation_id)
        ),
    )
