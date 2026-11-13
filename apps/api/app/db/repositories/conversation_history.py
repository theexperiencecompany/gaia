"""The projection of log entries into flat messages, for the screens that list them: search and pins.

A UserMessage is a user message, a Reply with its ReplySettled a bot message carrying its
outcome, a Notice a bot message, a TodoWoke or WorkflowFired the user-side message that woke
the run, and finished work with cards its own bubble until a reply answers that work (the
reply whose reply_id is its task_id carries them then). An approval card's status is derived
from the approval's entries; nothing rewrites it in place.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from app.constants.chat import BOT_MESSAGE_TYPE, USER_MESSAGE_TYPE
from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.chat_models import MessageReaction
from app.models.conversation_log_models import (
    ApprovalDecided,
    ApprovalRequested,
    EntryKind,
    LoggedEntry,
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
from app.models.conversation_models import ConversationEntry
from app.models.message_models import ReplyToMessageData
from app.models.tool_data_models import ToolDataEntry
from shared.py.analytics.catalog.hil import ApprovalOutcome

#: The kinds whose append advances a conversation's sync clock: each adds or ends a row a client shows.
SYNCED_KINDS: frozenset[str] = frozenset(
    {
        EntryKind.USER_MESSAGE,
        EntryKind.REPLY,
        EntryKind.REPLY_SETTLED,
        EntryKind.NOTICE,
        EntryKind.TODO_WOKE,
        EntryKind.WORKFLOW_FIRED,
        EntryKind.WORK_STARTED,
        EntryKind.WORK_FINISHED,
    }
)
#: The kinds a message read looks up beside its window.
RELATED_KINDS: frozenset[str] = frozenset(
    {
        EntryKind.REPLY_SETTLED,
        EntryKind.USER_MESSAGE,
        EntryKind.REPLY,
        EntryKind.APPROVAL_REQUESTED,
        EntryKind.APPROVAL_DECIDED,
        EntryKind.WORK_STARTED,
        EntryKind.WORK_FINISHED,
    }
)
#: The kinds whose text search reads and a pin marks.
TEXT_KINDS: frozenset[str] = frozenset({EntryKind.USER_MESSAGE, EntryKind.REPLY, EntryKind.NOTICE})
PINNABLE_KINDS: frozenset[str] = frozenset({EntryKind.USER_MESSAGE, EntryKind.REPLY})
_STOPPED_WORK = frozenset({WorkOutcome.CANCELLED, WorkOutcome.LOST})


@dataclass
class _Beside:
    """What the window's messages read from the entries around them."""

    settles: dict[str, ReplySettled] = field(default_factory=dict)
    users: dict[str, UserMessage] = field(default_factory=dict)
    replies: set[str] = field(default_factory=set)
    requests: dict[str, ApprovalRequested] = field(default_factory=dict)
    decisions: dict[str, ApprovalDecided] = field(default_factory=dict)
    finished: dict[str, WorkFinished] = field(default_factory=dict)
    # Detached work's task ids: its bubble sits at its WorkStarted, where the live view placed it.
    detached: set[str] = field(default_factory=set)

    @classmethod
    def of(cls, entries: Iterable[LoggedEntry]) -> _Beside:
        beside = cls()
        for logged in entries:
            match logged.entry:
                case ReplySettled() as settled:
                    beside.settles[settled.reply_id] = settled
                case UserMessage() as message:
                    beside.users[message.id] = message
                case Reply(reply_id=reply_id):
                    beside.replies.add(reply_id)
                case ApprovalRequested() as request:
                    beside.requests[request.approval_id] = request
                # Read order is not seq order: the restatement that carries the action's end wins.
                case ApprovalDecided() as decision if (
                    decision.action is not None or decision.approval_id not in beside.decisions
                ):
                    beside.decisions[decision.approval_id] = decision
                case WorkFinished() as work:
                    beside.finished[work.task_id] = work
                case WorkStarted(detached=True) as started:
                    beside.detached.add(started.task_id)
                case _:
                    pass
        return beside


