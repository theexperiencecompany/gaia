"""The comms fast lane: a turn's memories without embedding, ANN or rerank in front of it.

One Postgres query returns what the background recall pinned after the
conversation's previous exchange plus whatever shares a word with the new
message. The deep, semantic recall runs after a turn (for the next one) and on
demand through the search_memory tool, never in front of a reply.
"""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from pydantic import TypeAdapter

from app.constants.memory import (
    FAST_RECALL_MAX_TOKENS,
    MEMORY_RECALL_BLOCK_LIMIT,
    PRECOMPUTED_RECALL_KEY,
    PRECOMPUTED_RECALL_LIMIT,
    PRECOMPUTED_RECALL_TTL,
)
from app.db.redis import redis_cache
from app.memory import pg_store
from app.memory.engine import memory_engine
from app.memory.retrieval import build_entries, tokenize
from app.models.memory_models import MemoryEntry

_PINNED_IDS = TypeAdapter(list[str])


def fts_tokens(query: str) -> list[str]:
    """Return the query's distinct words, safe to OR into a tsquery, in order and capped."""
    words: dict[str, None] = {}
    for token in tokenize(query):
        word = token.replace("'", "")
        if word:
            words.setdefault(word, None)
    return list(words)[:FAST_RECALL_MAX_TOKENS]


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
    """Return the turn's memories: pinned for this conversation first, then any sharing a word."""
    pinned = await _pinned_ids(user_id, conversation_id)
    tokens = fts_tokens(query)
    if not pinned and not tokens:
        return []
    rows = await pg_store.fast_candidates(user_id, tokens, pinned, MEMORY_RECALL_BLOCK_LIMIT)
    return await build_entries(rows) if rows else []


def _last_text(messages: Sequence[AnyMessage], kind: type[HumanMessage | AIMessage]) -> str:
    return next((m.text for m in reversed(messages) if isinstance(m, kind) and m.text), "")


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
