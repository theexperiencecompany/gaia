"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.repositories.base import MongoDocument

HILApprovalStatus = Literal[
    "pending", "approved", "denied", "timeout", "abandoned", "auto_approved"
]

# The three global approval modes. Launch switch: the default stays
# ``always_allow`` (HIL off — nothing gated) until we flip it post-launch.
HILMode = Literal["always_allow", "always_ask", "auto"]
HIL_DEFAULT_MODE: HILMode = "always_allow"


class HILPreferences(BaseModel):
    """Stored on the user document under ``hil_preferences``."""

    # always_allow: run everything. always_ask: pause for every destructive tool.
    # auto: an intent judge runs aligned calls and pauses the rest.
    mode: HILMode = HIL_DEFAULT_MODE
    # Explicit per-tool exceptions that win over ``mode`` in every mode:
    # tool name -> should-ask (True = always ask, False = always allow). Holds
    # only the tools the user explicitly flipped, so it stays small.
    tool_overrides: dict[str, bool] = Field(default_factory=dict)


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
    status: HILApprovalStatus = "pending"
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
    # Set only when a *detached background subagent* parked on this approval. The
    # subagent's graph is checkpointed under this deterministic thread id, so the
    # executor's wait_for_subagents join can rediscover and resume it after the
    # executor's own pause — durable state, never the in-process session. ``None`` for
    # every other approval (interactive tool calls, blocking handoffs).
    subagent_thread_id: str | None = None
    subagent_agent_name: str | None = None
    # Stamped by the join once the parked subagent has been resumed and its result
    # collected. Distinct from ``resumed_at`` (which records that a decision dispatched
    # the *executor*): a batch decision wakes the executor once, then each parked
    # subagent is collected individually across join rounds.
    subagent_collected_at: datetime | None = None


class HILApprovalUpdate(BaseModel):
    """Partial ``$set`` update for an approval record (repository write model).

    Covers the post-creation stamps only — the decision transition itself goes
    through ``HilApprovalRepository.mark_decided`` because it is conditional on
    ``status == "pending"``, which a plain ``$set`` model cannot express.
    """

    model_config = ConfigDict(extra="forbid")

    resume_item: dict[str, Any] | None = None
    resumed_at: datetime | None = None
    subagent_thread_id: str | None = None
    subagent_agent_name: str | None = None
    subagent_collected_at: datetime | None = None


class HILToolRiskUpdate(BaseModel):
    """Partial update for a tool-risk record (repository write model)."""

    model_config = ConfigDict(extra="forbid")

    is_destructive: bool | None = None
    rationale: str | None = None
    classified_at: datetime | None = None
