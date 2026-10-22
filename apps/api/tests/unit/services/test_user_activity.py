"""record_activity, activity_status_of and reactivate_user: recording, reading and returning from user activity."""

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.constants.cache import LAST_ACTIVE_DEBOUNCE_SECONDS, LAST_ACTIVE_GATE_PREFIX
from app.constants.user_activity import IDLE_AFTER, REACTIVATE_USER_TASK, ActivityStatus
from app.models.scheduler_models import DeactivationReason
from app.models.user_activity_models import UserActivityDates
from app.services.user_activity.reactivation import reactivate_user
from app.services.user_activity.recording import record_activity
from app.services.user_activity.status import activity_status_of
from shared.py.analytics.catalog.attribution import EntrySurface

RECORDING = "app.services.user_activity.recording"
REACTIVATION = "app.services.user_activity.reactivation"
STATUS = "app.services.user_activity.status"
NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)


@pytest.fixture
def seam() -> Iterator[SimpleNamespace]:
    """Patch record_activity's collaborators; every call is also logged to one ordered list."""
    calls: list[str] = []
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=0)
    redis.set = AsyncMock()
    status = AsyncMock(return_value=ActivityStatus.ACTIVE)
    enqueue = AsyncMock(side_effect=lambda *a, **k: calls.append("enqueue"))
    write = AsyncMock(side_effect=lambda *a, **k: calls.append("write"))
    with (
        patch(f"{RECORDING}.redis_cache", SimpleNamespace(redis=redis)),
        patch(f"{RECORDING}.activity_status_of", status),
        patch(f"{RECORDING}.RedisPoolManager.get_pool", AsyncMock(return_value="pool")),
        patch(f"{RECORDING}.enqueue_worker_job", enqueue),
        patch(f"{RECORDING}.user_repository.set_last_active", write),
        patch(f"{RECORDING}.log") as log,
    ):
        yield SimpleNamespace(
            calls=calls, redis=redis, status=status, enqueue=enqueue, write=write, log=log
        )


@pytest.mark.unit
class TestRecordActivity:
    @time_machine.travel(NOW, tick=False)
    async def test_it_writes_now_and_closes_the_gate(self, seam):
        await record_activity("u1", EntrySurface.WEB)

        gate = f"{LAST_ACTIVE_GATE_PREFIX}:u1"
        seam.redis.exists.assert_awaited_once_with(gate)
        seam.status.assert_awaited_once_with("u1")
        seam.write.assert_awaited_once_with("u1", NOW)
        seam.redis.set.assert_awaited_once_with(gate, "1", ex=LAST_ACTIVE_DEBOUNCE_SECONDS)
        seam.enqueue.assert_not_awaited()
        seam.log.set_ns.assert_called_once_with("activity", surface="web", previous_status="active")

    async def test_a_second_request_inside_the_window_writes_nothing(self, seam):
        seam.redis.exists.return_value = 1

        await record_activity("u1", EntrySurface.BOT)

        seam.status.assert_not_awaited()
        seam.write.assert_not_awaited()

    async def test_a_dormant_user_is_reactivated_before_being_marked_active(self, seam):
        """Queued first, so a failed enqueue leaves the user dormant for the next request to retry."""
        seam.status.return_value = ActivityStatus.DORMANT

        await record_activity("u1", EntrySurface.VOICE)

        assert seam.calls == ["enqueue", "write"]
        assert seam.enqueue.await_args.args == ("pool", REACTIVATE_USER_TASK, "u1")
        assert seam.enqueue.await_args.kwargs["_job_id"] == f"{REACTIVATE_USER_TASK}:u1"

    async def test_a_failed_reactivation_enqueue_leaves_the_user_dormant(self, seam):
        seam.status.return_value = ActivityStatus.DORMANT
        seam.enqueue.side_effect = ConnectionError("redis down")

        with pytest.raises(ConnectionError):
            await record_activity("u1", EntrySurface.WEB)

        seam.write.assert_not_awaited()
        seam.redis.set.assert_not_awaited()

    @pytest.mark.parametrize("status", [ActivityStatus.ACTIVE, ActivityStatus.IDLE])
    async def test_only_a_dormant_user_is_reactivated(self, seam, status):
        seam.status.return_value = status

        await record_activity("u1", EntrySurface.WEB)

        seam.enqueue.assert_not_awaited()
        seam.write.assert_awaited_once()

    async def test_without_redis_every_call_writes(self, seam):
        with patch(f"{RECORDING}.redis_cache", SimpleNamespace(redis=None)):
            await record_activity("u1", EntrySurface.WEB)

        seam.write.assert_awaited_once()


@pytest.mark.unit
class TestReactivateUser:
    async def test_workflows_and_tracked_todos_paused_for_dormancy_resume(self):
        workflows = AsyncMock(return_value=2)
        todos = AsyncMock(return_value=3)
        with (
            patch(f"{REACTIVATION}.resume_dormancy_paused_workflows", workflows),
            patch(f"{REACTIVATION}.tracked_todo_service.resume_paused_for", todos),
            patch(f"{REACTIVATION}.log") as log,
        ):
            resumed = await reactivate_user("u1")

        assert resumed == 5
        log.set_ns.assert_called_once_with("reactivation", workflows_resumed=2, todos_resumed=3)
        workflows.assert_awaited_once_with("u1")
        todos.assert_awaited_once_with("u1", DeactivationReason.USER_DORMANT)

    async def test_a_todo_that_fails_to_resume_fails_the_reactivation(self):
        with (
            patch(f"{REACTIVATION}.resume_dormancy_paused_workflows", AsyncMock(return_value=1)),
            patch(
                f"{REACTIVATION}.tracked_todo_service.resume_paused_for",
                AsyncMock(side_effect=ExceptionGroup("todos", [RuntimeError("arq")])),
            ),
            pytest.raises(ExceptionGroup),
        ):
            await reactivate_user("u1")


@pytest.mark.unit
class TestActivityStatusOf:
    @time_machine.travel(NOW, tick=False)
    async def test_the_status_is_judged_from_the_stored_dates_at_now(self):
        dates = UserActivityDates(last_active_at=NOW - IDLE_AFTER)
        read = AsyncMock(return_value=dates)
        with patch(f"{STATUS}.user_repository.get_activity_dates", read):
            assert await activity_status_of("u1") is ActivityStatus.IDLE
        read.assert_awaited_once_with("u1")

    async def test_an_id_that_is_no_user_raises(self):
        with (
            patch(f"{STATUS}.user_repository.get_activity_dates", AsyncMock(return_value=None)),
            pytest.raises(LookupError, match="no user u1"),
        ):
            await activity_status_of("u1")