def needed_beside(
    window: Sequence[LoggedEntry], related: Sequence[LoggedEntry] = ()
) -> tuple[list[str], list[str]]:
    """Return the entry ids and reply ids the window's messages still need beside related.

    Each answer can name more (a settle's quote, a request's work), so a read asks until none is left.
    """
    read = [*window, *related]
    present = {logged.entry.id for logged in read}
    beside = _Beside.of(read)
    wanted = {target for logged in read if (target := _quote_target(logged.entry)) is not None}
    for logged in window:
        for approval_id in _card_approvals(logged.entry):
            wanted |= {
                f"approval:{approval_id}",
                f"approval:{approval_id}:decided",
                f"approval:{approval_id}:acted",
            }
    for request in beside.requests.values():
        wanted |= {f"work:{request.task_id}:finished", f"work:{request.task_id}:lost"}
    for logged in window:
        match logged.entry:
            case WorkStarted(detached=True, task_id=task_id):
                wanted |= {f"work:{task_id}:finished", f"work:{task_id}:lost"}
            case WorkFinished(task_id=task_id):
                wanted.add(f"work:{task_id}")
            case _:
                pass
    replies = {
        logged.entry.reply_id
        for logged in window
        if isinstance(logged.entry, Reply) and logged.entry.reply_id not in beside.settles
    }
    replies |= {
        logged.entry.task_id
        for logged in window
        if isinstance(logged.entry, WorkFinished) and logged.entry.task_id not in beside.replies
    }
    return sorted(wanted - present), sorted(replies)


def project(
    window: Sequence[LoggedEntry], related: Iterable[LoggedEntry] = ()
) -> list[ConversationEntry]:
    """Project the window's entries, in order, into messages; related supplies what they read beside them."""
    beside = _Beside.of([*window, *related])
    return [message for logged in window if (message := _message(logged, beside)) is not None]


def _message(logged: LoggedEntry, beside: _Beside) -> ConversationEntry | None:
    seq, date = logged.seq, logged.at.isoformat()
    match logged.entry:
        case UserMessage() as message:
            return ConversationEntry(
                seq=seq,
                date=date,
                type=USER_MESSAGE_TYPE,
                response=message.text,
                message_id=message.id,
                fileIds=list(message.file_ids),
                fileData=list(message.files),
                selectedTool=message.selected_tool,
                toolCategory=message.tool_category,
                selectedWorkflow=message.selected_workflow,
                selectedCalendarEvent=message.selected_calendar_event,
                replyToMessage=message.reply_to_message or _quote(beside, message.reply_to),
                reaction=_reaction(message),
                platform_message_id=message.platform_message_id,
                first_contact=message.first_contact or None,
                pinned=message.pinned or None,
                todo_run_wake=message.todo_run_wake,
            )
        # An imported reply with nothing in it is a folded emoji_ack that already held a seq.
        case Reply() as reply if not reply.imported or reply.text or reply.tool_data or reply.image:
            settled = beside.settles.get(reply.reply_id)
            target = reply.quote_target if settled is None else settled.quote_target
            return ConversationEntry(
                seq=seq,
                date=date,
                type=BOT_MESSAGE_TYPE,
                response=reply.text,
                message_id=reply.reply_id,
                tool_data=_cards(reply.tool_data, beside),
                follow_up_actions=list(reply.follow_up_actions) or None,
                image_data=reply.image,
                replyToMessage=_quote(beside, target),
                in_progress=True if settled is None else None,
                stopped=True if settled and settled.outcome is ReplyOutcome.STOPPED else None,
                error=settled.failure.value if settled and settled.failure else None,
                pinned=reply.pinned or None,
            )
        case Notice() as notice:
            return ConversationEntry(
                seq=seq,
                date=date,
                type=BOT_MESSAGE_TYPE,
                response=notice.text,
                message_id=notice.id,
                tool_data=_cards(notice.tool_data, beside),
                follow_up_actions=list(notice.follow_up_actions) or None,
            )
        case TodoWoke() as woke:
            return ConversationEntry(
                seq=seq,
                date=date,
                type=USER_MESSAGE_TYPE,
                response="",
                message_id=woke.id,
                todo_run_wake=woke.run.wake,
            )
        case WorkflowFired() as fired:
            return ConversationEntry(
                seq=seq,
                date=date,
                type=USER_MESSAGE_TYPE,
                response="",
                message_id=fired.id,
                selectedWorkflow=fired.run.workflow,
            )
        case WorkStarted(detached=True, task_id=task_id) if task_id in beside.finished:
            return _work_bubble(seq, date, beside.finished[task_id], beside)
        case WorkFinished() as work if work.task_id not in beside.detached:
            return _work_bubble(seq, date, work, beside)
        case _:
            return None


