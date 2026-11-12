"""What a comms attempt shows the model: log entries as stable-id thread messages, and the notes around them.

Every message made from an entry has the id LOG_MESSAGE_ID_PREFIX + entry id and
the entry's seq under additional_kwargs[LOG_SEQ], so re-sending a batch after a
restart upserts in place and the model sees each input once.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from langchain_core.messages import AnyMessage, HumanMessage

from app.agents.core.interruption import INTERRUPTION_MARKER, INTERRUPTION_SOURCE
from app.constants.conversation import (
    BARGE_IN_NOTE,
    INTEGRATION_CONNECTED_NOTE,
    LOG_MESSAGE_ID_PREFIX,
    LOG_SEQ,
    NOTICE_DELIVERED_NOTE,
    REACTION_NOTE,
    REACTION_NOTE_SUFFIX,
    SERVER_RESTART_NOTE,
    WORK_DONE_NOTE,
    WORK_UNFINISHED_NOTE,
    WORKFLOW_RUN_REQUEST,
)
from app.models.chat_models import ReactionBy
from app.models.conversation_log_models import (
    BargeIn,
    Batch,
    IntegrationConnected,
    LoggedEntry,
    Notice,
    ReplyOutcome,
    ReplySettled,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
)

#: Every user message reads as its text.
AS_TYPED: Mapping[str, str] = MappingProxyType({})
#: additional_kwargs key record_interruption tags its marker with.
_SOURCE_KEY = "lc_source"


def entry_message_id(entry_id: str) -> str:
    """Return the thread message id of the log entry with entry_id."""
    return f"{LOG_MESSAGE_ID_PREFIX}{entry_id}"


def attempt_messages(
    batch: Batch,
    context: Sequence[LoggedEntry],
    thread: Sequence[AnyMessage],
    said: Mapping[str, str],
) -> list[AnyMessage]:
    """Render context and batch in seq order; a Stop the thread already records is not said twice.

    said maps a user message's or a workflow fire's id to what the model reads for it.
    """
    ordered = sorted([*context, *batch.waking], key=lambda logged: logged.seq)
    return [
        message
        for logged in ordered
        if not (isinstance(logged.entry, StopRequested) and _stop_recorded(thread, logged.seq))
        for message in entry_messages(logged, said)
    ]


def absorbed_messages(
    entries: Sequence[LoggedEntry], said: Mapping[str, str]
) -> tuple[list[AnyMessage], bool]:
    """Render entries absorbed into a running attempt up to the first Stop; True when a Stop was reached."""
    messages: list[AnyMessage] = []
    for logged in entries:
        if isinstance(logged.entry, StopRequested):
            return messages, True
        messages.extend(entry_messages(logged, said))
    return messages, False


def entry_messages(logged: LoggedEntry, said: Mapping[str, str] = AS_TYPED) -> list[AnyMessage]:
    """Return the messages one log entry shows the model; most bookkeeping entries show nothing."""
    entry = logged.entry
    if isinstance(entry, UserMessage):
        message = _message(logged, said.get(entry.id, entry.text))
        reaction = entry.reaction
        if reaction is None or reaction.by is not ReactionBy.JEV:
            return [message]
        note = REACTION_NOTE.format(emoji=reaction.emoji)
        return [message, _message(logged, note, REACTION_NOTE_SUFFIX)]
    if isinstance(entry, WorkflowFired):
        request = WORKFLOW_RUN_REQUEST.format(title=entry.run.workflow.title)
        return [_message(logged, said.get(entry.id, request))]
    if isinstance(entry, StopRequested):
        marker = _message(logged, INTERRUPTION_MARKER)
        marker.additional_kwargs[_SOURCE_KEY] = INTERRUPTION_SOURCE
        return [marker]
    note = _note_text(logged)
    return [] if note is None else [_message(logged, note)]


def _note_text(logged: LoggedEntry) -> str | None:
    """Return the note a non-message entry leaves the model, or None for one it never sees."""
    note: str | None = None
    match logged.entry:
        case WorkFinished(outcome=WorkOutcome.DONE) as finished:
            note = WORK_DONE_NOTE.format(report=_reported(finished))
        case WorkFinished(outcome=outcome) as finished if outcome is not WorkOutcome.CANCELLED:
            note = WORK_UNFINISHED_NOTE.format(outcome=outcome, report=_reported(finished))
        case BargeIn(heard_text=heard):
            note = BARGE_IN_NOTE.format(heard=heard)
        case Notice(text=text):
            note = NOTICE_DELIVERED_NOTE.format(text=text)
        case IntegrationConnected(integration_name=name):
            note = INTEGRATION_CONNECTED_NOTE.format(integration=name)
        # A dead holder's open reply is settled failed with no answers by recovery.
        case ReplySettled(outcome=ReplyOutcome.FAILED, answers=()):
            note = SERVER_RESTART_NOTE
    return note


def _reported(finished: WorkFinished) -> str:
    """Return the work's report with what the review of its declared outcome adds."""
    return "\n\n".join(part for part in (finished.report, finished.note) if part)


def _message(logged: LoggedEntry, text: str, suffix: str = "") -> HumanMessage:
    return HumanMessage(
        content=text,
        id=f"{entry_message_id(logged.entry.id)}{suffix}",
        additional_kwargs={LOG_SEQ: logged.seq},
    )


def _stop_recorded(thread: Sequence[AnyMessage], stop_seq: int) -> bool:
    """Return True when the thread already holds an interruption marker after every input older than the stop."""
    older = [
        index
        for index, message in enumerate(thread)
        if isinstance(seq := message.additional_kwargs.get(LOG_SEQ), int) and seq < stop_seq
    ]
    if not older:
        return False
    return any(
        message.additional_kwargs.get(_SOURCE_KEY) == INTERRUPTION_SOURCE
        for message in thread[older[-1] + 1 :]
    )
