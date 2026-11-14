"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.constants.hil import ApprovalDecision
from app.models.document_models import MongoDocument
from shared.py.approvals import ActionResult, ApprovalOutcome

# The three global approval modes. Launch switch: the default stays
# ``always_allow`` (HIL off — nothing gated) until we flip it post-launch.
HILMode = Literal["always_allow", "always_ask", "auto"]
# once: this call only. always_tool: also set a "never ask" override for the tool.
ApprovalScope = Literal["once", "always_tool"]
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


class HILToolRiskUpdate(BaseModel):
    """Partial update for a tool-risk record (repository write model)."""

    model_config = ConfigDict(extra="forbid")

    is_destructive: bool | None = None
    rationale: str | None = None
    classified_at: datetime | None = None


class ApprovalProposal(BaseModel):
    """What a gated call proposes; the ledger mints the id and owns the state."""

    conversation_id: str
    user_id: str = ""
    fingerprint: str
    tool_name: str
    # HIL key (services/hil/tool_key) of the tool behind the call, for the card's
    # "always allow". None on rows registered before keys were MCP-scoped.
    tool_key: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    # The connected account the call acts as; None is the integration's primary.
    account: str | None = None
    summary: str = ""
    rationale: str = ""
    preview: str = ""
    owner_agent: str = ""
    # Background owner parked on this approval, for the resume driver: who to wake
    # when it decides ("workflow"|"todo" plus the id). Empty on live runs, which
    # resume through the executor inbox; set once at registration.
    owner_run_type: str = ""
    owner_id: str = ""
    proposing_run_id: str | None = None
    # The logged live work the approval holds; its request and every ending are log entries.
    # None only on rows registered before every run was logged work.
    task_id: str | None = None


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
    # None while pending; written explicitly so the live partial index can match null.
    outcome: ApprovalOutcome | None = None
    # What became of an approved action; None until it starts.
    action: ActionResult | None = None
    feedback: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    v: int = 0
    created_at: datetime | None = None
    # When the action started executing. The lazy reconciler treats an action still
    # executing past the cutoff as crashed (unknown) — never blind-retried.
    executing_started_at: datetime | None = None

    @property
    def standing(self) -> str:
        """Where the row stands in one word, for the model and logs; never stored."""
        return str(self.action or self.outcome or "pending")

    @property
    def live(self) -> bool:
        """Whether the row still holds its call: undecided, or approved and not yet started."""
        return self.outcome is None or (
            self.outcome is ApprovalOutcome.APPROVED and self.action is None
        )


# What a bot user's chat reply to pending approvals resolves to (services/hil/conversational.py).
DecisionAction = Literal[ApprovalDecision, "unrelated"]


class DecisionResult(BaseModel):
    """Classification of a user's reply to a single pending approval."""

    action: DecisionAction
    feedback: str | None = None


class BatchItemDecision(BaseModel):
    """One pending action's verdict from the user's reply."""

    index: int = Field(description="1-based index of the pending action")
    action: Literal[ApprovalDecision, "leave"]
    feedback: str | None = None


class BatchDecisionResult(BaseModel):
    """Classification of a reply against several pending approvals."""

    unrelated: bool = Field(
        description="True when the message is a new request, not an answer to the pending actions"
    )
    decisions: list[BatchItemDecision] = Field(default_factory=list)