def _work_bubble(
    seq: int, date: str, work: WorkFinished, beside: _Beside
) -> ConversationEntry | None:
    """Show finished work no reply took: its cards, or that it stopped."""
    if work.task_id in beside.replies or not (work.tool_data or work.outcome in _STOPPED_WORK):
        return None
    return ConversationEntry(
        seq=seq,
        date=date,
        type=BOT_MESSAGE_TYPE,
        response="",
        message_id=f"work:{work.task_id}",
        tool_data=_cards(work.tool_data, beside),
        stopped=True if work.outcome in _STOPPED_WORK else None,
    )


def _card_approvals(entry: object) -> list[str]:
    match entry:
        case Reply(tool_data=cards) | Notice(tool_data=cards) | WorkFinished(tool_data=cards):
            return [approval for card in cards if (approval := _approval_of(card)) is not None]
        case _:
            return []


class _ApprovalCardData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approval_id: str | None = None


def _approval_of(card: ToolDataEntry) -> str | None:
    data = card["data"]
    if card["tool_name"] != APPROVAL_REQUEST_TOOL_NAME or not isinstance(data, dict):
        return None
    return _ApprovalCardData.model_validate(data).approval_id


def _cards(cards: Sequence[ToolDataEntry], beside: _Beside) -> list[ToolDataEntry] | None:
    """Return the cards with each logged approval's outcome as the log has it."""
    shown: list[ToolDataEntry] = []
    for card in cards:
        approval_id = _approval_of(card)
        ended = None if approval_id is None else _approval_end(approval_id, beside)
        shown.append(card if ended is None else {**card, "data": {**card["data"], **ended}})
    return shown or None


def _approval_end(approval_id: str, beside: _Beside) -> dict[str, str | None] | None:
    """Return a logged approval's outcome and decider; None leaves an approval the log never asked as created."""
    decision = beside.decisions.get(approval_id)
    if decision is not None:
        return {"outcome": decision.outcome, "decider": decision.decider, "action": decision.action}
    request = beside.requests.get(approval_id)
    if request is None:
        return None
    work = beside.finished.get(request.task_id)
    if work is not None and work.outcome in _STOPPED_WORK:
        return {"outcome": ApprovalOutcome.CANCELLED, "decider": None}
    return {"outcome": None, "decider": None}


def _quote_target(entry: object) -> str | None:
    match entry:
        case UserMessage(reply_to_message=None, reply_to=target):
            return target
        case Reply(quote_target=target) | ReplySettled(quote_target=target):
            return target
        case _:
            return None


def _quote(beside: _Beside, target: str | None) -> ReplyToMessageData | None:
    quoted = None if target is None else beside.users.get(target)
    if quoted is None:
        return None
    return ReplyToMessageData(id=quoted.id, content=quoted.text, role="user")


def _reaction(message: UserMessage) -> MessageReaction | None:
    reaction = message.reaction
    return None if reaction is None else MessageReaction(emoji=reaction.emoji, by=reaction.by)
