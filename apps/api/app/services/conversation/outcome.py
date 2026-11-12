"""What became of one waking entry, read off the log: the reply that last answered it and the work it caused.

A producer that must know how its input ended (a workflow fire's job) appends it, then
awaits its outcome here instead of waiting on the run that answers it.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from app.models.conversation_frame_models import EntryFrame, EntryUpdatedFrame, StateFrame
from app.models.conversation_log_models import (
    ConversationState,
    LoggedEntry,
    Reply,
    ReplyOutcome,
    ReplySettled,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.event_stream import latest_frame_id, read_frames
from app.services.conversation.ports import ConversationLog

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
    entry_id: str, seq: int, entries: Sequence[LoggedEntry], state: ConversationState
) -> EntryOutcome | None:
    """Return the entry's outcome once nothing it caused is still running or unanswered; else None.

    entries are the log from seq on, with their current content.
    """
    if (
        seq in state.unsettled_waking
        or any(entry_id in work.answers for work in state.work)
        or any(entry_id in work.answers for work in state.finished_work)
    ):
        return None
    started = [e.entry for e in entries if isinstance(e.entry, WorkStarted)]
    tasks = {work.joins or work.task_id for work in started if entry_id in work.answers}
    finished = tuple(
        e.entry for e in entries if isinstance(e.entry, WorkFinished) and e.entry.task_id in tasks
    )
    settles = [
        e.entry
        for e in entries
        if isinstance(e.entry, ReplySettled) and entry_id in e.entry.answers
    ]
    if not settles:
        return EntryOutcome(settled=None, reply=None, work=finished)
    last = settles[-1]
    replies = [
        e.entry for e in entries if isinstance(e.entry, Reply) and e.entry.reply_id == last.reply_id
    ]
    return EntryOutcome(settled=last, reply=replies[-1] if replies else None, work=finished)


async def await_outcome(
    log: ConversationLog, conversation_id: str, user_id: str, logged: LoggedEntry, timeout: float
) -> EntryOutcome:
    """Wait until the appended entry's outcome is final; TimeoutError after timeout seconds.

    The log decides; the conversation's frames only say when to read it again.
    """
    cursor = await latest_frame_id(conversation_id)
    async with asyncio.timeout(timeout):
        while True:
            entries = await log.read_after(conversation_id, user_id, logged.seq - 1)
            state = await log.state(conversation_id, user_id)
            outcome = entry_outcome(logged.entry.id, logged.seq, entries, state)
            if outcome is not None:
                return outcome
            cursor = await _until_the_log_moves(conversation_id, cursor)


async def _until_the_log_moves(conversation_id: str, cursor: str) -> str:
    """Return the cursor after the next entry or state frame, or after a block that saw none."""
    while True:
        frames = await read_frames(conversation_id, cursor)
        if not frames:
            return cursor
        cursor = next((f.stream_id for f in reversed(frames) if f.stream_id is not None), cursor)
        if any(isinstance(f.frame, EntryFrame | EntryUpdatedFrame | StateFrame) for f in frames):
            return cursor
