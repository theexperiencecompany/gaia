"""Repository for the llm_calls collection — one document per model call.

The permanent ledger of every priced LLM call, written from the one seam
both metering routes share (app.services.llm_metering._record). Answers what
usage_daily's per-day rollup cannot: which call, on what model, in which
conversation, under which agent. No prompt or completion text is stored —
counts and identifiers only.

Any COGS/spend query must filter on charge_to_budget: True is spend metered
against the user's allowance, False is background work done on their behalf
(counted for COGS, never charged) — only the charged half mirrors the Redis
budget windows and usage_daily.cost. created_at carries a 90-day TTL; the
durable per-day history stays in usage_daily, which this never replaces.
"""

from collections.abc import Sequence
from datetime import datetime
import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict
from pymongo import UpdateOne

from app.constants.general import EXECUTOR_THREAD_PREFIX, SPAWN_THREAD_PREFIX
from app.db.repositories.base import MongoDocument, MongoRepository

CostSource = Literal["provider", "table"]
CallStatus = Literal["ok", "error"]
#: Short, stable classification of WHY a provider call failed. Derived from
#: the exception type, never from its message — messages change without
#: warning and would fragment a dashboard into near-duplicates.
ErrorFamily = Literal["rate_limit", "timeout", "provider_unavailable", "invalid_request", "other"]

# EXECUTOR_THREAD_PREFIX puts the conversation uuid at the TAIL, SPAWN_THREAD_PREFIX
# in the MIDDLE (it appends a tool-call id) — hence separate regexes; the executor
# one anchors at the end so the LAST "executor_" wins over a multi-part integration prefix.
_EXECUTOR_THREAD_RE = re.compile(
    rf"^(?:[^\s]*_)?{re.escape(EXECUTOR_THREAD_PREFIX)}(?P<conversation_id>[^_\s]+)$"
)
_SPAWN_THREAD_RE = re.compile(
    rf"^{re.escape(SPAWN_THREAD_PREFIX)}(?P<conversation_id>[^_\s]+)_\S+$"
)


class LaneThread(NamedTuple):
    """A checkpoint thread id split into its two queryable halves."""

    conversation_id: str | None
    lane_thread: str | None


def split_lane_thread(thread_id: str | None) -> LaneThread:
    """Split a checkpoint thread id into the bare conversation id and its lane wrapper.

    Returns lane_thread=None for a plain thread, and both as None when thread_id
    is empty. Unsplit, spawned-subagent threads would fragment one conversation
    into one id per tool call.
    """
    if not thread_id:
        return LaneThread(None, None)
    for pattern in (_EXECUTOR_THREAD_RE, _SPAWN_THREAD_RE):
        match = pattern.match(thread_id)
        if match is not None:
            return LaneThread(match.group("conversation_id"), thread_id)
    return LaneThread(thread_id, None)


