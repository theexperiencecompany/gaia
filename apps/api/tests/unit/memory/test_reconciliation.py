"""Unit tests for ``app.memory.reconciliation`` — dedupe/supersession verdicts.

Chroma similarity, Postgres hydration and the reconcile LLM are mocked seams;
the similarity banding, exact-duplicate collapse and candidate liveness
filtering under test are real.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
import uuid

import pytest

from app.constants.memory import MemoryKind, MemoryShelfLife, ReconcileOutcome
from app.memory import reconciliation
from app.memory.schemas import ExtractedFact, ReconcileBatchResult, ReconcileDecision
from app.models.memory_db_models import MemoryRecord

USER = "user-1"
EMBEDDING = [0.1, 0.2]
NOW = datetime(2026, 8, 27, tzinfo=UTC)


def make_fact(content: str = "sam likes green tea") -> ExtractedFact:
    return ExtractedFact(
        content=content,
        kind=MemoryKind.FACT,
        shelf_life=MemoryShelfLife.DURABLE,
        category_path="preferences",
        importance=0.5,
        entities=[],
        edges=[],
    )


def make_row(
    content: str = "sam likes green tea",
    *,
    is_latest: bool = True,
    is_forgotten: bool = False,
    forget_after: datetime | None = None,
) -> MemoryRecord:
    """A detached candidate row — no session, no DB."""
    return MemoryRecord(
        id=uuid.uuid4(),
        user_id=USER,
        kind="fact",
        content=content,
        category_path="preferences",
        importance=0.5,
        version=1,
        is_latest=is_latest,
        is_forgotten=is_forgotten,
        forget_after=forget_after,
        mentioned_at=NOW,
        created_at=NOW - timedelta(days=2),
        updated_at=NOW,
        source_type="conversation",
        metadata_json={},
    )


async def _reconcile_one(
    fact: ExtractedFact,
    row: MemoryRecord,
    *,
    similarity: float = 0.99,
    llm: AsyncMock | None = None,
) -> tuple[list[reconciliation.ReconciledFact], AsyncMock]:
    """Run ``reconcile`` for one fact whose only Chroma hit hydrates to ``row``."""
    llm_mock = llm if llm is not None else AsyncMock(return_value=ReconcileBatchResult())
    with (
        patch.object(
            reconciliation.chroma_store,
            "query_similar",
            AsyncMock(return_value=[(str(row.id), similarity)]),
        ),
        patch.object(reconciliation.pg_store, "get_memories_by_ids", AsyncMock(return_value=[row])),
        patch.object(reconciliation, "reconcile_facts", llm_mock),
    ):
        results = await reconciliation.reconcile(USER, [fact], [EMBEDDING])
    return results, llm_mock


@pytest.mark.unit
class TestCandidateLiveness:
    """A dead row hydrated from a lagging Chroma match must never absorb a fact.

    Chroma metadata can lag Postgres by one flag update (the expiry sweep, a
    supersession, a forget), so a candidate that looks live in Chroma can
    hydrate to a dead row. Matching against it swallows an identical
    restatement as DUPLICATE forever.
    """

    async def test_forgotten_candidate_yields_new_not_duplicate(self) -> None:
        fact = make_fact()
        row = make_row(content=fact.content, is_forgotten=True)

        results, llm = await _reconcile_one(fact, row)

        (reconciled,) = results
        assert reconciled.outcome is ReconcileOutcome.NEW
        assert reconciled.target_memory_id is None
        llm.assert_not_awaited()

    async def test_expired_candidate_yields_new_not_duplicate(self) -> None:
        fact = make_fact()
        row = make_row(content=fact.content, forget_after=NOW - timedelta(days=1))

        results, llm = await _reconcile_one(fact, row)

        (reconciled,) = results
        assert reconciled.outcome is ReconcileOutcome.NEW
        assert reconciled.target_memory_id is None
        llm.assert_not_awaited()

    async def test_superseded_candidate_yields_new_not_duplicate(self) -> None:
        fact = make_fact()
        row = make_row(content=fact.content, is_latest=False)

        results, llm = await _reconcile_one(fact, row)

        (reconciled,) = results
        assert reconciled.outcome is ReconcileOutcome.NEW
        assert reconciled.target_memory_id is None
        llm.assert_not_awaited()

    async def test_live_identical_candidate_still_collapses_to_duplicate(self) -> None:
        """The liveness filter must not be over-broad: a genuinely live exact
        match keeps collapsing without the LLM."""
        fact = make_fact()
        row = make_row(content=fact.content, forget_after=NOW + timedelta(days=30))

        results, llm = await _reconcile_one(fact, row)

        (reconciled,) = results
        assert reconciled.outcome is ReconcileOutcome.DUPLICATE
        assert reconciled.target_memory_id == str(row.id)
        llm.assert_not_awaited()

    async def test_live_differing_candidate_still_reaches_the_llm(self) -> None:
        fact = make_fact("sam moved to lisbon")
        row = make_row(content="sam lives in berlin")
        llm = AsyncMock(
            return_value=ReconcileBatchResult(
                decisions=[
                    ReconcileDecision(
                        new_fact_index=0,
                        decision=ReconcileOutcome.UPDATES,
                        target_memory_id=str(row.id),
                    )
                ]
            )
        )

        results, llm = await _reconcile_one(fact, row, llm=llm)

        (reconciled,) = results
        assert reconciled.outcome is ReconcileOutcome.UPDATES
        assert reconciled.target_memory_id == str(row.id)
        llm.assert_awaited_once()
