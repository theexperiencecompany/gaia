"""Repository for the ``llm_calls`` collection — one document per model call.

The permanent, queryable ledger of every priced LLM call, written from the one
seam both metering routes share (``app.services.llm_metering._record``). It
answers the questions ``usage_daily`` cannot: a per-day rollup knows what a user
spent, not *which* calls spent it, on what model, in which conversation, under
which agent — so today those answers only exist in log lines, which expire.

**No prompt or completion text is ever stored here.** Counts and identifiers
only. The whole point of a durable ledger is that it outlives a retention
window; message content must not.

**Any COGS or spend query must filter on ``charge_to_budget``.**
``charge_to_budget=True`` is spend the user asked for and was metered against
their allowance; ``False`` is background work GAIA chose to do on their behalf
(memory extraction, follow-ups, onboarding) which is recorded for COGS but never
charged. Summing ``cost_usd`` across both answers "what did this cost us", which
is a different question from "what was this user charged" — and only the charged
half mirrors the Redis budget windows and ``usage_daily.cost``.

``created_at`` carries a 90-day TTL (see ``create_llm_call_indexes``), which is
what keeps the collection bounded — the durable per-day money history stays in
``usage_daily``, which this never replaces.
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
#: Short, stable classification of WHY a provider call failed. Derived from the
#: exception type, never from its message: messages carry model ids, prompts
#: fragments and request ids, they change without warning, and grouping a
#: dashboard by them produces a long tail of near-duplicates instead of the five
#: buckets an operator actually acts on.
ErrorFamily = Literal["rate_limit", "timeout", "provider_unavailable", "invalid_request", "other"]

# A child agent runs on a WRAPPED checkpoint thread, and there are exactly two
# wrapping constructors in the codebase. Both anchor on a shared constant, so a
# drift in either is caught here rather than silently fragmenting the ledger:
#
#   ``executor_<conv>``                 subagent_runner.py, EXECUTOR_THREAD_PREFIX
#   ``<integration>_executor_<conv>``   handoff_tools.py wraps the above
#   ``spawn_<conv>_<tool_call_id>``     subagent.py, SPAWN_THREAD_PREFIX
#
# The conversation uuid is the TAIL of an executor thread but the MIDDLE of a
# spawn thread (a spawn appends its tool-call id, one thread per call), which is
# why they cannot share one pattern.
#
# The executor form is anchored at the end so the LAST ``executor_`` wins: a
# conversation id can never contain one, but a multi-part integration prefix
# can. Both rely on the conversation id itself holding no underscore — it is a
# uuid, and the same assumption the wrapping constructors already make when
# they join with one.
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

    Every wrapped shape returns the bare ``<conv>`` plus the full wrapped id as
    ``lane_thread``, so a ledger query can ask both "everything in this
    conversation" (across comms, executor and every spawn) and "only this lane".
    A plain conversation thread has no wrapper and returns ``lane_thread=None``.
    An empty/absent thread returns both as ``None`` rather than inventing an id.

    Spawned-subagent threads matter more than their ~1% share suggests: there is
    one per tool call, so a conversation that spawns work fragments into as many
    ids as it made calls, and each joins to nothing. That is the silent kind of
    wrong this collection exists to remove.
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
    #: Whether this spend counted against the user's daily allowance. Every
    #: spend query must filter on this — see the module docstring: charged and
    #: un-charged rows answer different questions and must not be summed
    #: together without meaning to.
    charge_to_budget: bool

    # --- what served it ---
    #: The model we asked for (the lane's configured id).
    model_requested: str
    #: The model the provider says answered. ``None`` when the response carried
    #: no model name.
    model_served: str | None = None
    #: The UPSTREAM that served the call, when the response names one. Almost
    #: always ``None`` today: ChatOpenRouter drops OpenRouter's ``provider``
    #: field and reports the literal aggregator name instead, so there is
    #: nothing honest to store — ``generation_id`` is the handle that resolves
    #: it. Never guessed from the model id.
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
    #: ``"ok"`` for a call the provider answered, ``"error"`` for one that
    #: raised after its retries were exhausted. Error rows exist because a
    #: failed call is still a fact about the system — without them the ledger
    #: describes only the calls that worked, and a provider outage looks like a
    #: quiet drop in traffic rather than a spike in failures.
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
    #: The surface the call originated from — "web", "discord", "telegram",
    #: "whatsapp", "slack", "voice", "workflow", "system". Threaded from the
    #: request/adapter that started the run, never inferred from the agent name
    #: (comms_agent serves every surface). ``None`` where the originating
    #: surface genuinely never reached the seam.
    channel: str | None = None

    # --- how long it took ---
    #: Wall time of the provider call. ``None`` where the seam cannot measure it
    #: (a message metered after the fact, not around its own invocation).
    duration_ms: float | None = None

    #: Deterministic identity of a backfilled row, derived from the log event it
    #: was rebuilt from. It is what makes ``--apply`` re-runnable: the same event
    #: always hashes to the same key, and a unique index turns a second insert
    #: into a no-op instead of a duplicate. Absent on live rows, which are
    #: written once by definition.
    backfill_key: str | None = None
    #: True for rows reconstructed from log history by
    #: ``scripts/backfill_llm_calls.py`` rather than written live. Their costs
    #: are re-derived and their context ids are only as good as the log line
    #: carried, so an analysis that needs first-party precision can exclude
    #: them; absent (falsey) on every live row.
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

        Idempotent by construction: each row carries a ``backfill_key`` derived
        from the log event it was rebuilt from, and ``$setOnInsert`` under a
        unique index means a re-run of ``--apply`` matches the existing document
        and writes nothing. Re-running a half-finished backfill is therefore
        safe and cheap, which matters because the run takes long enough to be
        interrupted.

        Returns the number of rows actually created. ``ordered=False`` so one
        duplicate cannot abort the rest of the batch.
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
