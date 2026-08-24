"""Unit tests for the memory-store repair script's selection logic.

Pure functions only: which rows the script proposes to retire, and why. The
Postgres round trips it drives are not exercised here — the script is run by
hand against a real store, and the part that must be right before then is
which rows it picks.
"""

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.constants.memory import MemoryKind, MemoryShelfLife, MemorySourceType
from app.models.memory_db_models import MemoryRecord
from app.scripts.repair_memory_store import (
    extends_parents_to_retire,
    looks_like_state,
    state_rows_to_forget,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


def make_row(
    *,
    content: str = "sam works at acme",
    row_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    relation_type: str | None = None,
    shelf_life: MemoryShelfLife = MemoryShelfLife.DURABLE,
    age_days: int = 0,
) -> MemoryRecord:
    row = MemoryRecord(
        user_id="u1",
        kind=MemoryKind.FACT.value,
        shelf_life=shelf_life.value,
        content=content,
        category_path="work",
        source_type=MemorySourceType.CONVERSATION.value,
        importance=0.5,
    )
    row.id = row_id or uuid.uuid4()
    row.parent_id = parent_id
    row.relation_type = relation_type
    row.created_at = NOW - timedelta(days=age_days)
    return row


@pytest.mark.unit
class TestExtendsParentsToRetire:
    def test_a_live_parent_of_a_live_extends_child_is_retired(self) -> None:
        parent = make_row(content="sam works at acme")
        child = make_row(
            content="sam is a staff engineer at acme",
            parent_id=parent.id,
            relation_type="extends",
        )

        assert extends_parents_to_retire([parent, child]) == [(parent, child)]

    def test_a_parent_that_is_no_longer_live_is_left_alone(self) -> None:
        child = make_row(parent_id=uuid.uuid4(), relation_type="extends")

        assert extends_parents_to_retire([child]) == []

    def test_an_updates_child_is_not_touched(self) -> None:
        # UPDATES already superseded its parent; only the EXTENDS pairs that
        # were written to coexist need repairing.
        parent = make_row()
        child = make_row(parent_id=parent.id, relation_type="updates")

        assert extends_parents_to_retire([parent, child]) == []

    def test_a_parent_with_several_extends_children_is_retired_once(self) -> None:
        parent = make_row()
        first = make_row(parent_id=parent.id, relation_type="extends", age_days=2)
        second = make_row(parent_id=parent.id, relation_type="extends", age_days=1)

        retired = extends_parents_to_retire([parent, first, second])

        assert [pair[0] for pair in retired] == [parent]
        # The newest child is the one that survives, so it is the one cited.
        assert retired[0][1] is second


@pytest.mark.unit
class TestLooksLikeState:
    @pytest.mark.parametrize(
        "content",
        [
            "As of August 2026 Sam has 18 active workflows",
            "Sam currently has Gmail disconnected",
            "The billing migration is failing in production",
            "Sam's Slack integration is disconnected",
            "Sam's Pro upgrade is pending",
        ],
    )
    def test_a_snapshot_phrase_is_state(self, content: str) -> None:
        assert looks_like_state(content) is True

    @pytest.mark.parametrize(
        "content",
        [
            "Sam's anniversary is October 19",
            "Sam is vegetarian",
            "Sam's partner is Khyati Sheth",
            "Sam prefers concise replies with no em dashes",
        ],
    )
    def test_a_durable_fact_is_not_state(self, content: str) -> None:
        assert looks_like_state(content) is False

    def test_the_match_is_not_fooled_by_a_word_that_merely_contains_a_keyword(self) -> None:
        assert looks_like_state("Sam works on concurrency at Acme") is False


@pytest.mark.unit
class TestStateRowsToForget:
    def test_a_backfilled_state_row_past_the_window_is_forgotten(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=90)

        assert state_rows_to_forget([row], now=NOW) == [row]

    def test_a_backfilled_state_row_inside_the_window_is_kept(self) -> None:
        row = make_row(shelf_life=MemoryShelfLife.STATE, age_days=10)

        assert state_rows_to_forget([row], now=NOW) == []

    def test_a_legacy_durable_row_falls_back_to_the_phrase_heuristic(self) -> None:
        # Rows written before shelf_life existed all read as 'durable'.
        stale = make_row(content="Gmail is currently disconnected", age_days=120)
        real = make_row(content="Sam's anniversary is October 19", age_days=120)

        assert state_rows_to_forget([stale, real], now=NOW) == [stale]

    def test_the_heuristic_never_reaches_a_recent_row(self) -> None:
        row = make_row(content="Gmail is currently disconnected", age_days=3)

        assert state_rows_to_forget([row], now=NOW) == []
