"""Contract tests for the scout store and signal memory against real Mongo update semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.scouts import ScoutsRepository
from app.db.repositories.signal_memory import SignalMemoryRepository
from app.models.scout_models import ScoutDocument, ScoutStatus, Signal

_START = datetime(2026, 10, 20, 7, 0, tzinfo=UTC)


def _signal(external_id: str, state: str | None, integration_id: str = "linear") -> Signal:
    return Signal(
        integration_id=integration_id,
        app="Linear",
        external_id=external_id,
        kind="issue",
        title=f"Issue {external_id}",
        state=state,
    )


@pytest.fixture
def memory(raw_collection) -> SignalMemoryRepository:
    return SignalMemoryRepository()


@pytest.fixture
def scouts(raw_collection) -> ScoutsRepository:
    return ScoutsRepository()


class TestSignalMemory:
    async def test_a_sighting_keeps_first_seen_and_tracks_the_latest_state(self, memory):
        await memory.record_seen("owner", [_signal("1", "Todo")], _START)
        await memory.record_seen("owner", [_signal("1", "Done")], _START + timedelta(days=2))

        [remembered] = await memory.find_for("owner", [_signal("1", None)])

        assert (remembered.first_seen, remembered.last_state, remembered.times_shown) == (
            _START,
            "Done",
            0,
        )

    async def test_marking_shown_counts_each_delivery_for_that_user_only(self, memory):
        signals = [_signal("1", "Todo"), _signal("2", "Todo")]
        await memory.record_seen("owner", signals, _START)
        await memory.record_seen("someone-else", signals, _START)

        await memory.mark_shown("owner", signals[:1], _START + timedelta(days=1))
        await memory.mark_shown("owner", signals[:1], _START + timedelta(days=2))

        owned = {m.external_id: m for m in await memory.find_for("owner", signals)}
        assert (owned["1"].times_shown, owned["1"].last_shown) == (2, _START + timedelta(days=2))
        assert (owned["2"].times_shown, owned["2"].last_shown) == (0, None)
        assert all(m.times_shown == 0 for m in await memory.find_for("someone-else", signals))

    async def test_forgetting_an_integration_leaves_the_others(self, memory):
        await memory.record_seen(
            "owner", [_signal("1", "Todo"), _signal("9", "Open", "github")], _START
        )

        assert await memory.delete_for_integration("owner", "linear") == 1

        assert [m.integration_id for m in await memory.list_for_user("owner")] == ["github"]


def _scout(fingerprint: str, user_id: str = "owner") -> ScoutDocument:
    return ScoutDocument(
        user_id=user_id,
        integration_id="linear",
        status=ScoutStatus.NOTHING_TO_WATCH,
        tool_fingerprint=fingerprint,
        learned_at=_START,
    )


class TestScouts:
    async def test_a_scout_stored_any_way_is_replaced_not_duplicated(self, scouts, raw_collection):
        await scouts.create(_scout("fp-1"))
        await scouts.create(_scout("fp-1", user_id="someone-else"))

        await scouts.replace(_scout("fp-2"))

        assert [s.tool_fingerprint for s in await scouts.list_for_user("owner")] == ["fp-2"]
        assert [s.tool_fingerprint for s in await scouts.list_for_user("someone-else")] == ["fp-1"]

    async def test_a_replaced_scout_is_stored_under_mongos_own_id_only(
        self, scouts, raw_collection
    ):
        await scouts.replace(_scout("fp-1"))

        [stored] = await raw_collection.find({}).to_list(None)
        assert "id" not in stored

    async def test_a_relearn_replaces_the_one_scout_per_integration(self, scouts):
        await scouts.replace(_scout("fp-1"))
        await scouts.replace(_scout("fp-2"))

        stored = await scouts.list_for_user("owner")
        assert [s.tool_fingerprint for s in stored] == ["fp-2"]
        found = await scouts.find_for("owner", "linear")
        assert found is not None and found.status is ScoutStatus.NOTHING_TO_WATCH
        assert await scouts.find_for("someone-else", "linear") is None
        assert await scouts.delete_for("owner", "linear") == 1
