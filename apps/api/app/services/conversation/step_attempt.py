"""One comms attempt's state, and the reply, deltas and settle it shapes from what it streamed."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.models.conversation_frame_models import (
    FollowUpActionsEvent,
    MessageBoundaryEvent,
    ResponseEvent,
    StreamPayload,
    ToolDataEvent,
)
from app.models.conversation_log_models import (
    Batch,
    CommitReason,
    IntegrationConnected,
    LoggedEntry,
    MergeGroup,
    Reply,
    ReplySettled,
    StepClaim,
    UserMessage,
    VisibleEntry,
    WakingEntry,
    WorkFinished,
    WorkflowFired,
)
from app.services.conversation.placement import watermark
from app.services.conversation.ports import (
    Replied,
    RunOutcome,
)
from app.services.conversation.reply_text import ReplyText, bubble_deltas, screen_bubbles
from app.services.conversation.screen import handoff_call_id
from app.services.conversation.step_view import StepView
from app.services.conversation.tool_cards import fold_cards
from app.services.conversation.tool_timeline import tool_timeline
from app.services.conversation.verdict import merge_group, quote_target
from app.utils.file_links import FileLinks
from shared.py.conversation_wire import (
    CardsDelta,
    FailureReason,
    FollowUpsDelta,
    ReplyDelta,
    ReplyOutcome,
    ToolDataEntry,
)


@dataclass(frozen=True)
class Quiet:
    """Committed, with nothing shown to the user yet."""

    reason: CommitReason


@dataclass(frozen=True)
class Drafting:
    """Committed, having streamed only hand-offs, which the work's own bubble shows: the reply has no slot yet."""

    reply: Reply


@dataclass(frozen=True)
class Showing:
    """Committed, and the user reads this reply's text in its slot: its content is the fold of every delta shown."""

    reply: Reply


@dataclass
class Attempt:
    """One comms attempt: the inputs handed to its runs, the replies it settled, and how far it got."""

    claim: StepClaim
    run_id: str
    reply_id: str
    batch: Batch
    # Every input the runs were given, in log order.
    handed: tuple[LoggedEntry, ...]
    # The key of the attempt's ledger of open messages, which its runs' closing tools write.
    ledger: str
    # Highest seq examined for joiners.
    seen: int
    view: StepView
    # The log's head as the last verdict's hint read it: the view answers only while it reaches this.
    hint_head: int
    progress: Quiet | Drafting | Showing | None = None
    # Segments this attempt settled; the current one is the next.
    segment: int = 0
    # The seq the current segment's reply opened at, None until it opens.
    slot: int | None = None
    # The inputs the current segment's settle answers, set as it settles.
    covers: tuple[LoggedEntry, ...] = ()
    # Seqs of handed inputs a settled segment answered.
    answered_seqs: frozenset[int] = frozenset()
    # Inputs were handed below the open reply's slot: it can answer none of them, so it ends at
    # the next model-written signal and the next segment opens below them.
    split: bool = False
    # The runs were already told which messages are still open; this attempt never tells them twice.
    reminded: bool = False
    # The run ended owing messages: the attempt goes on in a run that is told which.
    continuing: bool = False
    # The id of the newest settle this attempt appended.
    last_settle: str | None = None
    # Waking entries after handed, of the batch's group, not past a Stop.
    joiners: tuple[LoggedEntry, ...] = ()
    # A Stop or another group's input ended the run of joinable entries.
    closed: bool = False
    deltas: int = 0
    # The current segment's text as it streamed, which its bubbles are split from.
    text: ReplyText = field(default_factory=ReplyText)
    # The bubbles clients were last sent: behind text while a take-back is held.
    shown: tuple[str, ...] = ()
    # The reply as settled once the answer was final; the run only adds follow-up suggestions after.
    answered: LoggedEntry | None = None

    def bubbles(self, links: FileLinks) -> tuple[str, ...]:
        """Return the current segment's bubbles as a client may see them while it streams."""
        return screen_bubbles(self.text.shown, self.claim.conversation_id, links)

    @property
    def attempt_id(self) -> str:
        """Return the id the current reply segment streams and settles under."""
        return self.run_id if self.segment == 0 else f"{self.run_id}/{self.segment}"

    def settled_view(self) -> StepView | None:
        """Return the view when its newest entry is this attempt's own settle, so it holds everything through it."""
        newest = self.view.entries[-1].entry if self.view.entries else None
        return self.view if newest is not None and newest.id == self.last_settle else None

    @property
    def committed(self) -> CommitReason | None:
        """Return why the attempt is committed, or None while it can still restart."""
        if isinstance(self.progress, Showing):
            return CommitReason.VISIBLE_TEXT
        if isinstance(self.progress, Drafting):
            return CommitReason.MODEL_OUTPUT
        return self.progress.reason if self.progress is not None else None

    @property
    def group(self) -> MergeGroup:
        """Return the merge group of the attempt's inputs."""
        return merge_group(waking_entry(self.batch.waking[0]))

    @property
    def through(self) -> int:
        """Return the newest seq below which every handed input is answered once covers settle."""
        return watermark(
            self.handed,
            self.answered_seqs | {logged.seq for logged in self.covers},
            self.batch.start - 1,
        )

    @property
    def unanswered(self) -> tuple[LoggedEntry, ...]:
        """Return the handed inputs no settled segment answered yet."""
        return tuple(logged for logged in self.handed if logged.seq not in self.answered_seqs)


