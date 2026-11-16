"""The comms fast lane against real Postgres and Redis: semantic hits, pins and shared words."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.memory import MEMORY_VECTOR_MODEL
from app.memory import fast_recall, hosted_embeddings, vector_index
from app.memory.pg_store.memories import mark_forgotten
from app.memory.pg_store.vectors import live_vectors, upsert_vectors, vectors_changed_since
from tests.integration.real.memory.store import seed_memories

# Hand-made unit directions stand in for a model: these tests prove the lane's
# plumbing (held vectors, versioning, liveness, ordering), not a model's quality.
GIRLFRIEND, DOG, MOTHER = [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]
CELLO = [0.0, 0.0, 0.0, 1.0]
NEAR_GIRLFRIEND = [0.95, 0.05, 0.0, 0.0]


@contextmanager
def query_embeds_to(vector: Sequence[float]) -> Iterator[None]:
    """Report OpenAI configured and make the hosted query embedding return vector."""
    fast_recall._inflight.clear()
    with (
        patch.object(hosted_embeddings, "configured", return_value=True),
        patch.object(hosted_embeddings, "embed_query", new=AsyncMock(return_value=list(vector))),
    ):
        yield


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


async def _seed_with_vectors(user_id: str) -> tuple[str, str, str]:
    girlfriend, dog, mother = await seed_memories(
        user_id,
        [
            {"content": "Girlfriend is Priya; they met in college in Pune."},
            {"content": "Dog's name is Max, a golden retriever."},
            {"content": "Mother's name is Sunita."},
        ],
    )
    await upsert_vectors(
        user_id,
        MEMORY_VECTOR_MODEL,
        [(girlfriend.id, GIRLFRIEND), (dog.id, DOG), (mother.id, MOTHER)],
    )
    await vector_index.bump_version(user_id)
    return girlfriend.content, dog.content, mother.content


async def test_a_semantic_hit_needs_no_shared_word(memory_user: str) -> None:
    girlfriend, _dog, _mother = await _seed_with_vectors(memory_user)
    with query_embeds_to(NEAR_GIRLFRIEND):
        entries = await fast_recall.fast_recall(
            memory_user, "who am I dating", conversation_id=None
        )

    assert entries[0].content == girlfriend


async def test_a_semantic_hit_outranks_word_matches_that_mislead(memory_user: str) -> None:
    """The word name matches the dog and the mother; the semantic hit still comes first."""
    girlfriend, dog, mother = await _seed_with_vectors(memory_user)
    with query_embeds_to(NEAR_GIRLFRIEND):
        entries = await fast_recall.fast_recall(
            memory_user, "what's my gf's name", conversation_id=None
        )

    assert entries[0].content == girlfriend
    assert {e.content for e in entries[1:]} >= {dog, mother}


async def test_a_memory_written_after_the_set_was_held_is_found_next_turn(
    memory_user: str,
) -> None:
    await _seed_with_vectors(memory_user)
    with query_embeds_to(CELLO):
        assert await fast_recall.fast_recall(memory_user, "zzz", conversation_id=None) == []

    (late,) = await seed_memories(memory_user, [{"content": "Plays the cello on Sundays."}])
    with (
        patch.object(hosted_embeddings, "configured", return_value=True),
        patch.object(hosted_embeddings, "embed_documents", new=AsyncMock(return_value=[CELLO])),
    ):
        await vector_index.index_memories(memory_user, [(late.id, late.content)])
    await vector_index.bump_version(memory_user)

    with query_embeds_to(CELLO):
        entries = await fast_recall.fast_recall(memory_user, "zzz", conversation_id=None)

    assert [e.content for e in entries] == [late.content]


async def test_a_forgotten_memory_with_a_held_vector_never_renders(memory_user: str) -> None:
    await _seed_with_vectors(memory_user)
    with query_embeds_to(NEAR_GIRLFRIEND):
        before = await fast_recall.fast_recall(memory_user, "zzz", conversation_id=None)
    await mark_forgotten(str(before[0].id), memory_user, "user asked to forget")

    with query_embeds_to(NEAR_GIRLFRIEND):
        after = await fast_recall.fast_recall(memory_user, "zzz", conversation_id=None)

    assert before[0].content not in [e.content for e in after]


async def test_the_delta_read_names_new_vectors_live_and_forgotten_memories_dead(
    memory_user: str,
) -> None:
    """A write refreshes a held set from this read alone, so it must see adds, edits and forgets."""
    kept, edited, forgotten = await seed_memories(
        memory_user,
        [
            {"content": "Girlfriend is Priya."},
            {"content": "Dog's name is Max."},
            {"content": "Mother's name is Sunita."},
        ],
    )
    await upsert_vectors(
        memory_user,
        MEMORY_VECTOR_MODEL,
        [(kept.id, GIRLFRIEND), (edited.id, DOG), (forgotten.id, MOTHER)],
    )
    held = await live_vectors(memory_user, MEMORY_VECTOR_MODEL)

    (late,) = await seed_memories(memory_user, [{"content": "Plays the cello on Sundays."}])
    await upsert_vectors(memory_user, MEMORY_VECTOR_MODEL, [(late.id, CELLO), (edited.id, CELLO)])
    await mark_forgotten(str(forgotten.id), memory_user, "user asked to forget")

    delta = await vectors_changed_since(memory_user, MEMORY_VECTOR_MODEL, held.read_at)

    assert sorted(delta.live_ids) == sorted([str(late.id), str(edited.id)])
    assert delta.dead_ids == [str(forgotten.id)]
    assert delta.matrix.shape == (2, len(CELLO))
