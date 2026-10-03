"""Memory reaching the model as the user experiences it: the agent remembers.

Every e2e that touches memory doubles the whole engine, so nothing proved
the join the feature exists for: a retained fact rendering into the prompt
the model actually reads, the core fetched once no matter how many sections
want it, and a recall outage degrading the turn instead of failing it. The
reconcile verdicts (NEW vs DUPLICATE vs dead-row) decide what ever gets
stored at all, and they run furthest from any user-visible assertion.

Real: the context fetchers, the singleflight, the split, reconcile banding.
Doubled: the engine behind the fetchers (scripted core + recall), Chroma /
Postgres / the reconcile LLM behind reconcile.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.agents.context import fetchers
from app.agents.context.section_context import SectionContext
from app.agents.context.tiers import AgentTier
from app.constants.memory import MemoryKind, MemoryShelfLife, ReconcileOutcome
from app.memory import reconciliation
from app.memory.context import AGENDA_HEADING, RECENT_ACTIVITY_HEADING
from app.memory.schemas import ExtractedFact
from app.models.memory_db_models import MemoryRecord
from app.models.memory_models import MemoryEntry, MemorySearchResult

pytestmark = pytest.mark.e2e

USER_ID = "user-1"
FETCHERS_ENGINE = "app.agents.context.fetchers.memory_engine"
NOW = datetime(2026, 8, 27, tzinfo=UTC)
EMBEDDING = [0.1, 0.2]

CORE_DOC = (
    "Sam prefers morning standups.\n"
    "\n"
    f"{AGENDA_HEADING}\nShip the redlines today\n"
    "\n"
    f"{RECENT_ACTIVITY_HEADING}\n- 09:00 reviewed the contract"
)


def _ctx(**overrides) -> SectionContext:
    data = {"tier": AgentTier.COMMS, "user_id": USER_ID, "query": "standup time"}
    data.update(overrides)
    return SectionContext(**data)


def _engine_double(core: str = CORE_DOC, memories: list[MemoryEntry] | None = None):
    engine = AsyncMock()
    engine.get_core_context = AsyncMock(return_value=core)
    engine.recall = AsyncMock(
        return_value=MemorySearchResult(memories=memories or [], total_count=len(memories or []))
    )
    return engine


class TestMemoryReachesThePrompt:
    async def test_core_documents_land_in_the_stable_block(self) -> None:
        with patch(FETCHERS_ENGINE, _engine_double()):
            block = await fetchers.build_core_memory_block(_ctx())

        assert "Sam prefers morning standups." in block
        # The churning half lives in its own slot, never in the stable one.
        assert "Ship the redlines today" not in block
        assert "reviewed the contract" not in block

    async def test_agenda_and_activity_land_in_the_churn_block(self) -> None:
        with patch(FETCHERS_ENGINE, _engine_double()):
            block = await fetchers.build_agenda_and_activity_block(_ctx())

        assert "Ship the redlines today" in block
        assert "reviewed the contract" in block
        assert "Sam prefers morning standups." not in block

    async def test_recall_renders_dated_notes_for_the_turn(self) -> None:
        entry = MemoryEntry(id="mem-1", content="standup moved to 9:30", category_path="routines")
        with patch(FETCHERS_ENGINE, _engine_double(memories=[entry])):
            block = await fetchers.build_memory_recall_block(_ctx())

        assert "standup moved to 9:30" in block

    async def test_empty_recall_is_an_empty_block(self) -> None:
        with patch(FETCHERS_ENGINE, _engine_double(memories=[])):
            assert await fetchers.build_memory_recall_block(_ctx()) == ""

    async def test_core_is_fetched_once_for_both_sections(self) -> None:
        """The singleflight is load-bearing.

        Without it every concurrent section pays its own core read."""
        import asyncio

        engine = _engine_double()
        with patch(FETCHERS_ENGINE, engine):
            ctx = _ctx()
            await asyncio.gather(
                fetchers.build_core_memory_block(ctx),
                fetchers.build_agenda_and_activity_block(ctx),
            )

        engine.get_core_context.assert_awaited_once_with(USER_ID)


class TestMemoryFailureDegradesTheTurn:
    async def test_recall_outage_is_an_empty_block_not_a_failed_turn(self) -> None:
        engine = AsyncMock()
        engine.recall = AsyncMock(side_effect=RuntimeError("chroma down"))
        with patch(FETCHERS_ENGINE, engine):
            assert await fetchers.build_memory_recall_block(_ctx()) == ""

    async def test_core_outage_empties_both_core_blocks(self) -> None:
        engine = AsyncMock()
        engine.get_core_context = AsyncMock(side_effect=RuntimeError("pg down"))
        with patch(FETCHERS_ENGINE, engine):
            ctx = _ctx()
            assert await fetchers.build_core_memory_block(ctx) == ""
            assert await fetchers.build_agenda_and_activity_block(ctx) == ""


def _fact(content: str = "sam likes green tea") -> ExtractedFact:
    return ExtractedFact(
        content=content,
        kind=MemoryKind.FACT,
        shelf_life=MemoryShelfLife.DURABLE,
        category_path="preferences",
        importance=0.5,
        entities=[],
        edges=[],
    )


def _row(content: str = "sam likes green tea", **overrides) -> MemoryRecord:
    data = {
        "id": uuid.uuid4(),
        "user_id": USER_ID,
        "kind": "fact",
        "content": content,
        "category_path": "preferences",
        "importance": 0.5,
        "version": 1,
        "is_latest": True,
        "is_forgotten": False,
        "forget_after": None,
        "mentioned_at": NOW,
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW,
        "source_type": "conversation",
        "metadata_json": {},
    }
    data.update(overrides)
    return MemoryRecord(**data)


async def _reconcile(fact: ExtractedFact, row: MemoryRecord | None, *, similarity: float = 0.99):
    llm = AsyncMock()
    similar = [(str(row.id), similarity)] if row is not None else []
    rows = [row] if row is not None else []
    with (
        patch.object(reconciliation.chroma_store, "query_similar", AsyncMock(return_value=similar)),
        patch.object(reconciliation.pg_store, "get_memories_by_ids", AsyncMock(return_value=rows)),
        patch.object(reconciliation, "reconcile_facts", llm),
        patch.object(reconciliation, "datetime", wraps=datetime) as clock,
    ):
        clock.now.return_value = NOW
        results = await reconciliation.reconcile(USER_ID, [fact], [EMBEDDING])
    return results, llm


class TestReconcileVerdicts:
    async def test_byte_identical_restatement_collapses_without_the_llm(self) -> None:
        fact = _fact()
        results, llm = await _reconcile(fact, _row(content=fact.content))

        assert len(results) == 1
        assert results[0].outcome is ReconcileOutcome.DUPLICATE
        llm.assert_not_awaited()

    async def test_novel_fact_is_new_without_the_llm(self) -> None:
        results, llm = await _reconcile(_fact("sam hates cilantro"), None)

        assert len(results) == 1
        assert results[0].outcome is ReconcileOutcome.NEW
        assert results[0].target_memory_id is None
        llm.assert_not_awaited()

    async def test_forgotten_row_never_absorbs_a_restatement(self) -> None:
        """Dead rows never absorb facts.

        Chroma metadata lags Postgres by one flag update; matching against
        the dead row would swallow the restatement as DUPLICATE forever."""
        fact = _fact()
        results, llm = await _reconcile(fact, _row(content=fact.content, is_forgotten=True))

        assert len(results) == 1
        assert results[0].outcome is ReconcileOutcome.NEW
        llm.assert_not_awaited()

    async def test_verdicts_keep_input_order_across_facts(self) -> None:
        dupe = _fact()
        dupe_row = _row(content=dupe.content)
        novel = _fact("sam adopted a cat")
        llm = AsyncMock()
        with (
            patch.object(
                reconciliation.chroma_store,
                "query_similar",
                AsyncMock(side_effect=[[(str(dupe_row.id), 0.99)], []]),
            ),
            patch.object(
                reconciliation.pg_store,
                "get_memories_by_ids",
                AsyncMock(return_value=[dupe_row]),
            ),
            patch.object(reconciliation, "reconcile_facts", llm),
            patch.object(reconciliation, "datetime", wraps=datetime) as clock,
        ):
            clock.now.return_value = NOW
            results = await reconciliation.reconcile(USER_ID, [dupe, novel], [EMBEDDING, EMBEDDING])

        assert [r.outcome for r in results] == [
            ReconcileOutcome.DUPLICATE,
            ReconcileOutcome.NEW,
        ]
        llm.assert_not_awaited()
