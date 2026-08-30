"""Repository for the ``llm_calls`` collection — one document per model call.

The permanent, queryable ledger of every priced LLM call, written from the one
seam both metering routes share (``app.services.llm_metering._record``). It
answers the questions ``usage_daily`` cannot: a per-day rollup knows what a user
spent, not *which* calls spent it, on what model, in which conversation, under
which agent — so today those answers only exist in log lines, which expire.

**No prompt or completion text is ever stored here.** Counts and identifiers
only. The whole point of a durable ledger is that it outlives a retention
window; message content must not.

``created_at`` carries a 90-day TTL (see ``create_llm_call_indexes``), which is
what keeps the collection bounded — the durable per-day money history stays in
``usage_daily``, which this never replaces.
"""

from datetime import datetime
import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import MongoDocument, MongoRepository

CostSource = Literal["provider", "table"]

# A child agent runs on a WRAPPED checkpoint thread — ``executor_<conv>``, and
# for integration-triggered runs ``<integration>_executor_<conv>`` (see
# ``AgentConfigurable.thread_id``). The bare conversation uuid is the tail; the
# wrapper is what says which lane produced the call. Anchored at the end so the
# LAST ``executor_`` wins: a conversation id can never contain one, but a
# multi-part integration prefix can.
_LANE_THREAD_RE = re.compile(r"^(?:[^\s]*_)?executor_(?P<conversation_id>[^_\s]+)$")


class LaneThread(NamedTuple):
    """A checkpoint thread id split into its two queryable halves."""

    conversation_id: str | None
    lane_thread: str | None


def split_lane_thread(thread_id: str | None) -> LaneThread:
    """Split a checkpoint thread id into the bare conversation id and its lane wrapper.

    ``executor_<conv>`` / ``<integration>_executor_<conv>`` return the bare
    ``<conv>`` plus the full wrapped id as ``lane_thread``, so a ledger query can
    ask both "everything in this conversation" (across comms and executor) and
    "only the executor lane". A plain conversation thread has no wrapper and
    returns ``lane_thread=None``. An empty/absent thread returns both as ``None``
    rather than inventing an id.
    """
    if not thread_id:
        return LaneThread(None, None)
    match = _LANE_THREAD_RE.match(thread_id)
    if match is None:
        return LaneThread(thread_id, None)
    return LaneThread(match.group("conversation_id"), thread_id)


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
    #: Whether this spend counted against the user's daily allowance.
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

    # --- how long it took ---
    #: Wall time of the provider call. ``None`` where the seam cannot measure it
    #: (a message metered after the fact, not around its own invocation).
    duration_ms: float | None = None


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


llm_calls_repository = LLMCallsRepository()
