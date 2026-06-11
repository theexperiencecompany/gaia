"""Core documents + consolidation — rewrites, versioning, debounce, hot cache.

The consolidation LLM is canned (``ConsolidatedDocument``); everything else
(fact gathering from Postgres, document versioning, Redis pending set,
debounce waiter, hot-context invalidation) runs for real. Debounce timing is
shrunk via monkeypatch — no sleeps against the production 120s window.
"""

import asyncio

import pytest
from redis.asyncio import Redis

from app.constants.memory import (
    CONSOLIDATION_PENDING_KEY,
    DOCUMENT_HISTORY_LIMIT,
    MemoryDocType,
    MemorySourceType,
    ReconcileOutcome,
)
from app.memory import consolidation, pg_store
from app.memory.engine import memory_engine
from app.memory.schemas import (
    ConsolidatedDocument,
    ExtractedMemoryBatch,
    ReconcileBatchResult,
    ReconcileDecision,
)
from tests.memory.llm import FakeMemoryLLM, make_batch, make_fact
from tests.memory.store import fetch_document_rows, seed_memories

pytestmark = pytest.mark.memory


async def test_consolidate_feeds_user_doc_prompt_with_the_right_facts(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    seeded = await seed_memories(
        memory_user,
        [
            {"content": "Aryan is a software engineer at TechNova.", "category": "work"},
            {"content": "Aryan lives in Indiranagar, Bengaluru.", "category": "home"},
            {"content": "Aryan is building GAIA on weekends.", "category": "work/gaia"},
        ],
    )
    fake_llm.respond(
        ConsolidatedDocument,
        ConsolidatedDocument(content="# About Aryan\n- Engineer at TechNova in Bengaluru."),
    )

    rewritten = await memory_engine.consolidate(memory_user, [MemoryDocType.USER_MD])
    assert rewritten == [MemoryDocType.USER_MD]

    calls = fake_llm.calls_for(ConsolidatedDocument)
    assert len(calls) == 1
    prompt = calls[0].human
    for record in seeded:
        assert record.content in prompt, f"fact missing from consolidation inputs: {record.content}"
    assert "(no previous version)" in prompt

    document = await memory_engine.get_document(memory_user, MemoryDocType.USER_MD)
    assert document is not None
    assert document.content == "# About Aryan\n- Engineer at TechNova in Bengaluru."
    assert document.version == 1


async def test_consolidate_empty_user_skips_without_llm_call(memory_user: str) -> None:
    # No canned ConsolidatedDocument is registered: any LLM call would fail
    # the test. A user with no facts and no previous documents must skip all.
    rewritten = await memory_engine.consolidate(memory_user)
    assert rewritten == []
    assert await fetch_document_rows(memory_user) == []


async def test_consolidate_llm_failure_keeps_previous_version(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await memory_engine.update_document(memory_user, MemoryDocType.USER_MD, "# Original")
    await seed_memories(
        memory_user, [{"content": "Aryan adopted a cat named Miso.", "category": "pets"}]
    )

    fake_llm.respond(ConsolidatedDocument, None)
    rewritten = await memory_engine.consolidate(memory_user, [MemoryDocType.USER_MD])
    assert rewritten == []

    document = await memory_engine.get_document(memory_user, MemoryDocType.USER_MD)
    assert document is not None
    assert document.content == "# Original", "LLM failure must not clobber the document"
    assert document.version == 1


async def test_update_document_bumps_version_and_caps_history(memory_user: str) -> None:
    total_writes = DOCUMENT_HISTORY_LIMIT + 2  # 12 writes -> history overflows by one
    for index in range(1, total_writes + 1):
        await memory_engine.update_document(
            memory_user, MemoryDocType.AGENDA_MD, f"agenda v{index}"
        )

    rows = await fetch_document_rows(memory_user)
    assert len(rows) == 1
    document = rows[0]
    assert document.version == total_writes
    assert document.content == f"agenda v{total_writes}"
    assert len(document.history) == DOCUMENT_HISTORY_LIMIT, "history must be capped"
    assert document.history[0]["version"] == total_writes - 1, "history must be newest-first"
    assert document.history[0]["content"] == f"agenda v{total_writes - 1}"
    assert document.history[-1]["version"] == total_writes - DOCUMENT_HISTORY_LIMIT, (
        "oldest history entry must roll off the cap"
    )


async def test_debounced_consolidation_merges_doc_types_and_fires_once(
    memory_user: str,
    fake_llm: FakeMemoryLLM,
    monkeypatch: pytest.MonkeyPatch,
    real_redis: Redis,
) -> None:
    # Shrunk from the production 120s, but kept wide enough that both retains
    # (real embeddings + store writes) land inside one debounce window.
    monkeypatch.setattr(consolidation, "CONSOLIDATION_DEBOUNCE_SECONDS", 1.5)
    fake_llm.respond(ConsolidatedDocument, ConsolidatedDocument(content="# Rewritten"))
    # Short first-person facts can drift into the reconcile band; the verdict
    # is irrelevant here, so keep everything NEW and test only the debounce.
    fake_llm.respond(
        ReconcileBatchResult,
        ReconcileBatchResult(
            decisions=[ReconcileDecision(new_fact_index=0, decision=ReconcileOutcome.NEW)]
        ),
    )

    fake_llm.respond(
        ExtractedMemoryBatch,
        make_batch([make_fact("Aryan's partner is Nadia.", category="relationships")]),
    )
    await memory_engine.retain(
        memory_user,
        [{"role": "user", "content": "first"}],
        source_type=MemorySourceType.CONVERSATION,
    )
    waiter = consolidation._waiters.get(memory_user)
    assert waiter is not None, "first retain must start a debounce waiter"

    fake_llm.respond(
        ExtractedMemoryBatch,
        make_batch([make_fact("Aryan is vegetarian.", category="food-preferences")]),
    )
    await memory_engine.retain(
        memory_user,
        [{"role": "user", "content": "second"}],
        source_type=MemorySourceType.CONVERSATION,
    )
    assert consolidation._waiters.get(memory_user) is waiter, (
        "second retain inside the window must reuse the live waiter"
    )

    await asyncio.wait_for(waiter, timeout=5)

    # relationships -> people_md + user_md; food-preferences -> memory_md.
    # One merged pass: exactly three rewrites, no second consolidation.
    calls = fake_llm.calls_for(ConsolidatedDocument)
    assert len(calls) == 3, f"expected one merged consolidation pass, saw {len(calls)} rewrites"
    doc_types = {row.doc_type for row in await fetch_document_rows(memory_user)}
    assert doc_types == {
        MemoryDocType.PEOPLE_MD.value,
        MemoryDocType.USER_MD.value,
        MemoryDocType.MEMORY_MD.value,
    }
    pending = await real_redis.get(CONSOLIDATION_PENDING_KEY.format(user_id=memory_user))
    assert pending is None, "pending set must be consumed by the waiter"


async def test_core_context_cache_serves_stale_until_retain_invalidates(
    memory_user: str, fake_llm: FakeMemoryLLM
) -> None:
    await memory_engine.update_document(
        memory_user, MemoryDocType.USER_MD, "Aryan is a software engineer in Bengaluru."
    )
    first = await memory_engine.get_core_context(memory_user)
    assert "Aryan is a software engineer in Bengaluru." in first

    # Write the document straight through the store, bypassing invalidation:
    # the cached context must keep serving the old assembly (real Redis hit).
    await pg_store.upsert_document(
        memory_user, MemoryDocType.USER_MD, "Aryan moved to San Francisco."
    )
    stale = await memory_engine.get_core_context(memory_user)
    assert stale == first, "core context was not served from cache"

    fake_llm.respond(
        ExtractedMemoryBatch, make_batch(entries=["Asked GAIA about moving logistics"])
    )
    await memory_engine.retain(
        memory_user,
        [{"role": "user", "content": "transcript"}],
        source_type=MemorySourceType.CONVERSATION,
    )

    fresh = await memory_engine.get_core_context(memory_user)
    assert "Aryan moved to San Francisco." in fresh, "retain did not invalidate the core context"
    assert "Asked GAIA about moving logistics" in fresh, "fresh context missing today's journal"
