"""What a comms attempt shows the model: log entries as stable-id thread messages, and the notes around them.

Every message made from an entry has the id LOG_MESSAGE_ID_PREFIX + entry id and
the entry's seq under additional_kwargs[LOG_SEQ], so re-sending a batch after a
restart upserts in place and the model sees each input once.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import BaseModel, ConfigDict

from app.agents.core.interruption import INTERRUPTION_MARKER, INTERRUPTION_SOURCE
from app.constants.chat import ARTIFACT_CARD, SUBAGENT_GROUP_TOOL_NAME
from app.constants.conversation import (
    ABSORBED_NOTE,
    ABSORBED_NOTE_SUFFIX,
    BARGE_IN_NOTE,
    INTEGRATION_CONNECTED_NOTE,
    LOG_MESSAGE_ID_PREFIX,
    LOG_SEQ,
    MESSAGE_HANDLE,
    NOTICE_DELIVERED_NOTE,
    REACTION_NOTE,
    REACTION_NOTE_SUFFIX,
    SERVER_RESTART_NOTE,
    WORK_CARD_LINE,
    WORK_CARD_MAKER,
    WORK_CARDS_NOTE,
    WORK_DONE_NOTE,
    WORK_UNFINISHED_NOTE,
    WORKFLOW_RUN_REQUEST,
)
from app.models.artifact_models import ArtifactCard
from app.models.chat_models import ReactionBy, tool_fields
from app.models.conversation_log_models import (
    Batch,
    IntegrationConnected,
    LoggedEntry,
    Notice,
    Reply,
    ReplySettled,
    StopRequested,
    UserMessage,
    WorkFinished,
    WorkflowFired,
    WorkOutcome,
)
from shared.py.conversation_wire import ReplyOutcome, ToolDataEntry

#: Every user message reads as its text.
AS_TYPED: Mapping[str, str] = MappingProxyType({})
#: additional_kwargs key record_interruption tags its marker with.
_SOURCE_KEY = "lc_source"


def entry_message_id(entry_id: str) -> str:
    """Return the thread message id of the log entry with entry_id."""
    return f"{LOG_MESSAGE_ID_PREFIX}{entry_id}"


def verbatim_message_ids(
    thread: Sequence[AnyMessage], inputs: Iterable[str], pinned: Sequence[LoggedEntry]
) -> list[str]:
    """Return the thread ids history summarization keeps word for word: inputs, and what the user pinned.

    A pinned reply keeps the text GAIA wrote between the last input logged before it and
    the first logged after it: its turn's words, whose messages carry no entry id.
    """
    kept = {entry_message_id(i) for i in inputs}
    kept |= {entry_message_id(p.entry.id) for p in pinned if isinstance(p.entry, UserMessage)}
    replies = [p.seq for p in pinned if isinstance(p.entry, Reply)]
    after = -1
    words: list[str] = []
    for message in [*thread, None]:
        seq = None if message is None else message.additional_kwargs.get(LOG_SEQ)
        if message is None or isinstance(seq, int):
            before = seq if isinstance(seq, int) else None
            if any(after < r and (before is None or r < before) for r in replies):
                kept.update(words)
            after, words = (before if before is not None else after), []
        elif isinstance(message, AIMessage) and message.text and message.id is not None:
            words.append(message.id)
    return sorted(kept)


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
        and not (logged not in batch.waking and _left_to_its_decision(logged))
        for message in entry_messages(logged, said)
    ]


def _left_to_its_decision(logged: LoggedEntry) -> bool:
    """Return True for a chat run's finish that its approval's decision carries on, so the next work reports."""
    entry = logged.entry
    return (
        isinstance(entry, WorkFinished)
        and entry.continued_by_decision
        and entry.outcome is WorkOutcome.DONE
    )


def absorbed_messages(
    entries: Sequence[LoggedEntry], said: Mapping[str, str]
) -> tuple[list[AnyMessage], tuple[LoggedEntry, ...]]:
    """Render entries absorbed into a running attempt up to the first Stop, with the entries that joined it.

    Absorbed user messages end with a note that the run's earlier request is still owed: read
    as a fresh turn, the newest message alone gets answered and the work in progress is dropped.
    """
    messages: list[AnyMessage] = []
    joined: list[LoggedEntry] = []
    for logged in entries:
        if isinstance(logged.entry, StopRequested):
            break
        messages.extend(entry_messages(logged, said))
        joined.append(logged)
    said_by_user = [logged for logged in joined if isinstance(logged.entry, UserMessage)]
    if said_by_user:
        messages.append(_message(said_by_user[-1], ABSORBED_NOTE, ABSORBED_NOTE_SUFFIX))
    return messages, tuple(joined)


def entry_messages(logged: LoggedEntry, said: Mapping[str, str] = AS_TYPED) -> list[AnyMessage]:
    """Return the messages one log entry shows the model; most bookkeeping entries show nothing."""
    entry = logged.entry
    if isinstance(entry, UserMessage):
        handle = MESSAGE_HANDLE.format(seq=logged.seq)
        message = _message(logged, f"{handle}{said.get(entry.id, entry.text)}")
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
        # Detached work that delivered its own result (a subagent, a browser job, a replay) says nothing.
        case WorkFinished(report="", note="", nothing_for_user=True):
            pass
        case WorkFinished(outcome=WorkOutcome.DONE) as finished:
            note = WORK_DONE_NOTE.format(report=_reported(finished))
        case WorkFinished(outcome=outcome) as finished if outcome is not WorkOutcome.CANCELLED:
            note = WORK_UNFINISHED_NOTE.format(outcome=outcome, report=_reported(finished))
        case Reply(heard_through=int() as heard_through, text=text):
            note = BARGE_IN_NOTE.format(heard=text[:heard_through])
        case Notice(text=text):
            note = NOTICE_DELIVERED_NOTE.format(text=text)
        case IntegrationConnected(integration_name=name):
            note = INTEGRATION_CONNECTED_NOTE.format(integration=name)
        # A dead holder's open reply is settled failed with no answers by recovery.
        case ReplySettled(outcome=ReplyOutcome.FAILED, answers=()):
            note = SERVER_RESTART_NOTE
    return note


def work_cards_note(finished: WorkFinished) -> str | None:
    """Return the note naming the cards a work's result shows, with the subagent that made each; None when it shows none."""
    makers = _subagent_names(finished.tool_data)
    counts: Counter[tuple[str, str]] = Counter()
    cards: tuple[ToolDataEntry, ...] = finished.tool_data
    for card in cards:
        data = card["data"]
        if card["tool_name"] not in tool_fields or _retracts_a_file(card):
            continue
        maker = makers.get(card.get("subagent_id") or "", "")
        counts[card["tool_name"], maker] += len(data) if isinstance(data, list) else 1
    if not counts:
        return None
    lines = [
        WORK_CARD_LINE.format(
            name=name, count=count, maker=WORK_CARD_MAKER.format(subagent=maker) if maker else ""
        )
        for (name, maker), count in counts.items()
    ]
    return WORK_CARDS_NOTE.format(cards="\n".join(lines))


def _retracts_a_file(card: ToolDataEntry) -> bool:
    """Return whether card is a deleted file's remove card, which shows nothing itself."""
    return (
        card["tool_name"] == ARTIFACT_CARD
        and ArtifactCard.model_validate(card["data"]).event == "remove"
    )


def _subagent_names(cards: Sequence[ToolDataEntry]) -> dict[str, str]:
    """Map each subagent the cards' groups hold, nested ones too, to its name."""
    names: dict[str, str] = {}
    groups = [card["data"] for card in cards if card["tool_name"] == SUBAGENT_GROUP_TOOL_NAME]
    while groups:
        group = groups.pop()
        if not isinstance(group, dict):
            continue
        credited = _CreditedSubagent.model_validate(group)
        if credited.subagent_name:
            names[credited.subagent_id] = credited.subagent_name
        groups.extend(credited.nested_subagents)
    return names


class _CreditedSubagent(BaseModel):
    """The part of a subagent group card that says who made the cards under it."""

    model_config = ConfigDict(extra="ignore")

    subagent_id: str
    subagent_name: str | None = None
    nested_subagents: list[object] = []


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
