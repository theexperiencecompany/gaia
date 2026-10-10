"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.background.executor_queue import ExecutorRunItem
from app.db.repositories.base import MongoDocument
from app.models.agent_config import SubagentResumeItem


class HILApprovalStatus(StrEnum):
    """Where one approval stands. ``StrEnum`` because these values are already written
    to Mongo and streamed to the client as plain strings — the enum names them without
    changing a single stored document.

    ``AUTO_APPROVED`` means *decided without asking*, and nothing more. It does not mean
    the call ran: approvals are settled in their own graph node, and every tool — auto
    or not — is executed afterwards by the tool node.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ABANDONED = "abandoned"
    AUTO_APPROVED = "auto_approved"

    @property
    def settled(self) -> bool:
        """Whether the decision is final. Every status but ``PENDING`` is."""
        return self is not HILApprovalStatus.PENDING


# The three global approval modes. Launch switch: the default stays
# ``always_allow`` (HIL off — nothing gated) until we flip it post-launch.
HILMode = Literal["always_allow", "always_ask", "auto"]
HIL_DEFAULT_MODE: HILMode = "always_allow"


class DeclinedCallRecord(TypedDict):
    """What ``bridge.remember_declined_call`` stores in Redis for one declined call.

    Written and read by that one module, so it needs no runtime validation — the
    TypedDict is the shape contract both sides are checked against.
    """

    feedback: str | None
    # Present only on auto-mode refusals (absent on rows written before this
    # shipped, which correctly read as user-made).
    auto: NotRequired[bool]


class HilInterruptPayload(TypedDict, total=False):
    """What the HIL gate passes to interrupt() (gate.decide_tool_call).

    approval_ids is added when several gated calls park in one step (subagent_runner.merge_approvals).
    """

    type: str
    approval_id: str
    tool_name: str
    summary: str
    integration_name: str | None
    approval_ids: list[str]


class HilResumeDecision(TypedDict, total=False):
    """The Command(resume=...) value a decided approval wakes its gate with (resolution.py)."""

    status: str
    feedback: str | None
    scope: str
    approval_id: str


class HILPreferences(BaseModel):
    """Stored on the user document under ``hil_preferences``."""

    # always_allow: run everything. always_ask: pause for every destructive tool.
    # auto: an intent judge runs aligned calls and pauses the rest.
    mode: HILMode = HIL_DEFAULT_MODE
    # Explicit per-tool exceptions that win over ``mode`` in every mode:
    # tool name -> should-ask (True = always ask, False = always allow). Holds
    # only the tools the user explicitly flipped, so it stays small.
    tool_overrides: dict[str, bool] = Field(default_factory=dict)
    # Auto mode declines to judge these tools — they always get a card. The
    # deny-rule half of deny > ask > allow: explicit, per-user, no inference.
    never_auto_tools: list[str] = Field(default_factory=list)


class HILToolRiskRecord(MongoDocument):
    """Cached LLM classification for one CUSTOM-integration tool (Mongo
    ``hil_tool_risk``), for durability across restarts/processes.

    Supported/internal tools are never stored here — they resolve straight from
    the tool registry's ``destructive`` flag.
    """

    tool_name: str
    description_hash: str
    is_destructive: bool
    rationale: str = ""
    classified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class HILApprovalRecord(MongoDocument):
    """Durable record of one approval request (Mongo ``hil_approvals``).

    The decision source of truth and audit trail: who asked to run what, the
    decision, decider, and timing. The LangGraph checkpoint holds *graph* state;
    this holds *decision* state, so an approval survives a restart/deploy and a
    late or duplicate decision can be resolved exactly once against it.
    """

    approval_id: str
    user_id: str
    conversation_id: str
    stream_id: str
    tool_name: str
    tool_call_id: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    integration_name: str | None = None
    status: HILApprovalStatus = HILApprovalStatus.PENDING
    scope: str = "once"
    feedback: str | None = None
    # Why auto mode ran this without asking (the intent judge's own words). Empty for
    # anything the user decided — there the decision, not a rationale, is the record.
    auto_reason: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    # Serialized run context (executor_queue.build_run_item shape) written when
    # the executor pauses; a decision re-dispatches the run from it. Lives on the
    # record — not a TTL'd cache — so a decision can never outlive its context.
    resume_item: dict[str, Any] | None = None
    # Stamped when the resume run is dispatched; a decided record without it is
    # a crashed resume the sweep re-dispatches.
    resumed_at: datetime | None = None
    # Set at creation only when a background subagent raised this approval: its thread
    # and the SubagentResumeItem that rebuilds it, so any process can resume it on a
    # decision. dict[str, Any] on the read side for the same reason as resume_item.
    subagent_thread_id: str | None = None
    subagent_resume: dict[str, Any] | None = None

    def resume_payload(self) -> HilResumeDecision:
        """The Command(resume=...) value this decided record wakes its gate with.

        Abandoned resumes as a denial: the user moved on, the agent must not act.
        approval_id lets a gate sequence match its own decision on replay.
        """
        status = self.status
        return {
            "status": HILApprovalStatus.DENIED.value
            if status is HILApprovalStatus.ABANDONED
            else status.value,
            "feedback": self.feedback,
            "scope": self.scope,
            "approval_id": self.approval_id,
        }


class HILApprovalUpdate(BaseModel):
    """Partial ``$set`` update for an approval record (repository write model).

    Covers the post-creation stamps only — the decision transition itself goes
    through ``HilApprovalRepository.mark_decided`` because it is conditional on
    ``status == "pending"``, which a plain ``$set`` model cannot express.
    """

    model_config = ConfigDict(extra="forbid")

    # Typed on the write side only — set_resume_item is the sole writer, taking
    # an ExecutorRunItem. The read side (HILApprovalRecord) stays dict[str, Any]
    # deliberately: narrowing it would reject rows written before this type existed.
    resume_item: ExecutorRunItem | None = None
    resumed_at: datetime | None = None
    subagent_resume: SubagentResumeItem | None = None


class HILToolRiskUpdate(BaseModel):
    """Partial update for a tool-risk record (repository write model)."""

    model_config = ConfigDict(extra="forbid")

    is_destructive: bool | None = None
    rationale: str | None = None
    classified_at: datetime | None = None


class LedgerState(StrEnum):
    """Where one ledger approval stands. Separate enum from ``HILApprovalStatus``:
    the ledger has no expiry/timeout states and adds execution tracking — reusing
    the old enum would let timeout machinery read ledger rows and vice versa."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    REVOKED = "revoked"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    UNKNOWN = "unknown"


