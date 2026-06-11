"""Ingestion end-to-end — retain pipelines against real stores.

Extraction is canned per test (``ExtractedMemoryBatch``); embeddings,
reconciliation thresholds, Postgres writes, Chroma upserts and the entity
graph all run for real. Every assertion reads persisted state back out of
the stores, not just the ``RetainResult`` counters.
"""

import asyncio

from langchain_core.messages import BaseMessage
import pytest
from redis.asyncio import Redis

from app.constants.memory import CONSOLIDATION_PENDING_KEY, MemorySourceType, ReconcileOutcome
from app.memory import consolidation
from app.memory.engine import RetainResult, memory_engine
from app.memory.schemas import ExtractedMemoryBatch
from tests.memory.llm import FakeMemoryLLM, make_batch, make_fact
from tests.memory.store import (
    chroma_user_vector_ids,
    chroma_vector_metadata,
    count_entity_links,
    fetch_edges,
    fetch_entities,
    fetch_episode_rows,
    fetch_memory_rows,
    linked_entity_ids,
)

pytestmark = pytest.mark.memory


async def _retain(
    user_id: str,
    fake_llm: FakeMemoryLLM,
    batch: ExtractedMemoryBatch,
    transcript: str = "transcript",
) -> RetainResult:
    fake_llm.respond(ExtractedMemoryBatch, batch)
    return await memory_engine.retain(
        user_id,
        [{"role": "user", "content": transcript}],
        source_type=MemorySourceType.CONVERSATION,
    )


