"""The comms fast lane against real Postgres: one query, pinned rows plus OR-matched text."""

import pytest

from app.memory import fast_recall
from app.memory.pg_store.memories import mark_forgotten
from tests.integration.real.memory.store import seed_memories

pytestmark = pytest.mark.memory


async def test_a_single_shared_word_is_enough_to_match(memory_user: str) -> None:
    """websearch_to_tsquery ANDs every term, so a conversational turn matched nothing."""
    await seed_memories(
        memory_user,
        [
            {"content": "Flies Lufthansa and always books a window seat."},
            {"content": "Allergic to peanuts."},
        ],
    )

    entries = await fast_recall.fast_recall(
        memory_user, "hey which seat should I pick for tomorrow's flight", conversation_id=None
    )

    assert [e.content for e in entries] == ["Flies Lufthansa and always books a window seat."]


async def test_pinned_memories_come_first_even_with_no_shared_words(memory_user: str) -> None:
    pinned, other = await seed_memories(
        memory_user,
        [
            {"content": "Partner's name is Priya."},
            {"content": "Prefers morning meetings."},
        ],
    )
    await fast_recall.store_precomputed(memory_user, "conv-1", [str(pinned.id)])

    entries = await fast_recall.fast_recall(memory_user, "morning plans", conversation_id="conv-1")

    assert [e.content for e in entries] == [pinned.content, other.content]


async def test_a_forgotten_pinned_memory_never_renders(memory_user: str) -> None:
    (pinned,) = await seed_memories(memory_user, [{"content": "Lives in Berlin."}])
    await fast_recall.store_precomputed(memory_user, "conv-1", [str(pinned.id)])
    await mark_forgotten(str(pinned.id), memory_user, "user asked to forget")

    entries = await fast_recall.fast_recall(
        memory_user, "where do I live", conversation_id="conv-1"
    )

    assert entries == []


async def test_nothing_to_match_returns_nothing(memory_user: str) -> None:
    await seed_memories(memory_user, [{"content": "Allergic to peanuts."}])

    assert await fast_recall.fast_recall(memory_user, "?!", conversation_id=None) == []