class LLMCallDocument(MongoDocument):
    """One priced model call, as it lands in the ledger.

    Every field is a count, a flag, a timestamp or an identifier. Adding a field
    that carries prompt or completion text — even a truncated preview — breaks
    the collection's one invariant.
    """

    created_at: datetime

    # --- who and which lane ---
    #: Absent on system lanes that run without a user (and on any path where the
    #: user id never reached the metering seam) — a real "nobody", not a default.
    user_id: str | None = None
    #: The lane label the ``llm_call`` wide event carries, verbatim.
    agent_name: str
    #: Auxiliary/background work GAIA chose to do, rather than the user's turn.
    background: bool
    #: Whether this spend counted against the user's daily allowance — see the
    #: module docstring: charged and uncharged rows answer different questions
    #: and must not be summed together.
    charge_to_budget: bool

    # --- what served it ---
    #: The model we asked for (the lane's configured id).
    model_requested: str
    #: The model the provider says answered. ``None`` when the response carried
    #: no model name.
    model_served: str | None = None
    #: The UPSTREAM that served the call, when named. Almost always ``None``:
    #: ChatOpenRouter drops OpenRouter's ``provider`` field, so
    #: ``generation_id`` is the handle that resolves it instead. Never guessed.
    provider: str | None = None

    # --- what it cost ---
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    #: Whether ``cost_usd`` is what the provider charged or what our price table
    #: guessed. The two disagree by more than 10x per upstream, so coverage of
    #: the reported price has to be measurable per call.
    cost_source: CostSource
    #: OpenRouter's generation id — the spot-audit handle back to the upstream.
    generation_id: str | None = None
    #: Why the provider stopped generating ("stop", "length", "tool_calls",
    #: "content_filter", …). A run of ``length`` across one lane is a truncation
    #: bug that otherwise only shows up as users reporting cut-off answers.
    finish_reason: str | None = None

    # --- how it ended ---
    #: ``"ok"`` or ``"error"`` (after retries exhausted); error rows are kept so
    #: an outage shows as a spike in failures, not a quiet drop in traffic.
    status: CallStatus = "ok"
    #: Set only on ``status="error"``. See :data:`ErrorFamily`.
    error_family: ErrorFamily | None = None

    # --- where it ran ---
    #: The TRUE conversation uuid, bare (see :func:`split_lane_thread`).
    conversation_id: str | None = None
    #: The wrapped checkpoint thread when the call ran on a child lane.
    lane_thread: str | None = None
    #: The agent tree this call belongs to; ``None`` for work not bounded by one.
    root_request_id: str | None = None
    workflow_id: str | None = None
    workflow_execution_id: str | None = None
    #: ARQ job identity, for calls made inside a worker task.
    job_id: str | None = None
    task_name: str | None = None
    #: The originating surface ("web", "discord", "telegram", "whatsapp",
    #: "slack", "voice", "workflow", "system"), threaded from the request —
    #: never inferred from agent name, since comms_agent serves every surface.
    channel: str | None = None

    # --- how long it took ---
    #: Wall time of the provider call. ``None`` where the seam cannot measure it
    #: (a message metered after the fact, not around its own invocation).
    duration_ms: float | None = None

    #: Deterministic identity derived from the log event a backfilled row was
    #: rebuilt from, making ``--apply`` re-runnable: a unique index turns a
    #: repeat insert into a no-op. Absent on live rows.
    backfill_key: str | None = None
    #: True for rows reconstructed by ``scripts/backfill_llm_calls.py`` rather
    #: than written live; their costs are re-derived and context ids are only
    #: as good as the log line, so precision-sensitive analysis can exclude them.
    backfilled: bool = False


class LLMCallUpdate(BaseModel):
    """No field is settable: the ledger is append-only.

    A recorded call is a historical fact. Nothing corrects one in place — a
    re-pricing writes its own record elsewhere (``usage_daily.cost_actual``).
    """

    model_config = ConfigDict(extra="forbid")


class LLMCallsRepository(MongoRepository[LLMCallDocument, LLMCallUpdate]):
    collection_name = "llm_calls"
    document_model = LLMCallDocument
    update_model = LLMCallUpdate
    uses_object_id = True
    # No cache: the ledger is write-heavy and append-only, and nothing reads a
    # call back by id — it is queried in ranges by the indexes below.
    cache_policy = None

    async def insert_backfilled(self, docs: Sequence[LLMCallDocument]) -> int:
        """Insert reconstructed rows, skipping any already present.

        Idempotent: each row's backfill_key plus $setOnInsert under a unique index
        turns a re-run into a no-op. ordered=False so one duplicate cannot abort the
        rest of the batch. Returns the number of rows actually created.
        """
        if not docs:
            return 0
        operations = [
            UpdateOne(
                {"backfill_key": doc.backfill_key},
                {"$setOnInsert": doc.model_dump(exclude={"id"}, exclude_none=True)},
                upsert=True,
            )
            for doc in docs
        ]
        result = await self._raw_collection().bulk_write(operations, ordered=False)
        return int(result.upserted_count)


llm_calls_repository = LLMCallsRepository()
