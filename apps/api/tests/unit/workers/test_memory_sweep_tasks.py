"""Unit tests for the nightly memory expiry sweep.

Postgres and the per-user follow-ups are mocked; the sweep's own orchestration
(which users get re-rendered, what the summary reports) is real.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.tasks.memory_sweep_tasks import sweep_expired_memories
from tests.helpers import captured_wide_event


@pytest.fixture
def sweep_boundaries() -> dict[str, AsyncMock]:
    mocks = {
        "sweep": AsyncMock(return_value=[]),
        "count": AsyncMock(return_value=3),
        "render": AsyncMock(return_value=None),
        "seed": AsyncMock(return_value=None),
        "invalidate": AsyncMock(return_value=None),
    }
    with (
        patch(
            "app.workers.tasks.memory_sweep_tasks.pg_store.sweep_expired_memories", mocks["sweep"]
        ),
        patch("app.workers.tasks.memory_sweep_tasks.pg_store.count_live_memories", mocks["count"]),
        patch("app.workers.tasks.memory_sweep_tasks.render_agenda_document", mocks["render"]),
        patch("app.workers.tasks.memory_sweep_tasks.set_cached_live_count", mocks["seed"]),
        patch(
            "app.workers.tasks.memory_sweep_tasks.invalidate_user_memory_caches",
            mocks["invalidate"],
        ),
    ):
        yield mocks


@pytest.mark.unit
class TestSweepExpiredMemories:
    async def test_reports_how_many_rows_it_retired(
        self, sweep_boundaries: dict[str, AsyncMock]
    ) -> None:
        sweep_boundaries["sweep"].return_value = ["u1", "u1", "u2"]

        summary = await sweep_expired_memories({})

        assert summary == "expired=3 users=2"

    async def test_each_affected_user_is_repaired_exactly_once(
        self, sweep_boundaries: dict[str, AsyncMock]
    ) -> None:
        sweep_boundaries["sweep"].return_value = ["u1", "u1", "u2"]

        await sweep_expired_memories({})

        assert {call.args[0] for call in sweep_boundaries["render"].await_args_list} == {"u1", "u2"}
        assert sweep_boundaries["render"].await_count == 2
        assert [call.args for call in sweep_boundaries["invalidate"].await_args_list] == [
            ("u1",),
            ("u2",),
        ]

    async def test_the_free_plan_counter_is_reseeded_from_the_authoritative_count(
        self, sweep_boundaries: dict[str, AsyncMock]
    ) -> None:
        sweep_boundaries["sweep"].return_value = ["u1"]
        sweep_boundaries["count"].return_value = 7

        await sweep_expired_memories({})

        assert sweep_boundaries["count"].await_args.args == ("u1",)
        assert sweep_boundaries["seed"].await_args.args == ("u1", 7)

    async def test_the_sweep_is_reported_on_the_wide_event(
        self, sweep_boundaries: dict[str, AsyncMock]
    ) -> None:
        # The nightly task has no caller to return to — the wide event is the
        # only place the night's work is visible.
        sweep_boundaries["sweep"].return_value = ["u1", "u1", "u2"]

        async with captured_wide_event() as event:
            await sweep_expired_memories({})

        assert event["memory_sweep"] == {"memories_expired": 3, "users_repaired": 2}

    async def test_a_clean_sweep_touches_nobody(
        self, sweep_boundaries: dict[str, AsyncMock]
    ) -> None:
        await sweep_expired_memories({})

        sweep_boundaries["render"].assert_not_awaited()
        sweep_boundaries["seed"].assert_not_awaited()
        sweep_boundaries["invalidate"].assert_not_awaited()
