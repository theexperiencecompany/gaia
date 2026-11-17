"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants.hil import ApprovalDecision
from app.models.document_models import MongoDocument
from shared.py.approvals import ActionResult, ApprovalOutcome

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


class ApprovalDetail(BaseModel):
    """One labelled fact about a gated call, e.g. To: bob@x.com."""

    label: str
    value: str
    # Long text (an email body): the web card keeps it behind its details toggle.
    expandable: bool = False


class ApprovalDescription(BaseModel):
    """A gated call in plain words, rendered the same by web cards and bot prompts."""

    # Verb + object, e.g. "Send an email".
    action: str
    # The action as one sentence, for the card, lists and the model: Email bob@x.com about “Q3”.
    headline: str
    # What a single-action prompt asks: OK to email bob@x.com about “Q3”? None on entries
    # logged before questions were phrased; those read their headline.
    question: str | None = None
    # Closing verb, e.g. "send it".
    confirm: str
    # Facts the sentence does not already say.
    details: list[ApprovalDetail]
    # On a re-ask after "yes, but change X": the facts that differ from the call the user changed.
    changes: list[ApprovalDetail] = Field(default_factory=list)
    # The same change in words, e.g. Updated priority to high.
    change_note: str | None = None


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

    Uncached: rows are decision state read at low volume. A pending row leaves by a
    decision the conversation log took: the user's, the agent's revoke, a stop, or expiry.
    """

    approval_id: str
    # Set while a decision is being written and handed to the work, cleared once it was;
    # one older than the lease is a hand-off that failed, and the sweeper carries it out.
    delivering_since: datetime | None = None
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