def waking_entry(logged: LoggedEntry) -> WakingEntry:
    entry = logged.entry
    if isinstance(entry, UserMessage | WorkflowFired | WorkFinished | IntegrationConnected):
        return entry
    raise TypeError(f"seq {logged.seq} is a {entry.kind}, not a waking entry")


def reply_deltas(
    before: Reply,
    folded: Reply,
    payload: StreamPayload,
    shown: tuple[str, ...],
    bubbles: tuple[str, ...],
) -> list[ReplyDelta]:
    """Return what a client shows changing: bubble text, the follow-ups, or the cards and their timeline."""
    match payload:
        case ResponseEvent() | MessageBoundaryEvent():
            return [*bubble_deltas(shown, bubbles)]
        case FollowUpActionsEvent():
            return [FollowUpsDelta(follow_up_actions=folded.follow_up_actions)]
    cards = _own_cards(folded)
    if cards == _own_cards(before):
        return []
    return [CardsDelta(tool_data=cards, timeline=tool_timeline(cards))]


def _own_cards(reply: Reply) -> tuple[ToolDataEntry, ...]:
    """Return the cards the reply shows; a hand-off shows on its work."""
    return tuple(card for card in reply.tool_data if handoff_call_id(card) is None)


def final_reply(attempt: Attempt, outcome: RunOutcome) -> tuple[Reply, bool]:
    """Return what was shown, and whether it holds words or cards; a run's Replied content is used only when nothing it streamed stayed."""
    filled = base_reply(attempt)
    if isinstance(outcome, Replied) and not (filled.text or filled.tool_data):
        filled = filled.model_copy(
            update={
                "text": outcome.text,
                "tool_data": outcome.tool_data,
                "follow_up_actions": outcome.follow_up_actions,
            }
        )
    return filled, bool(filled.text or filled.tool_data)


def _settle_id(attempt: Attempt) -> str:
    return f"{attempt.attempt_id}:settled"


def settled_entry(
    attempt: Attempt,
    outcome: ReplyOutcome,
    answers: tuple[str, ...],
    through: int,
    quote: str | None,
    failure: FailureReason | None = None,
) -> ReplySettled:
    return ReplySettled(
        id=_settle_id(attempt),
        reply_id=attempt.reply_id,
        outcome=outcome,
        answers=answers,
        through=through,
        quote_target=quote,
        failure=failure,
        narrates=_narrated(attempt),
    )


def quote_in(
    answers: tuple[str, ...], reply_seq: int, entries: Sequence[LoggedEntry]
) -> str | None:
    settled = {
        logged.entry.reply_id: logged.entry.answers
        for logged in entries
        if isinstance(logged.entry, ReplySettled)
    }
    visible = [_visible(logged, settled) for logged in entries]
    return quote_target(answers, reply_seq, [item for item in visible if item is not None])


def _visible(logged: LoggedEntry, settled: Mapping[str, tuple[str, ...]]) -> VisibleEntry | None:
    match logged.entry:
        case UserMessage(id=message_id):
            return VisibleEntry(seq=logged.seq, id=message_id, is_user_message=True)
        case Reply(reply_id=reply_id, text=text) as reply if text or _own_cards(reply):
            return VisibleEntry(
                seq=logged.seq,
                id=reply_id,
                is_user_message=False,
                answers=settled.get(reply_id, ()),
            )
    return None


def is_text(payload: StreamPayload) -> bool:
    return isinstance(payload, ResponseEvent) and bool(payload.response)


def is_visible(payload: StreamPayload) -> bool:
    if isinstance(payload, ToolDataEvent):
        return handoff_call_id(payload.tool_data) is None
    return is_text(payload)


def _narrated(attempt: Attempt) -> tuple[str, ...]:
    """Return the tasks whose finished work the reply answers: its covers once named, until then every unanswered input."""
    return tuple(
        logged.entry.task_id
        for logged in attempt.covers or attempt.unanswered
        if isinstance(logged.entry, WorkFinished)
    )


def folded_reply(reply: Reply, payload: StreamPayload, text: ReplyText) -> Reply:
    """Return reply with one more shown delta folded in: its text so far, follow-ups, or what its cards show."""
    match payload:
        case ResponseEvent() | MessageBoundaryEvent():
            return reply.model_copy(update={"text": text.text})
        case FollowUpActionsEvent(follow_up_actions=actions):
            return reply.model_copy(update={"follow_up_actions": tuple(actions)})
    cards = fold_cards([payload], seed=reply.tool_data).tool_data
    return reply if cards == reply.tool_data else reply.model_copy(update={"tool_data": cards})


def empty_reply(attempt: Attempt) -> Reply:
    return Reply(
        id=f"{attempt.attempt_id}:reply",
        reply_id=attempt.reply_id,
        attempt_id=attempt.attempt_id,
        narrates=_narrated(attempt),
    )


def base_reply(attempt: Attempt) -> Reply:
    progress = attempt.progress
    return progress.reply if isinstance(progress, Showing | Drafting) else empty_reply(attempt)
