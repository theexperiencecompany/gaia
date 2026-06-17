"""Lineage and forgetting invariants — supersession chains and the hard wipe.

These are the invariants the rest of the engine leans on: exactly one live
head per chain, a stable root anchor, soft-forget hiding the whole chain
from recall, and ``delete_all`` leaving zero residue in any of the six
Postgres tables or either Chroma collection.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.memory import (
    CHROMA_MEMORY_EPISODES_COLLECTION,
    MemoryDocType,
    MemoryRelationType,
    MemorySourceType,
)
from app.memory import pg_store
from app.memory.engine import memory_engine
from app.memory.schemas import EpisodeSummary, ExtractedMemoryBatch
from tests.memory.llm import FakeMemoryLLM, make_batch, make_fact
from tests.memory.store import (
    chroma_user_vector_ids,
    chroma_vector_metadata,
    count_entity_links,
    fetch_document_rows,
    fetch_edges,
    fetch_entities,
    fetch_episode_rows,
    fetch_memory_rows,
    seed_memories,
)

pytestmark = pytest.mark.memory


async def test_three_deep_update_chain_invariants(memory_user: str) -> None:
    (root,) = await seed_memories(
        memory_user,
        [{"content": "Arjun works at TechNova.", "category": "work"}],
    )

    head_id = str(root.id)
    for content in (
        "Arjun works at Initech.",
        "Arjun works at Hooli.",
        "Arjun works at Pied Piper.",
    ):
        entry = await memory_engine.update_memory(memory_user, head_id, content)
        assert entry is not None, f"update_memory refused live head {head_id}"
        head_id = entry.id

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 4
    assert sorted(row.version for row in rows) == [1, 2, 3, 4]

    latest = [row for row in rows if row.is_latest]
    assert len(latest) == 1, "chain must have exactly one live head"
    assert latest[0].version == 4
    assert latest[0].content == "Arjun works at Pied Piper."

    by_version = {row.version: row for row in rows}
    for version in (2, 3, 4):
        assert by_version[version].root_id == root.id, "root_id must anchor at the original"
        assert by_version[version].parent_id == by_version[version - 1].id
        assert by_version[version].relation_type == MemoryRelationType.UPDATES.value

    # Only the head may be reachable through recall.
    result = await memory_engine.recall(memory_user, "where does Arjun work")
    contents = [memory.content for memory in result.memories]
    assert "Arjun works at Pied Piper." in contents
    for stale in ("TechNova", "Initech", "Hooli"):
        assert all(stale not in content for content in contents), (
            f"superseded version '{stale}' leaked into recall: {contents}"
        )


async def test_forgetting_chain_head_hides_the_whole_chain(memory_user: str) -> None:
    (root,) = await seed_memories(
        memory_user,
        [{"content": "Arjun plays badminton on Saturdays.", "category": "hobbies"}],
    )
    entry = await memory_engine.update_memory(
        memory_user, str(root.id), "Arjun plays badminton on Sundays."
    )
    assert entry is not None

    forgotten = await memory_engine.forget_memory(memory_user, entry.id, "user request")
    assert forgotten is True

    result = await memory_engine.recall(memory_user, "when does Arjun play badminton")
    assert result.memories == [], "forgotten chain still reachable through recall"

    listing = await memory_engine.list_memories(memory_user)
    assert listing.total_count == 0

    head_metadata = await chroma_vector_metadata(entry.id)
    assert head_metadata is not None and head_metadata["is_forgotten"] is True

    # Forgetting is soft: the rows must still exist for lineage history.
    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2


async def test_delete_all_leaves_zero_rows_and_zero_vectors(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    # Build a user with residue in every table: facts + entities + edges via
    # retain, a journal day that rolled over into an episode vector, and a
    # core document.
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    await pg_store.append_episode_entries(
        memory_user,
        yesterday,
        [{"time": "10:00", "text": "Planned the Lisbon trip", "source": "conversation"}],
    )
    fake_llm.respond(EpisodeSummary, EpisodeSummary(summary="Planned the Lisbon trip."))
    fake_llm.respond(
        ExtractedMemoryBatch,
        make_batch(
            facts=[
                make_fact(
                    "Arjun is dating Nadia.",
                    category="relationships",
                    entities=[("Arjun", "person"), ("Nadia", "person")],
                    edges=[("Arjun", "is dating", "Nadia")],
                )
            ],
            entries=["Talked about weekend plans with Nadia"],
        ),
    )
    await memory_engine.retain(
        memory_user,
        [{"role": "user", "content": "transcript"}],
        source_type=MemorySourceType.CONVERSATION,
    )
    await memory_engine.update_document(memory_user, MemoryDocType.USER_MD, "# Arjun")

    assert await fetch_memory_rows(memory_user)
    assert await fetch_entities(memory_user)
    assert await fetch_edges(memory_user)
    assert await fetch_episode_rows(memory_user)
    assert await fetch_document_rows(memory_user)
    assert await chroma_user_vector_ids(memory_user)
    assert await chroma_user_vector_ids(memory_user, CHROMA_MEMORY_EPISODES_COLLECTION)

    deleted = await memory_engine.delete_all(memory_user)
    assert deleted == 1

    assert await fetch_memory_rows(memory_user) == []
    assert await fetch_entities(memory_user) == []
    assert await fetch_edges(memory_user) == []
    assert await fetch_episode_rows(memory_user) == []
    assert await fetch_document_rows(memory_user) == []
    assert await count_entity_links(memory_user) == 0
    assert await chroma_user_vector_ids(memory_user) == []
    assert await chroma_user_vector_ids(memory_user, CHROMA_MEMORY_EPISODES_COLLECTION) == []