LIVE_LEDGER_STATES = frozenset({LedgerState.PENDING, LedgerState.APPROVED})


class ApprovalProposal(BaseModel):
    """What a gated call proposes; the ledger mints the id and owns the state."""

    conversation_id: str
    user_id: str = ""
    fingerprint: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    rationale: str = ""
    preview: str = ""
    owner_agent: str = ""
    blocked_by: list[str] = Field(default_factory=list)
    # Background owner parked on this approval, for the resume driver: who to wake
    # when it decides ("workflow"|"todo" plus the id). Empty on live runs, which
    # resume through the executor inbox; set once at registration.
    owner_run_type: str = ""
    owner_id: str = ""
    proposing_run_id: str | None = None


class ApprovalLedgerDocument(MongoDocument, ApprovalProposal):
    """One entry in the executor-free approval ledger (``approval_ledger``).

    Uncached and never expiring: rows are decision state read at low volume, and
    a pending row leaves only by user decision or agent revoke — never by timer.
    """

    approval_id: str
    # Whether a resume was already enqueued: the approve tap and any retry/reconnect
    # share it, so exactly one resume per approval. Every further resume needs a
    # fresh user approval (the human is the loop breaker).
    owner_resumed: bool = False
    state: LedgerState = LedgerState.PENDING
    feedback: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    v: int = 0
    created_at: datetime | None = None
    # When this row entered EXECUTING. The lazy reconciler treats EXECUTING
    # older than the cutoff as crashed (UNKNOWN) — never blind-retried.
    executing_started_at: datetime | None = None


# What a bot user's chat reply to pending approvals resolves to (services/hil/conversational.py).
DecisionAction = Literal["approve", "deny", "unrelated"]


class DecisionResult(BaseModel):
    """Classification of a user's reply to a single pending approval."""

    action: DecisionAction
    feedback: str | None = None


class BatchItemDecision(BaseModel):
    """One pending action's verdict from the user's reply."""

    index: int = Field(description="1-based index of the pending action")
    action: Literal["approve", "deny", "leave"]
    feedback: str | None = None


class BatchDecisionResult(BaseModel):
    """Classification of a reply against several pending approvals."""

    unrelated: bool = Field(
        description="True when the message is a new request, not an answer to the pending actions"
    )
    decisions: list[BatchItemDecision] = Field(default_factory=list)
