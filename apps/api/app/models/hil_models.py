"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument

# The three global approval modes. The default applies at read time to every user
# who never chose a mode, so changing it moves all of them at once.
HILMode = Literal["always_allow", "always_ask", "auto"]
# once: this call only. always_tool: also set a "never ask" override for the tool.
ApprovalScope = Literal["once", "always_tool"]
HIL_DEFAULT_MODE: HILMode = "auto"


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


class LedgerState(StrEnum):
    """Where one ledger approval stands: the decision, then its execution."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    REVOKED = "revoked"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    # The user pressed Stop before deciding; REVOKED is the agent withdrawing it.
    CANCELLED = "cancelled"


LIVE_LEDGER_STATES = frozenset({LedgerState.PENDING, LedgerState.APPROVED})


class ApprovalDetail(BaseModel):
    """One labelled fact about a gated call, e.g. To: bob@x.com."""

    label: str
    value: str


class ApprovalDescription(BaseModel):
    """A gated call in plain words, rendered the same by web cards and bot prompts."""

    # Verb + object, e.g. "Send an email".
    action: str
    # The action with its target, for lists and the model: Send an email to bob@x.com: "Q3".
    headline: str
    # Closing verb for a single-action prompt, e.g. "send it".
    confirm: str
    details: list[ApprovalDetail]


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
