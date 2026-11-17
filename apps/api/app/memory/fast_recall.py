"""The comms fast lane: a turn's memories in one budgeted step in front of the reply.

The query's embedding starts when the request arrives, on a hosted model, so it
runs alongside the rest of the turn's setup. It is matched against the user's
vectors held in process, and one Postgres query then returns the semantic hits,
the memories pinned by the background recall of the conversation's previous
exchange, and any memory sharing a word with the message. No rerank: it lowered
retrieval quality on LongMemEval and cost 2.3s p50 in prod.
"""

import asyncio
from collections.abc import Sequence
import time

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import TypeAdapter

from app.constants.memory import (
    FAST_RECALL_MAX_TOKENS,
    FAST_RECALL_MIN_SIMILARITY,
    FAST_RECALL_SEMANTIC_BUDGET_SECONDS,
    FAST_RECALL_SEMANTIC_K,
    MEMORY_RECALL_BLOCK_LIMIT,
    PRECOMPUTED_RECALL_KEY,
    PRECOMPUTED_RECALL_LIMIT,
    PRECOMPUTED_RECALL_TTL,
    QUERY_EMBEDDING_TTL_SECONDS,
)
from app.db.redis import redis_cache
from app.memory import hosted_embeddings, pg_store, vector_index
from app.memory.engine import memory_engine
from app.memory.retrieval import build_entries, tokenize
from app.models.memory_models import MemoryEntry
from app.services.latency_metrics import observe_fast_recall_semantic_missed
from shared.py.wide_events import log

_PINNED_IDS = TypeAdapter(list[str])

#: Query text -> (started, embedding task). Shared across turns in the process:
#: an embedding depends on the text alone.
_inflight: dict[str, tuple[float, asyncio.Task[list[float]]]] = {}


def fts_tokens(query: str) -> list[str]:
    """Return the query's distinct words, safe to OR into a tsquery, in order and capped."""
    words = dict.fromkeys(word for token in tokenize(query) if (word := token.replace("'", "")))
    return list(words)[:FAST_RECALL_MAX_TOKENS]


def _consume_failure(task: asyncio.Task[list[float]]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.warning("Query embedding failed", error=str(error), error_type=type(error).__name__)


def start_query_embedding(query: str) -> None:
    """Begin embedding the turn's message now, so the lane finds it done or nearly."""
    if not query.strip() or not hosted_embeddings.configured():
        return
    now = time.monotonic()
    stale = [
        text
        for text, (started, _) in _inflight.items()
        if now - started > QUERY_EMBEDDING_TTL_SECONDS
    ]
    for text in stale:
        del _inflight[text]
    if query not in _inflight:
        task = asyncio.create_task(hosted_embeddings.embed_query(query))
        task.add_done_callback(_consume_failure)
        _inflight[query] = (now, task)


async def _query_vector(query: str) -> list[float]:
    start_query_embedding(query)
    entry = _inflight.get(query)
    if entry is None:
        raise hosted_embeddings.HostedEmbeddingError("OpenAI is not configured")
    # Shielded: a lane that runs out of budget must not cancel an embedding
    # another turn with the same text may be waiting on.
    return await asyncio.shield(entry[1])


async def _semantic_ids(user_id: str, query: str) -> list[str]:
    if not hosted_embeddings.configured() or not await vector_index.has_vectors(user_id):
        return []
    vector = await _query_vector(query)
    return await vector_index.nearest(
        user_id, vector, FAST_RECALL_SEMANTIC_K, min_similarity=FAST_RECALL_MIN_SIMILARITY
    )


def _log_late_failure(task: asyncio.Task[list[str]]) -> None:
    if not task.cancelled() and (error := task.exception()) is not None:
        log.warning(
            "Late semantic step failed after the lane answered",
            error=str(error),
            error_type=type(error).__name__,
        )


async def _semantic_in_time(user_id: str, query: str) -> list[str]:
    """Return the semantic hits that land within the lane's semantic budget, else none.

    A late step is shielded and keeps running, so the embedding and the user's
    vector set are ready for the next turn instead of thrown away.
    """
    step = asyncio.ensure_future(_semantic_ids(user_id, query))
    try:
        return await asyncio.wait_for(asyncio.shield(step), FAST_RECALL_SEMANTIC_BUDGET_SECONDS)
    except TimeoutError:
        step.add_done_callback(_log_late_failure)
        observe_fast_recall_semantic_missed()
        log.set_ns("memory_fast_recall", semantic="late")
        return []


async def store_precomputed(user_id: str, conversation_id: str, memory_ids: list[str]) -> None:
    """Pin memory ids for the conversation's next turn."""
    if not redis_cache.client:
        return
    await redis_cache.client.set(
        PRECOMPUTED_RECALL_KEY.format(user_id=user_id, conversation_id=conversation_id),
        _PINNED_IDS.dump_json(memory_ids).decode(),
        ex=PRECOMPUTED_RECALL_TTL,
    )


async def _pinned_ids(user_id: str, conversation_id: str | None) -> list[str]:
    if conversation_id is None or not redis_cache.client:
        return []
    raw = await redis_cache.client.get(
        PRECOMPUTED_RECALL_KEY.format(user_id=user_id, conversation_id=conversation_id)
    )
    return _PINNED_IDS.validate_json(raw) if raw else []


async def fast_recall(
    user_id: str, query: str, *, conversation_id: str | None
) -> list[MemoryEntry]:
    """Return the turn's memories: semantic matches, then pinned, then any sharing a word."""
    semantic, pinned = await asyncio.gather(
        _semantic_in_time(user_id, query), _pinned_ids(user_id, conversation_id)
    )
    tokens = fts_tokens(query)
    if not (semantic or pinned or tokens):
        return []
    rows = await pg_store.fast_candidates(
        user_id, tokens, pinned, MEMORY_RECALL_BLOCK_LIMIT, semantic_ids=semantic
    )
    return await build_entries(rows) if rows else []


def _last_text(messages: Sequence[AnyMessage], kind: type[HumanMessage | AIMessage]) -> str:
    texts = (m.text for m in reversed(messages) if isinstance(m, kind) and m.text)
    return next(texts, "")  # pragma: no mutate — the exchange join drops empty text


async def precompute_next_turn(
    user_id: str, conversation_id: str, messages: Sequence[AnyMessage]
) -> None:
    """Run the deep recall on the exchange that just ended and pin it for the next turn."""
    exchange = "\n".join(
        text
        for text in (_last_text(messages, HumanMessage), _last_text(messages, AIMessage))
        if text
    )
    if not exchange:
        return
    result = await memory_engine.recall(user_id, exchange, limit=PRECOMPUTED_RECALL_LIMIT)
    await store_precomputed(
        user_id, conversation_id, [memory.id for memory in result.memories if memory.id]
    )
