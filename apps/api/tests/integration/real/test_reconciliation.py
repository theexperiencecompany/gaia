"""Reconciliation torture tests — dedupe/supersession against real stores.

Each test drives the full retain() pipeline with canned extraction output
and real embeddings, then asserts on the persisted Postgres + Chroma state.
The cosine thresholds (DUPLICATE >= 0.92, reconcile band >= 0.75) are the
real production constants — sentence pairs were chosen so their bge-small
similarity lands deterministically in the intended band.
"""

import uuid

import pytest

from app.constants.memory import MemoryRelationType, MemorySourceType, ReconcileOutcome
from app.memory.engine import memory_engine
from app.memory.schemas import (
    ExtractedMemoryBatch,
    ReconcileBatchResult,
    ReconcileDecision,
)
from tests.memory.llm import (
    FakeMemoryLLM,
    make_batch,
    make_fact,
    reconcile_against_first_candidate,
)
from tests.memory.store import chroma_vector_metadata, fetch_memory_rows

pytestmark = pytest.mark.memory


async def _retain(user_id: str, fake_llm: FakeMemoryLLM, batch: ExtractedMemoryBatch):
    """Run one ingestion with a canned extraction batch."""
    fake_llm.respond(ExtractedMemoryBatch, batch)
    return await memory_engine.retain(
        user_id,
        [{"role": "user", "content": "transcript"}],
        source_type=MemorySourceType.CONVERSATION,
    )


