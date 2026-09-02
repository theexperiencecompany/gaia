"""HIL preference + custom-tool classification documents."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.background.executor_queue import ExecutorRunItem
from app.db.repositories.base import MongoDocument


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
    the tool registry's ``destructive`` flag. A CLI-backed tool stores one record
    per command shape, since its single name covers every command it can run.
    """

    tool_name: str
    # md5 of what was classified: the tool's description, plus the CLI command shape
    # when the verdict is for one command rather than for the tool as a whole.
    description_hash: str
    is_destructive: bool
    # The classified command shape, for a CLI-backed tool whose one name covers every
    # command it can run (empty for every other tool). Stored in the clear because the
    # hash above is a key, not something a human reading a cached verdict can decode.
    command_shape: str = ""
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

    # Typed on the write side only. set_resume_item is the sole writer and takes
    # an ExecutorRunItem, so every write is controlled. HILApprovalRecord keeps
    # `dict[str, Any]` on the read side deliberately — narrowing a persisted
    # field would start rejecting rows written before this type existed.
    resume_item: ExecutorRunItem | None = None
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
