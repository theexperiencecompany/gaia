"""The one projection of a conversation's log into the messages a client receives.

A UserMessage is a user message, a Reply with its ReplySettled a bot message carrying its
outcome, a Notice a bot message, a TodoWoke or WorkflowFired the user-side message that woke
the run. Every other kind shapes no message of its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from app.constants.chat import BOT_MESSAGE_TYPE, USER_MESSAGE_TYPE
from app.models.chat_models import MessageReaction
from app.models.conversation_log_models import (
    EntryKind,
    LoggedEntry,
    Notice,
    Reply,
    ReplyOutcome,
    ReplySettled,
    TodoWoke,
    UserMessage,
    WorkflowFired,
)
from app.models.conversation_models import ConversationEntry
from app.models.message_models import ReplyToMessageData

#: The kinds a history window counts: each shapes one message.
MESSAGE_KINDS: frozenset[str] = frozenset(
    {
        EntryKind.USER_MESSAGE,
        EntryKind.REPLY,
        EntryKind.NOTICE,
        EntryKind.TODO_WOKE,
        EntryKind.WORKFLOW_FIRED,
    }
)
#: The kinds a message read looks up beside its window: the settles and the quoted user messages.
RELATED_KINDS: frozenset[str] = frozenset({EntryKind.REPLY_SETTLED, EntryKind.USER_MESSAGE})
#: The kinds whose text search reads and a pin marks.
TEXT_KINDS: frozenset[str] = frozenset({EntryKind.USER_MESSAGE, EntryKind.REPLY, EntryKind.NOTICE})
PINNABLE_KINDS: frozenset[str] = frozenset({EntryKind.USER_MESSAGE, EntryKind.REPLY})


def needed_beside(
    window: Sequence[LoggedEntry], related: Sequence[LoggedEntry] = ()
) -> tuple[list[str], list[str]]:
    """Return what the window's messages still need beside related: quoted user message ids, and unsettled reply ids.

    A settle's quote is the reply's final one, so a read that found settles asks again for their quotes.
    """
    read = [*window, *related]
    present = {logged.entry.id for logged in read}
    settled = {logged.entry.reply_id for logged in read if isinstance(logged.entry, ReplySettled)}
    quoted = {
        target
        for logged in read
        if (target := _quote_target(logged.entry)) is not None and target not in present
    }
    replies = [
        logged.entry.reply_id
        for logged in window
        if isinstance(logged.entry, Reply) and logged.entry.reply_id not in settled
    ]
    return sorted(quoted), replies


def project(
    window: Sequence[LoggedEntry], related: Iterable[LoggedEntry] = ()
) -> list[ConversationEntry]:
    """Project the window's entries, in order, into messages; related supplies settles and quoted messages."""
    beside = list(related)
    settles = {
        logged.entry.reply_id: logged.entry
        for logged in [*window, *beside]
        if isinstance(logged.entry, ReplySettled)
    }
    users = {
        logged.entry.id: logged.entry
        for logged in [*window, *beside]
        if isinstance(logged.entry, UserMessage)
    }
    return [
        message for logged in window if (message := _message(logged, settles, users)) is not None
    ]


def _message(
    logged: LoggedEntry,
    settles: Mapping[str, ReplySettled],
    users: Mapping[str, UserMessage],
) -> ConversationEntry | None:
    seq, date = logged.seq, logged.at.isoformat()
    match logged.entry:
        case UserMessage() as message:
            quote = message.reply_to_message or _quote(users, message.reply_to)
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
                replyToMessage=quote,
                reaction=_reaction(message),
                platform_message_id=message.platform_message_id,
                pinned=message.pinned or None,
            )
        case Reply() as reply:
            settled = settles.get(reply.reply_id)
            target = reply.quote_target if settled is None else settled.quote_target
            return ConversationEntry(
                seq=seq,
                date=date,
                type=BOT_MESSAGE_TYPE,
                response=reply.text,
                message_id=reply.reply_id,
                tool_data=list(reply.tool_data) or None,
                follow_up_actions=list(reply.follow_up_actions) or None,
                replyToMessage=_quote(users, target),
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
                tool_data=list(notice.tool_data) or None,
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
        case _:
            return None


def _quote_target(entry: object) -> str | None:
    match entry:
        case UserMessage(reply_to_message=None, reply_to=target):
            return target
        case Reply(quote_target=target) | ReplySettled(quote_target=target):
            return target
        case _:
            return None


def _quote(users: Mapping[str, UserMessage], target: str | None) -> ReplyToMessageData | None:
    quoted = None if target is None else users.get(target)
    if quoted is None:
        return None
    return ReplyToMessageData(id=quoted.id, content=quoted.text, role="user")


def _reaction(message: UserMessage) -> MessageReaction | None:
    reaction = message.reaction
    return None if reaction is None else MessageReaction(emoji=reaction.emoji, by=reaction.by)