async def test_exact_duplicate_is_skipped_without_llm(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    content = "Arjun's girlfriend Nadia's birthday is March 12."
    first = await _retain(memory_user, fake_llm, make_batch([make_fact(content)]))
    assert first.new == 1

    # Identical content → cosine ~1.0 → cheap-path DUPLICATE. The reconcile
    # LLM must NOT be consulted: no ReconcileBatchResult response is
    # registered, so any consult would raise.
    second = await _retain(memory_user, fake_llm, make_batch([make_fact(content)]))
    assert second.duplicates == 1
    assert second.new == 0

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 1
    assert rows[0].content == content
    assert rows[0].is_latest


async def test_paraphrase_does_not_survive_as_second_latest_fact(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(memory_user, fake_llm, make_batch([make_fact("Arjun's partner is Nadia.")]))

    # Paraphrase sits above the 0.92 duplicate threshold for bge-small; if it
    # ever dips into the ambiguous band a DUPLICATE verdict from the canned
    # reconcile LLM must collapse it just the same.
    fake_llm.respond(
        ReconcileBatchResult, reconcile_against_first_candidate(ReconcileOutcome.DUPLICATE)
    )
    result = await _retain(
        memory_user, fake_llm, make_batch([make_fact("Nadia is Arjun's girlfriend.")])
    )
    assert result.duplicates == 1

    rows = await fetch_memory_rows(memory_user)
    latest = [row for row in rows if row.is_latest]
    assert len(latest) == 1, f"paraphrase survived as a second fact: {[r.content for r in rows]}"
    assert latest[0].content == "Arjun's partner is Nadia."


async def test_contradiction_creates_updates_chain(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(memory_user, fake_llm, make_batch([make_fact("Arjun lives in Bengaluru.")]))
    old = (await fetch_memory_rows(memory_user))[0]

    fake_llm.respond(
        ReconcileBatchResult, reconcile_against_first_candidate(ReconcileOutcome.UPDATES)
    )
    result = await _retain(
        memory_user, fake_llm, make_batch([make_fact("Arjun moved to San Francisco.")])
    )
    assert result.updated == 1
    assert result.new == 0

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2
    old_row = next(row for row in rows if row.id == old.id)
    new_row = next(row for row in rows if row.id != old.id)

    assert not old_row.is_latest, "superseded memory still marked latest"
    assert new_row.is_latest
    assert new_row.version == 2
    assert new_row.parent_id == old.id
    assert new_row.root_id == old.id, "root_id must anchor the chain at the original"
    assert new_row.relation_type == MemoryRelationType.UPDATES.value

    # Chroma metadata must agree with Postgres, or recall filters will lag.
    old_metadata = await chroma_vector_metadata(str(old.id))
    assert old_metadata is not None and old_metadata["is_latest"] is False
    new_metadata = await chroma_vector_metadata(str(new_row.id))
    assert new_metadata is not None and new_metadata["is_latest"] is True


async def test_refinement_extends_and_keeps_both_latest(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(memory_user, fake_llm, make_batch([make_fact("Arjun likes coffee.")]))
    old = (await fetch_memory_rows(memory_user))[0]

    fake_llm.respond(
        ReconcileBatchResult, reconcile_against_first_candidate(ReconcileOutcome.EXTENDS)
    )
    result = await _retain(
        memory_user,
        fake_llm,
        make_batch([make_fact("Arjun specifically likes oat-milk lattes.")]),
    )
    assert result.extended == 1

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2
    assert all(row.is_latest for row in rows), "EXTENDS must not supersede the original"
    extension = next(row for row in rows if row.id != old.id)
    # EXTENDS is a relatedness link, not a revision: the new fact keeps version 1
    # and its own chain (root_id stays None). Only UPDATES advances the version.
    assert extension.version == 1
    assert extension.parent_id == old.id
    assert extension.root_id is None
    assert extension.relation_type == MemoryRelationType.EXTENDS.value


async def test_same_topic_different_assertion_stays_new(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(
        memory_user,
        fake_llm,
        make_batch([make_fact("Arjun's girlfriend Nadia's birthday is March 12.")]),
    )

    # Same subject (Nadia), different assertion — similarity is below the
    # reconcile band, so this must store as NEW without consulting the LLM
    # (no reconcile response registered → a consult would raise).
    result = await _retain(
        memory_user, fake_llm, make_batch([make_fact("Nadia's favorite food is sushi.")])
    )
    assert result.new == 1
    assert result.duplicates == 0
    assert result.updated == 0

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2
    assert all(row.is_latest for row in rows)


async def test_hallucinated_target_id_downgrades_to_new(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(memory_user, fake_llm, make_batch([make_fact("Arjun likes coffee.")]))

    bogus_id = str(uuid.uuid4())
    fake_llm.respond(
        ReconcileBatchResult,
        ReconcileBatchResult(
            decisions=[
                ReconcileDecision(
                    new_fact_index=0,
                    decision=ReconcileOutcome.UPDATES,
                    target_memory_id=bogus_id,
                )
            ]
        ),
    )
    result = await _retain(
        memory_user,
        fake_llm,
        make_batch([make_fact("Arjun specifically likes oat-milk lattes.")]),
    )
    assert len(fake_llm.calls_for(ReconcileBatchResult)) == 1, "fact never reached the LLM band"
    assert result.new == 1, "hallucinated target id must downgrade to NEW"
    assert result.updated == 0

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2
    assert all(row.is_latest for row in rows), "nothing may be superseded by a hallucinated id"
    assert all(row.version == 1 for row in rows)


async def test_reconcile_llm_total_failure_stores_everything_as_new(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await _retain(memory_user, fake_llm, make_batch([make_fact("Arjun likes coffee.")]))

    # Total reconcile failure (every provider down) → None → all-NEW fallback.
    fake_llm.respond(ReconcileBatchResult, None)
    result = await _retain(
        memory_user,
        fake_llm,
        make_batch([make_fact("Arjun specifically likes oat-milk lattes.")]),
    )
    assert len(fake_llm.calls_for(ReconcileBatchResult)) == 1
    assert result.new == 1, "LLM failure must not lose the fact"

    rows = await fetch_memory_rows(memory_user)
    assert len(rows) == 2
    assert {row.content for row in rows} == {
        "Arjun likes coffee.",
        "Arjun specifically likes oat-milk lattes.",
    }
