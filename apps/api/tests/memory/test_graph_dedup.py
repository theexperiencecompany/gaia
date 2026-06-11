"""Tests for graph edge deduplication — _dedupe_edges helper and insert_edges guard.

Two layers are tested:

1. Pure unit: ``_dedupe_edges`` collapses duplicate/bidirectional edges in
   memory without touching the DB.
2. Integration: ``insert_edges`` + ``get_graph`` write a pair and then confirm
   that a same-pair edge (different wording or opposite direction) is silently
   dropped, leaving only one edge in the graph.
"""

from collections.abc import Callable
from datetime import UTC, datetime
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.memory.pg_store.graph import _dedupe_edges, get_graph, insert_edges, upsert_entities
from app.models.memory_db_models import MemoryGraphEdge

pytestmark = pytest.mark.memory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)


def _make_edge(
    source_id: uuid.UUID,
    relationship: str,
    target_id: uuid.UUID,
    *,
    user_id: str = "test-user",
    memory_id: uuid.UUID | None = None,
) -> MemoryGraphEdge:
    """Build a detached MemoryGraphEdge for unit tests (no DB round-trip)."""
    edge = MemoryGraphEdge()
    edge.id = uuid.uuid4()
    edge.user_id = user_id
    edge.source_entity_id = source_id
    edge.relationship = relationship
    edge.target_entity_id = target_id
    edge.memory_id = memory_id
    edge.created_at = _NOW
    return edge


# ---------------------------------------------------------------------------
# Unit tests — _dedupe_edges (no DB required)
# ---------------------------------------------------------------------------


def test_dedupe_edges_empty() -> None:
    assert _dedupe_edges([]) == []


def test_dedupe_edges_single_edge_unchanged() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    edge = _make_edge(a, "is founder of", b)
    result = _dedupe_edges([edge])
    assert len(result) == 1
    assert result[0].relationship == "is founder of"


def test_dedupe_edges_same_pair_different_wording_keeps_longest() -> None:
    """'is founder and ceo of' beats 'is founder of' — more informative."""
    a, b = uuid.uuid4(), uuid.uuid4()
    short = _make_edge(a, "is founder of", b)
    long_ = _make_edge(a, "is founder and ceo of", b)
    result = _dedupe_edges([short, long_])
    assert len(result) == 1
    assert result[0].relationship == "is founder and ceo of"


def test_dedupe_edges_same_pair_different_wording_order_independent() -> None:
    """Order of input edges must not change which one wins."""
    a, b = uuid.uuid4(), uuid.uuid4()
    short = _make_edge(a, "is founder of", b)
    long_ = _make_edge(a, "is founder and ceo of", b)
    # long_ first
    result = _dedupe_edges([long_, short])
    assert len(result) == 1
    assert result[0].relationship == "is founder and ceo of"


def test_dedupe_edges_bidirectional_collapses_to_one() -> None:
    """Alice -is dating-> Bob  AND  Bob -is girlfriend of-> Alice → one edge."""
    a, b = uuid.uuid4(), uuid.uuid4()
    fwd = _make_edge(a, "is dating", b)
    rev = _make_edge(b, "is girlfriend of", a)
    result = _dedupe_edges([fwd, rev])
    assert len(result) == 1
    # The winning label must be the longer one.
    assert result[0].relationship == "is girlfriend of"


def test_dedupe_edges_preserves_original_direction() -> None:
    """Dedup must never flip an edge: relationship labels are directional.

    Swapping endpoints to a canonical order would invert the meaning
    ("Alice is from Lisbon" -> "Lisbon is from Alice").
    """
    a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    b = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    # Stored with the larger UUID as source — must come back unchanged.
    edge = _make_edge(b, "is from", a)
    result = _dedupe_edges([edge])
    assert len(result) == 1
    assert result[0].source_entity_id == b
    assert result[0].target_entity_id == a


