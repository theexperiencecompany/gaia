"""What became of one waking entry, read off the log: the reply that last answered it and the work it caused.

A producer that must know how its input ended (a workflow fire's job) appends it, then
awaits its outcome here instead of waiting on the run that answers it.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame, StateFrame
from app.models.conversation_lifecycle_models import (
    Lifecycles,
    Message,
    MessageAnswered,
    MessageFailed,
)
from app.models.conversation_log_models import (
    ConversationState,
    LoggedEntry,
    Reply,
    ReplySettled,
    WorkFinished,
    WorkOutcome,
)
from app.services.conversation.event_stream import (
    UnreadableFrames,
    latest_frame_id,
    read_frames,
)
from app.services.conversation.lifecycle import fold
from app.services.conversation.ports import ConversationLog
from shared.py.conversation_wire import ReplyOutcome

_ReplyEntry = TypeVar("_ReplyEntry", Reply, ReplySettled)

#: A Stop dropped the entry, or the work it caused, before it was answered.
STOPPED = "stopped"


@dataclass(frozen=True)
class EntryOutcome:
    """How an entry ended: the last settle that answered it, that settle's reply, and its work's ends."""

    # None when a Stop dropped the entry before any reply answered it.
    settled: ReplySettled | None
    reply: Reply | None
    work: tuple[WorkFinished, ...]

    @property
    def failure(self) -> str | None:
        """Return why the entry was not carried out, with what its unfinished work reported; None when it was."""
        if self.settled is None or self.settled.outcome is ReplyOutcome.STOPPED:
            return STOPPED
        if self.settled.failure is not None:
            return self.settled.failure.value
        unfinished = [work for work in self.work if work.outcome is not WorkOutcome.DONE]
        if not unfinished:
            return None
        return f"work {unfinished[0].outcome.value}: {unfinished[0].report}"

    @property
    def text(self) -> str:
        """Return what the last answering reply said."""
        return self.reply.text if self.reply is not None else ""


def entry_outcome(
    entry_id: str, entries: Sequence[LoggedEntry], state: ConversationState
) -> EntryOutcome | None:
    """Return the entry's outcome once nothing it caused is still running or unanswered; else None.

    entries are the log from the entry's own seq, with their current content: all that answers it.
    """
    first = entries[0]
    if first.seq in state.unsettled_waking or entry_id in state.owed_answers:
        return None
    window = fold.fold_window(Lifecycles(), entries)
    owing = [message for message in window.messages.values() if _reports(message, entry_id)]
    tasks = {run.task_id for run in window.runs.values() if entry_id in run.answers}
    work = tuple(
        e.entry for e in entries if isinstance(e.entry, WorkFinished) and e.entry.task_id in tasks
    )
    last = max(owing, key=lambda message: message.seq, default=None)
    if last is not None and last.live:
        return None
    match None if last is None else last.status:
        case MessageAnswered(reply_id=reply_id) | MessageFailed(reply_id=reply_id):
            settled = _last(entries, ReplySettled, reply_id)
            return EntryOutcome(settled=settled, reply=_last(entries, Reply, reply_id), work=work)
        case _:
            # Stopped, or a run that ended reporting nothing: no reply answered the entry.
            return EntryOutcome(settled=None, reply=None, work=work)


def _reports(message: Message, entry_id: str) -> bool:
    """Return whether message is the entry itself or the result of work it caused."""
    return message.id == entry_id or (
        message.result is not None and entry_id in message.result.answers
    )


def _last(
    entries: Sequence[LoggedEntry], kind: type[_ReplyEntry], reply_id: str
) -> _ReplyEntry | None:
    found = [e.entry for e in entries if isinstance(e.entry, kind) and e.entry.reply_id == reply_id]
    return found[-1] if found else None


async def await_outcome(
    log: ConversationLog, conversation_id: str, user_id: str, logged: LoggedEntry, timeout: float
) -> EntryOutcome:
    """Wait until the appended entry's outcome is final; TimeoutError after timeout seconds.

    The log decides; the conversation's frames only say when to read it again.
    """
    cursor = await latest_frame_id(conversation_id)
    async with asyncio.timeout(timeout):
        while True:
            # State before entries: whatever the state says has settled, the entries read after it hold.
            state = await log.state(conversation_id, user_id)
            entries = await log.read_after(conversation_id, user_id, logged.seq - 1)
            outcome = entry_outcome(logged.entry.id, entries, state)
            if outcome is not None:
                return outcome
            cursor = await _until_the_log_moves(conversation_id, cursor)


async def _until_the_log_moves(conversation_id: str, cursor: str) -> str:
    """Return the cursor after the next entry or state frame, or after a block that saw none."""
    while True:
        try:
            frames = await read_frames(conversation_id, cursor)
        except UnreadableFrames as unreadable:
            return unreadable.through  # it may be the entry waited on; the caller rereads the log
        if not frames:
            return cursor
        cursor = next((f.stream_id for f in reversed(frames) if f.stream_id is not None), cursor)
        if any(isinstance(f.frame, EntryFrame | EntryUpdatedFrame | StateFrame) for f in frames):
            return cursor
