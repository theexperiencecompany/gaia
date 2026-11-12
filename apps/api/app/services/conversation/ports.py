"""The interfaces the conversation step runs against: the log, the comms run, frames, effects, approvals."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.constants.hil import ApprovalDecision
from app.models.conversation_frame_models import DeltaPayload, OutputFrame
from app.models.conversation_log_models import (
    Batch,
    CommsPhase,
    ConversationState,
    Effect,
    Entry,
    LoggedEntry,
    PreemptHint,
    RejectReason,
    Reply,
    StepClaim,
    UserMessage,
)
from app.models.tool_data_models import ToolDataEntry


class EntryRejected(Exception):
    """reduce refused the entry, so nothing was stored."""

    def __init__(self, reason: RejectReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ClaimLost(Exception):
    """The claim is no longer the conversation's current epoch, so the write was refused."""


@dataclass(frozen=True)
class Appended:
    """An entry at its seq, the states either side of it, and the effects its append must run."""

    logged: LoggedEntry
    previous: ConversationState
    state: ConversationState
    effects: tuple[Effect, ...]
    duplicate: bool


class ConversationLog(Protocol):
    """One conversation's ordered record, its folded state, and the step's claim on it."""

    async def append(self, conversation_id: str, user_id: str, entry: Entry) -> Appended:
        """Store entry at the next seq; the same id again returns the first result as a duplicate."""
        ...

    async def append_fenced(self, claim: StepClaim, entry: Entry) -> Appended:
        """Append only while claim holds the current epoch; raise ClaimLost otherwise."""
        ...

    async def amend(self, claim: StepClaim, entry: Reply | UserMessage) -> LoggedEntry:
        """Replace the stored entry with entry's id in place, fenced; content only, never state."""
        ...

    async def read_after(self, conversation_id: str, seq: int) -> Sequence[LoggedEntry]:
        """Return the entries after seq in order, with their current content."""
        ...

    async def state(self, conversation_id: str) -> ConversationState:
        """Return the conversation's current state."""
        ...

    async def claim(self, conversation_id: str, user_id: str) -> StepClaim | None:
        """Take the step with a new epoch, or None while another holder is alive."""
        ...

    async def release_if_caught_up(self, claim: StepClaim) -> bool:
        """Release when nothing waking is unsettled; atomic with append; ClaimLost on a stale epoch."""
        ...

    async def set_comms(self, claim: StepClaim, phase: CommsPhase) -> ConversationState:
        """Write the comms phase, fenced, and return the new state."""
        ...

    async def hint(self, conversation_id: str) -> PreemptHint:
        """Return the cheap preempt view; barge_reply_id is set only while that reply is open."""
        ...

    async def beat(self, claim: StepClaim) -> bool:
        """Renew the claim's liveness; False means it is lost."""
        ...


class CancelReason(StrEnum):
    """Why the step cancels a comms run, which decides what the run leaves in model memory."""

    RESTART = "restart"
    STOP = "stop"
    TRUNCATE = "truncate"
    LOST = "lost"


@dataclass(frozen=True)
class Streamed:
    """A visible delta of the reply: text, reasoning or a tool card."""

    payload: DeltaPayload


@dataclass(frozen=True)
class Summarized:
    """The summarization call ran; it shows nothing, but the attempt must not be paid for twice."""


@dataclass(frozen=True)
class ModelOutput:
    """The comms model node returned."""

    has_tool_calls: bool


@dataclass(frozen=True)
class Replied:
    """The run ended with a reply."""

    text: str
    tool_data: tuple[ToolDataEntry, ...] = ()
    follow_up_actions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reacted:
    """The run ended with a reaction on the newest covered user message instead of words."""

    emoji: str


@dataclass(frozen=True)
class Silent:
    """The run ended with nothing to say."""


RunOutcome = Replied | Reacted | Silent


@dataclass(frozen=True)
class Finished:
    """The run is done; yielded only once the run task has exited."""

    outcome: RunOutcome


RunEvent = Streamed | Summarized | ModelOutput | Finished


class CommsRun(Protocol):
    """One running comms attempt."""

    def events(self) -> AsyncIterator[RunEvent]:
        """Yield the run's events; Finished is last, and a failed run raises."""
        ...

    def absorb(self, entries: Sequence[LoggedEntry]) -> None:
        """Give the run more waking entries to include before its next model call."""
        ...

    async def cancel(self, reason: CancelReason) -> None:
        """Cancel the run and return only once it is certainly dead."""
        ...


class CommsRunner(Protocol):
    """Starts comms runs."""

    async def start(
        self, claim: StepClaim, batch: Batch, context: Sequence[LoggedEntry]
    ) -> CommsRun:
        """Start a run on batch; context is every entry since the last settled input the batch does not carry, given again on a restart."""
        ...


class Frames(Protocol):
    """The conversation's output stream to clients."""

    async def publish(self, conversation_id: str, frame: OutputFrame) -> None:
        """Publish one frame."""
        ...


class Effects(Protocol):
    """The side effects an append asks for."""

    async def kick(self, conversation_id: str, user_id: str) -> None:
        """Make sure a step runs for the conversation."""
        ...

    async def cancel_work(
        self, conversation_id: str, user_id: str, task_ids: tuple[str, ...]
    ) -> None:
        """Cancel exactly these tasks."""
        ...

    async def start_ack(self, conversation_id: str, user_id: str, message_id: str) -> None:
        """React to a just-accepted user message."""
        ...


class ApprovalReplies(Protocol):
    """Reads a typed reply on a button-less surface as an answer to pending approvals."""

    async def classify(
        self, conversation_id: str, user_id: str, message_text: str
    ) -> ApprovalDecision | None:
        """Return the decision the message gives, or None when it is not an answer."""
        ...


@dataclass(frozen=True)
class RuntimePorts:
    """Everything accept and advance touch outside their own logic."""

    log: ConversationLog
    runner: CommsRunner
    frames: Frames
    effects: Effects
    approvals: ApprovalReplies
    clock: Callable[[], datetime]
    tick: Callable[[], Awaitable[None]]