def test_dedupe_edges_distinct_pairs_all_kept() -> None:
    """Three edges between three distinct pairs must all survive."""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    e1 = _make_edge(a, "knows", b)
    e2 = _make_edge(b, "works with", c)
    e3 = _make_edge(a, "mentors", c)
    result = _dedupe_edges([e1, e2, e3])
    assert len(result) == 3


# ---------------------------------------------------------------------------
# Integration tests — insert_edges + get_graph (requires real Postgres)
# ---------------------------------------------------------------------------


async def _seed_two_entities(user_id: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert two entities and return their IDs."""
    id_map = await upsert_entities(user_id, [("Alice", "person"), ("Bob", "person")])
    return id_map["alice"], id_map["bob"]


async def test_insert_edges_skips_same_pair_different_wording(
    make_memory_user: Callable[[], str],
    pg_engine: AsyncEngine,
) -> None:
    """A second edge with the same entity pair but different wording is dropped."""
    user_id = make_memory_user()
    alice_id, bob_id = await _seed_two_entities(user_id)

    # memory_id is None here: the edge dedup is independent of provenance, and a
    # fake memory_id would violate the memories FK.
    inserted1 = await insert_edges(user_id, [(alice_id, "knows", bob_id)], None)
    assert inserted1 == 1

    # Different wording, same pair — should be silently dropped.
    inserted2 = await insert_edges(user_id, [(alice_id, "is friends with", bob_id)], None)
    assert inserted2 == 0


async def test_insert_edges_skips_reverse_direction(
    make_memory_user: Callable[[], str],
    pg_engine: AsyncEngine,
) -> None:
    """A reverse-direction edge for an existing pair is dropped."""
    user_id = make_memory_user()
    alice_id, bob_id = await _seed_two_entities(user_id)

    await insert_edges(user_id, [(alice_id, "is dating", bob_id)], None)

    # Opposite direction — same unordered pair, must be dropped.
    inserted = await insert_edges(user_id, [(bob_id, "is boyfriend of", alice_id)], None)
    assert inserted == 0


async def test_get_graph_deduplicates_preexisting_duplicate_edges(
    make_memory_user: Callable[[], str],
    pg_engine: AsyncEngine,
) -> None:
    """get_graph collapses pre-existing duplicate edges that bypassed the write guard.

    Simulates edges that existed before the write guard was added (or were
    inserted via another path) and verifies _dedupe_edges is applied on read.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.memory.pg_store._session import memory_session

    user_id = make_memory_user()
    alice_id, bob_id = await _seed_two_entities(user_id)

    # Insert two edges for the same pair directly (bypassing insert_edges guard)
    # to simulate pre-existing duplicates.
    from app.constants.memory import MemoryKind, MemorySourceType
    from app.models.memory_db_models import MemoryRecord

    # We need a real memory_id so the get_graph join works.
    mem = MemoryRecord(
        user_id=user_id,
        kind=MemoryKind.FACT.value,
        content="Alice and Bob are colleagues.",
        category_path="work",
        source_type=MemorySourceType.MANUAL.value,
    )
    from app.memory import pg_store

    await pg_store.insert_memories([mem])

    async with memory_session() as session:
        await session.execute(
            pg_insert(MemoryGraphEdge)
            .values(
                [
                    {
                        "user_id": user_id,
                        "source_entity_id": alice_id,
                        "relationship": "works with",
                        "target_entity_id": bob_id,
                        "memory_id": mem.id,
                    },
                    {
                        "user_id": user_id,
                        "source_entity_id": bob_id,
                        "relationship": "is colleague of",
                        "target_entity_id": alice_id,
                        "memory_id": mem.id,
                    },
                ]
            )
            .on_conflict_do_nothing(constraint="uq_memory_graph_edges_triple")
        )
        await session.commit()

    _, edges = await get_graph(user_id)
    assert len(edges) == 1
    # Longer label wins.
    assert edges[0].relationship == "is colleague of"