async def test_full_retain_persists_facts_graph_and_journal(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    batch = make_batch(
        facts=[
            make_fact(
                "Aryan's girlfriend Nadia's birthday is March 12.",
                category="relationships",
                importance=0.9,
                entities=[("Aryan", "person"), ("Nadia", "person")],
                edges=[("Aryan", "is dating", "Nadia")],
            ),
            make_fact(
                "Aryan works at TechNova as a backend engineer.",
                category="work",
                entities=[("Aryan", "person"), ("TechNova", "organization")],
                edges=[("Aryan", "works at", "TechNova")],
            ),
            make_fact("Aryan is vegetarian.", category="food-preferences"),
        ],
        entries=["Discussed Nadia's birthday plans", "GAIA noted the dietary preference"],
    )
    result = await _retain(memory_user, fake_llm, batch)

    assert result.facts_extracted == 3
    assert result.new == 3
    assert result.duplicates == result.updated == result.extended == 0
    assert result.entities_linked == 4
    assert result.edges_added == 2
    assert result.episode_entries == 2

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 3
    assert all(row.is_latest and row.version == 1 for row in rows)
    assert all(row.source_type == MemorySourceType.CONVERSATION.value for row in rows)
    by_content = {row.content: row for row in rows}
    assert by_content["Aryan's girlfriend Nadia's birthday is March 12."].importance == 0.9
    assert by_content["Aryan is vegetarian."].category_path == "food-preferences"

    # Chroma agrees row-for-row, with filterable metadata.
    vector_ids = set(await chroma_user_vector_ids(memory_user))
    assert vector_ids == {str(row.id) for row in rows}
    metadata = await chroma_vector_metadata(str(by_content["Aryan is vegetarian."].id))
    assert metadata is not None
    assert metadata["category_path"] == "food-preferences"
    assert metadata["is_latest"] is True and metadata["is_forgotten"] is False

    entities = await fetch_entities(memory_user)
    assert {entity.name for entity in entities} == {"Aryan", "Nadia", "TechNova"}
    assert await count_entity_links(memory_user) == 4

    edges = await fetch_edges(memory_user)
    assert {(edge.relationship) for edge in edges} == {"is dating", "works at"}
    assert all(edge.memory_id is not None for edge in edges), "edges must keep provenance"

    episodes = await fetch_episode_rows(memory_user)
    assert len(episodes) == 1
    assert [entry["text"] for entry in episodes[0].entries] == [
        "Discussed Nadia's birthday plans",
        "GAIA noted the dietary preference",
    ]


async def test_entities_dedupe_case_insensitively_across_retains(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(
        memory_user,
        fake_llm,
        make_batch(
            [
                make_fact(
                    "Aryan's girlfriend Nadia's birthday is March 12.",
                    category="relationships",
                    entities=[("Nadia", "person")],
                )
            ]
        ),
    )
    await _retain(
        memory_user,
        fake_llm,
        make_batch(
            [
                make_fact(
                    "nadia is allergic to shellfish.",
                    category="relationships",
                    entities=[("nadia", "person")],
                )
            ]
        ),
    )

    entities = await fetch_entities(memory_user)
    assert len(entities) == 1, f"case variants must collapse: {[e.name for e in entities]}"
    assert entities[0].name == "Nadia", "first-seen casing must be kept"

    rows = await fetch_memory_rows(memory_user)
    for row in rows:
        assert await linked_entity_ids(row.id) == {entities[0].id}, (
            "both memories must link to the single canonical entity"
        )


async def test_edges_are_idempotent_across_repeat_retains(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    edge = [("Aryan", "is dating", "Nadia")]
    entities = [("Aryan", "person"), ("Nadia", "person")]
    first = await _retain(
        memory_user,
        fake_llm,
        make_batch(
            [
                make_fact(
                    "Aryan is dating Nadia.",
                    category="relationships",
                    entities=entities,
                    edges=edge,
                )
            ]
        ),
    )
    assert first.edges_added == 1

    second = await _retain(
        memory_user,
        fake_llm,
        make_batch(
            [
                make_fact(
                    "Aryan booked a table at Burma Burma for Friday evening.",
                    category="food-preferences",
                    entities=entities,
                    edges=edge,
                )
            ]
        ),
    )
    assert second.edges_added == 0, "repeated triple must hit the unique constraint"

    edges = await fetch_edges(memory_user)
    assert len(edges) == 1, f"duplicate edge rows persisted: {len(edges)}"


async def test_retain_with_zero_facts_and_entries_is_a_clean_noop(
    memory_user: str, fake_llm: FakeMemoryLLM, real_redis: Redis
) -> None:
    result = await _retain(memory_user, fake_llm, make_batch())

    assert result.facts_extracted == 0
    assert result.new == result.updated == result.extended == result.duplicates == 0
    assert result.episode_entries == 0

    assert await fetch_memory_rows(memory_user) == []
    assert await fetch_entities(memory_user) == []
    assert await fetch_episode_rows(memory_user) == []
    assert await chroma_user_vector_ids(memory_user) == []
    assert memory_user not in consolidation._waiters, "no-op must not schedule consolidation"
    pending = await real_redis.get(CONSOLIDATION_PENDING_KEY.format(user_id=memory_user))
    assert pending is None


async def test_retain_single_duplicate_collapses_to_existing_memory(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    first = await memory_engine.retain_single(
        memory_user,
        "Aryan is vegetarian.",
        category_path="food-preferences",
        source_type=MemorySourceType.MANUAL,
    )
    second = await memory_engine.retain_single(
        memory_user,
        "Aryan is vegetarian.",
        category_path="food-preferences",
        source_type=MemorySourceType.MANUAL,
    )
    assert first.outcome is ReconcileOutcome.NEW
    assert second.outcome is ReconcileOutcome.DUPLICATE
    assert second.entry.id == first.entry.id, "exact duplicate must surface the existing memory"
    assert len(await fetch_memory_rows(memory_user)) == 1


async def test_concurrent_retains_do_not_corrupt_graph_or_journal(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    batches = {
        f"convo {index}": make_batch(
            facts=[
                make_fact(
                    content,
                    category=category,
                    entities=[("Marco", "person")],
                )
            ],
            entries=[f"concurrent retain entry {index}"],
        )
        for index, (content, category) in enumerate(
            [
                ("Marco recommended a trattoria in Rome.", "travel"),
                ("Marco plays five-a-side football on Tuesdays.", "hobbies"),
                ("Marco's code reviews are scheduled for Friday.", "work"),
            ]
        )
    }

    def respond(messages: list[BaseMessage]) -> ExtractedMemoryBatch:
        transcript = str(messages[-1].content)
        for key, batch in batches.items():
            if key in transcript:
                return batch
        raise AssertionError(f"unexpected transcript: {transcript}")

    fake_llm.respond(ExtractedMemoryBatch, respond)
    results = await asyncio.gather(
        *[
            memory_engine.retain(
                memory_user,
                [{"role": "user", "content": key}],
                source_type=MemorySourceType.CONVERSATION,
            )
            for key in batches
        ]
    )
    assert sum(result.new for result in results) == 3

    entities = await fetch_entities(memory_user)
    assert len(entities) == 1, (
        f"concurrent retains created duplicate entities: {[e.name for e in entities]}"
    )

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 3
    assert all(row.is_latest for row in rows)
    for row in rows:
        assert await linked_entity_ids(row.id) == {entities[0].id}

    episodes = await fetch_episode_rows(memory_user)
    assert len(episodes) == 1, "concurrent retains must converge on one journal row"
    texts = {entry["text"] for entry in episodes[0].entries}
    assert texts == {f"concurrent retain entry {index}" for index in range(3)}, (
        "concurrent retains lost journal entries"
    )
