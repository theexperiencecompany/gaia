"""Unit tests for app.workers.tasks.maintenance_sweep_tasks.

The cron that keeps tracked todos honest: expired todos get a health-check
agent pass (archive/notify), overdue todos get an individual notification,
dormant todos get re-queued or bundled into a digest. The backoff escalation
(`_register_notification`) is the load-bearing part — a stuck todo must stop
nagging once the schedule is exhausted, and the daytime gate must keep
notifications out of the user's night.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.workers.tasks.maintenance_sweep_tasks import (
    DORMANT_DAYS,
    MAX_HEALTH_CHECKS_PER_USER,
    NOTIFICATION_BACKOFF_DAYS,
    NOTIFICATION_MUTE_DAYS,
    SECONDS_PER_DAY,
    STRIKE_TTL_DAYS,
    WAITING_LABEL_MAX_DAYS,
    _classify_tracked_todos,
    _has_upcoming_schedule,
    _health_check_dormant,
    _health_check_expired,
    _is_dormant,
    _is_user_daytime,
    _notify_overdue,
    _process_dormant,
    _process_expired,
    _process_overdue,
    _register_notification,
    _send_individual_notification,
    _send_user_dormant_digest,
    _todo_redirect_action,
    maintenance_sweep_tracked_todos,
)

MODULE = "app.workers.tasks.maintenance_sweep_tasks"

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _doc(**overrides) -> TodoDocument:
    fields: dict = {
        "id": "todo-1",
        "user_id": "user-1",
        "title": "Follow up with the client",
        "labels": [],
        "updated_at": NOW - timedelta(days=10),
    }
    fields.update(overrides)
    return TodoDocument(**fields)


def _pool(**overrides) -> MagicMock:
    pool = MagicMock()
    pool.exists = AsyncMock(return_value=0)
    pool.set = AsyncMock(return_value=True)
    pool.get = AsyncMock(return_value=None)
    for key, value in overrides.items():
        setattr(pool, key, value)
    return pool


def _sweep_patches(**overrides) -> tuple[MagicMock, dict[str, AsyncMock], list]:
    """The patches an end-to-end sweep needs, with overridable return values.

    Returns ``(pool, mocks, patches)`` where ``mocks`` keys name each seam.
    """
    defaults = {
        "list": [_doc()],
        "daytime": True,
        "canvas": "",
        "health": "NEEDS_ATTENTION: nothing to do",
    }
    defaults.update(overrides)
    pool = _pool()
    mocks: dict[str, AsyncMock] = {
        "list": AsyncMock(return_value=defaults["list"]),
        "get_pool": AsyncMock(return_value=pool),
        "daytime": AsyncMock(return_value=defaults["daytime"]),
        "canvas": AsyncMock(return_value=defaults["canvas"]),
        "health": AsyncMock(return_value=defaults["health"]),
        "archive": AsyncMock(),
        "schedule": AsyncMock(),
        "system_log": AsyncMock(),
        "add_labels": AsyncMock(),
        "notify": AsyncMock(),
        "info": MagicMock(),
        "log_set": MagicMock(),
    }
    patches = [
        patch(f"{MODULE}.todo_repository.list_active_tracked_all_users", mocks["list"]),
        patch(f"{MODULE}.RedisPoolManager.get_pool", mocks["get_pool"]),
        patch(f"{MODULE}._is_user_daytime", mocks["daytime"]),
        patch(f"{MODULE}._read_canvas", mocks["canvas"]),
        patch(f"{MODULE}._call_health_check_agent", mocks["health"]),
        patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", mocks["archive"]),
        patch(f"{MODULE}.tracked_todo_service.schedule_execution", mocks["schedule"]),
        patch(f"{MODULE}.tracked_todo_service.system_log", mocks["system_log"]),
        patch(f"{MODULE}.todo_repository.add_labels", mocks["add_labels"]),
        patch(f"{MODULE}.notification_service.create_notification", mocks["notify"]),
        patch(f"{MODULE}.log.info", mocks["info"]),
        patch(f"{MODULE}.log.set", mocks["log_set"]),
    ]
    return pool, mocks, patches


@contextmanager
def _sweep(**overrides) -> Iterator[tuple[MagicMock, dict[str, AsyncMock]]]:
    """An end-to-end sweep with every seam mocked; yields ``(pool, mocks)``."""
    pool, mocks, patches = _sweep_patches(**overrides)
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield pool, mocks


# ---------------------------------------------------------------------------
# _has_upcoming_schedule / _is_dormant — pure classification logic
# ---------------------------------------------------------------------------


class TestHasUpcomingSchedule:
    def test_future_scheduled_at_counts(self):
        assert _has_upcoming_schedule(_doc(scheduled_at=NOW + timedelta(hours=2)), NOW) is True

    def test_recent_recurring_execution_counts(self):
        assert (
            _has_upcoming_schedule(
                _doc(scheduled_at=NOW - timedelta(days=1), recurrence="daily"), NOW
            )
            is True
        )

    def test_stale_recurring_execution_is_orphaned(self):
        assert (
            _has_upcoming_schedule(
                _doc(scheduled_at=NOW - timedelta(days=5), recurrence="daily"), NOW
            )
            is False
        )

    def test_recurrence_without_schedule_is_orphaned(self):
        assert _has_upcoming_schedule(_doc(recurrence="daily"), NOW) is False

    def test_plain_todo_without_schedule(self):
        assert _has_upcoming_schedule(_doc(), NOW) is False

    def test_scheduled_exactly_now_does_not_count_without_recurrence(self):
        assert _has_upcoming_schedule(_doc(scheduled_at=NOW), NOW) is False

    def test_recurring_executed_exactly_two_days_ago_is_not_stale(self):
        assert (
            _has_upcoming_schedule(
                _doc(scheduled_at=NOW - timedelta(days=2), recurrence="daily"), NOW
            )
            is True
        )

    def test_recurring_executed_three_days_ago_is_orphaned(self):
        assert (
            _has_upcoming_schedule(
                _doc(scheduled_at=NOW - timedelta(days=3), recurrence="daily"), NOW
            )
            is False
        )


class TestIsDormant:
    def test_idle_past_threshold_without_schedule_is_dormant(self):
        assert _is_dormant(_doc(updated_at=NOW - timedelta(days=10)), NOW) is True

    def test_recently_updated_is_not_dormant(self):
        assert _is_dormant(_doc(updated_at=NOW - timedelta(days=2)), NOW) is False

    def test_idle_at_exactly_the_threshold_is_not_dormant(self):
        assert _is_dormant(_doc(updated_at=NOW - timedelta(days=DORMANT_DAYS)), NOW) is False

    def test_upcoming_schedule_rescues_an_idle_todo(self):
        doc = _doc(
            updated_at=NOW - timedelta(days=10),
            scheduled_at=NOW + timedelta(hours=1),
        )
        assert _is_dormant(doc, NOW) is False

    def test_fresh_blocking_label_suppresses_surfacing(self):
        doc = _doc(updated_at=NOW - timedelta(days=3), labels=["blocked"])
        assert _is_dormant(doc, NOW) is False

    def test_stuck_blocking_label_surfaces_after_max_days(self):
        doc = _doc(updated_at=NOW - timedelta(days=10), labels=["waiting-for-approval"])
        assert _is_dormant(doc, NOW) is True

    def test_missing_updated_at_is_never_dormant(self):
        assert _is_dormant(_doc(updated_at=None), NOW) is False

    def test_blocking_label_suppresses_surfacing_within_max_days(self):
        doc = _doc(updated_at=NOW - timedelta(days=6), labels=["blocked"])
        assert _is_dormant(doc, NOW) is False

    def test_blocking_label_at_exactly_max_days_is_not_stuck_yet(self):
        doc = _doc(updated_at=NOW - timedelta(days=WAITING_LABEL_MAX_DAYS), labels=["blocked"])
        assert _is_dormant(doc, NOW) is False


# ---------------------------------------------------------------------------
# _classify_tracked_todos — tier bucketing
# ---------------------------------------------------------------------------


class TestClassifyTrackedTodos:
    async def _classify(self, pool: MagicMock, todos: list[TodoDocument]):
        list_mock = AsyncMock(return_value=todos)
        with patch(f"{MODULE}.todo_repository.list_active_tracked_all_users", list_mock):
            expired, overdue, dormant = await _classify_tracked_todos(pool, NOW)
        return expired, overdue, dormant, list_mock

    async def test_buckets_expired_overdue_and_dormant(self):
        pool = _pool()
        todos = [
            _doc(id="exp", expires_at=NOW - timedelta(hours=1), updated_at=NOW),
            _doc(id="due", due_date=NOW - timedelta(days=1), updated_at=NOW),
            _doc(id="dor", updated_at=NOW - timedelta(days=10)),
            _doc(id="fine", updated_at=NOW),
        ]
        expired, overdue, dormant, list_mock = await self._classify(pool, todos)

        assert [t.id for t in expired] == ["exp"]
        assert [t.id for t in overdue] == ["due"]
        assert [t.id for t in dormant] == ["dor"]
        list_mock.assert_awaited_once_with(limit=200)

    async def test_todo_in_cooldown_is_skipped(self):
        pool = _pool()
        pool.exists = AsyncMock(side_effect=lambda key: 1 if "todo-1" in key else 0)
        todos = [
            _doc(id="todo-1", expires_at=NOW - timedelta(hours=1)),
            _doc(id="todo-2", expires_at=NOW - timedelta(hours=1)),
        ]
        expired, _overdue, _dormant, _list_mock = await self._classify(pool, todos)

        assert [t.id for t in expired] == ["todo-2"]

    async def test_due_todo_with_upcoming_schedule_is_not_overdue(self):
        pool = _pool()
        todos = [
            _doc(
                id="sched",
                due_date=NOW - timedelta(days=1),
                scheduled_at=NOW + timedelta(hours=1),
            )
        ]
        _expired, overdue, _dormant, _list_mock = await self._classify(pool, todos)
        assert overdue == []

    async def test_each_tier_is_capped_at_20(self):
        pool = _pool()
        todos = [_doc(id=f"exp-{i}", expires_at=NOW - timedelta(hours=1)) for i in range(25)] + [
            _doc(id=f"dor-{i}", updated_at=NOW - timedelta(days=10)) for i in range(25)
        ]
        expired, _overdue, dormant, _list_mock = await self._classify(pool, todos)

        assert len(expired) == 20
        assert len(dormant) == 20

    async def test_overdue_tier_capped_at_20(self):
        pool = _pool()
        todos = [_doc(id=f"due-{i}", due_date=NOW - timedelta(days=1)) for i in range(25)]
        _expired, overdue, _dormant, _list_mock = await self._classify(pool, todos)
        assert len(overdue) == 20

    async def test_expired_at_exactly_now_is_expired(self):
        pool = _pool()
        expired, _overdue, _dormant, _list_mock = await self._classify(
            pool, [_doc(id="exact", expires_at=NOW, updated_at=NOW)]
        )
        assert [t.id for t in expired] == ["exact"]

    async def test_due_exactly_now_is_overdue(self):
        pool = _pool()
        _expired, overdue, _dormant, _list_mock = await self._classify(
            pool, [_doc(id="exact", due_date=NOW, updated_at=NOW)]
        )
        assert [t.id for t in overdue] == ["exact"]

    async def test_empty_scan_returns_empty_tiers(self):
        pool = _pool()
        expired, overdue, dormant, _list_mock = await self._classify(pool, [])
        assert (expired, overdue, dormant) == ([], [], [])


# ---------------------------------------------------------------------------
# _health_check_expired — archive / notify / mute
# ---------------------------------------------------------------------------


class TestHealthCheckExpired:
    async def test_archive_decision_archives_and_cooldowns(self):
        pool = _pool()
        archive = AsyncMock()
        health = AsyncMock(return_value="ARCHIVE: everything resolved itself")
        todo = _doc()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="canvas text")) as canvas,
            patch(f"{MODULE}._call_health_check_agent", health),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", archive),
            patch(f"{MODULE}.log.info") as info,
        ):
            outcome = await _health_check_expired(todo, pool)

        assert outcome == "archived"
        archive.assert_awaited_once_with("todo-1", "user-1", "everything resolved itself")
        canvas.assert_awaited_once_with(todo)
        health.assert_awaited_once_with(
            "todo-1",
            "user-1",
            "A tracked todo has expired.\n"
            "Title: Follow up with the client\n"
            "Canvas:\ncanvas text\n\n"
            "Did this expire cleanly (i.e. no further action is needed)? "
            "Respond with exactly one of:\n"
            "ARCHIVE: <brief reason>\n"
            "NOTIFY: <message to send to the user>",
        )
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY
        )
        info.assert_called_once_with(
            "maintenance_sweep.expired_archived",
            todo_id="todo-1",
            reason="everything resolved itself",
        )

    async def test_notify_decision_sends_a_warning_notification(self):
        pool = _pool()
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="NOTIFY: Your todo expired and needs a decision."),
            ),
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.log.info") as info,
        ):
            outcome = await _health_check_expired(_doc(title="Ship the report"), pool)

        assert outcome == "notified"
        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.WARNING
        assert request.content.title == "Expired: Ship the report"
        assert request.content.body == "Your todo expired and needs a decision."
        assert request.content.actions[0].label == "View todo"
        assert request.content.actions[0].style == ActionStyle.PRIMARY
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"
        assert request.metadata == {"todo_id": "todo-1"}
        pool.set.assert_awaited_with("gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY)
        info.assert_called_once_with(
            "maintenance_sweep.expired_notified", todo_id="todo-1"
        )

    async def test_muted_todo_after_backoff_is_exhausted_sends_nothing(self):
        pool = _pool()
        pool.get = AsyncMock(return_value=b"4")
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="NOTIFY: still expired"),
            ),
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.log.info") as info,
        ):
            outcome = await _health_check_expired(_doc(), pool)

        assert outcome == "muted"
        notify.assert_not_awaited()
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=NOTIFICATION_MUTE_DAYS * SECONDS_PER_DAY
        )
        info.assert_called_once_with("maintenance_sweep.expired_muted", todo_id="todo-1")

    async def test_agent_failure_still_notifies_with_the_failure_text(self):
        pool = _pool()
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="NEEDS_ATTENTION: Health check failed"),
            ),
            patch(f"{MODULE}.notification_service.create_notification", notify),
        ):
            outcome = await _health_check_expired(_doc(), pool)

        assert outcome == "notified"
        assert notify.await_args.args[0].content.body == "NEEDS_ATTENTION: Health check failed"


# ---------------------------------------------------------------------------
# _health_check_dormant — requeue / needs attention
# ---------------------------------------------------------------------------


class TestHealthCheckDormant:
    async def test_execute_decision_re_queues_with_exact_jitter_window(self):
        pool = _pool()
        schedule = AsyncMock()
        syslog = AsyncMock()
        todo = _doc()
        fake_dt = MagicMock()
        fake_dt.now.return_value = NOW
        random_mock = MagicMock()
        random_mock.randint.return_value = 60
        with (
            patch(f"{MODULE}.datetime", fake_dt),
            patch(f"{MODULE}.random", random_mock),
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="canvas text")) as canvas,
            patch(f"{MODULE}._call_health_check_agent", AsyncMock(return_value="EXECUTE: send the follow-up email")) as health,
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", schedule),
            patch(f"{MODULE}.tracked_todo_service.system_log", syslog),
            patch(f"{MODULE}.log.info") as info,
        ):
            outcome = await _health_check_dormant(todo, pool)

        assert outcome == "requeued"
        canvas.assert_awaited_once_with(todo)
        random_mock.randint.assert_called_once_with(10, 120)
        schedule.assert_awaited_once_with("todo-1", NOW + timedelta(seconds=60))
        health.assert_awaited_once_with(
            "todo-1",
            "user-1",
            "A tracked todo has been dormant for 10 days.\n"
            "Title: Follow up with the client\n"
            "Canvas:\ncanvas text\n\n"
            "Is there a clear, concrete next action that can be taken right now? "
            "Respond with exactly one of:\n"
            "EXECUTE: <specific action to perform immediately>\n"
            "NEEDS_ATTENTION: <brief summary of why this needs human review>",
        )
        syslog.assert_awaited_once_with(
            "todo-1",
            "user-1",
            "maintenance_requeued",
            "Dormant todo re-queued by maintenance sweep (idle 10d). Action: send the follow-up email",
        )
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY
        )
        info.assert_called_once_with(
            "maintenance_sweep.dormant_requeued",
            todo_id="todo-1",
            scheduled_at=(NOW + timedelta(seconds=60)).isoformat(),
        )

    async def test_needs_attention_does_not_touch_the_schedule(self):
        pool = _pool()
        schedule = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="NEEDS_ATTENTION: blocked on client sign-off"),
            ),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", schedule),
            patch(f"{MODULE}.log.info") as info,
        ):
            outcome = await _health_check_dormant(_doc(), pool)

        assert outcome == "needs_attention"
        schedule.assert_not_awaited()
        pool.set.assert_not_awaited()
        info.assert_called_once_with(
            "maintenance_sweep.dormant_needs_attention", todo_id="todo-1"
        )

    async def test_agent_failure_is_needs_attention(self):
        pool = _pool()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="NEEDS_ATTENTION: Health check failed"),
            ),
        ):
            outcome = await _health_check_dormant(_doc(), pool)
        assert outcome == "needs_attention"

    async def test_prompt_uses_dormant_days_when_updated_at_missing(self):
        pool = _pool()
        fake_dt = MagicMock()
        fake_dt.now.return_value = NOW
        health = AsyncMock(return_value="NEEDS_ATTENTION: gone quiet")
        with (
            patch(f"{MODULE}.datetime", fake_dt),
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(f"{MODULE}._call_health_check_agent", health),
        ):
            outcome = await _health_check_dormant(_doc(updated_at=None), pool)

        assert outcome == "needs_attention"
        assert health.await_args.args[2].startswith(
            "A tracked todo has been dormant for 5 days.\n"
        )


# ---------------------------------------------------------------------------
# _notify_overdue
# ---------------------------------------------------------------------------


class TestNotifyOverdue:
    async def test_notifies_and_labels_needs_follow_up(self):
        pool = _pool()
        notify = AsyncMock()
        add_labels = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.todo_repository.add_labels", add_labels),
            patch(f"{MODULE}.log.info") as info,
        ):
            # due_date is relative to real now — _notify_overdue computes
            # "days overdue" from its own clock, not the test's frozen NOW.
            result = await _notify_overdue(
                _doc(title="Pay the invoice", due_date=datetime.now(UTC) - timedelta(days=2)),
                pool,
            )

        assert result is True
        request = notify.await_args.args[0]
        assert request.content.title == "Overdue: Pay the invoice"
        assert request.content.body == (
            "'Pay the invoice' was due 2 days ago and has no scheduled follow-up."
        )
        assert request.content.actions[0].label == "View todo"
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"
        assert request.metadata == {"todo_id": "todo-1"}
        add_labels.assert_awaited_once_with("todo-1", user_id="user-1", labels=["needs-follow-up"])
        pool.set.assert_awaited_with("gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY)
        info.assert_called_once_with(
            "maintenance_sweep.overdue_notified", todo_id="todo-1", days_overdue=2
        )

    async def test_single_day_overdue_uses_singular_day(self):
        pool = _pool()
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.todo_repository.add_labels", AsyncMock()),
        ):
            result = await _notify_overdue(
                _doc(title="Ship it", due_date=datetime.now(UTC) - timedelta(days=1)),
                pool,
            )

        assert result is True
        request = notify.await_args.args[0]
        assert request.content.body == (
            "'Ship it' was due 1 day ago and has no scheduled follow-up."
        )

    async def test_missing_due_date_reports_zero_days(self):
        pool = _pool()
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.todo_repository.add_labels", AsyncMock()),
        ):
            result = await _notify_overdue(_doc(due_date=None), pool)

        assert result is True
        request = notify.await_args.args[0]
        assert request.content.body == (
            "'Follow up with the client' was due 0 days ago and has no scheduled follow-up."
        )

    async def test_muted_overdue_sends_nothing(self):
        pool = _pool()
        pool.get = AsyncMock(return_value="4")
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.todo_repository.add_labels", AsyncMock()),
            patch(f"{MODULE}.log.info") as info,
        ):
            result = await _notify_overdue(_doc(), pool)

        assert result is False
        notify.assert_not_awaited()
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=NOTIFICATION_MUTE_DAYS * SECONDS_PER_DAY
        )
        info.assert_called_once_with("maintenance_sweep.overdue_muted", todo_id="todo-1")


# ---------------------------------------------------------------------------
# _register_notification — the escalating backoff
# ---------------------------------------------------------------------------


class TestRegisterNotification:
    async def test_first_strike_sets_a_one_day_cooldown(self):
        pool = _pool()
        assert await _register_notification(pool, "todo-1") is True

        pool.get.assert_awaited_once_with("gaia_maintenance_strikes:todo-1")
        calls = [(c.args, c.kwargs) for c in pool.set.await_args_list]
        assert (
            ("gaia_maintenance_strikes:todo-1", "1"),
            {"ex": STRIKE_TTL_DAYS * SECONDS_PER_DAY},
        ) in calls
        assert (
            ("gaia_maintenance_notified:todo-1", "1"),
            {"ex": NOTIFICATION_BACKOFF_DAYS[0] * SECONDS_PER_DAY},
        ) in calls

    @pytest.mark.parametrize(
        ("strike", "expected_ex"),
        [("1", 3 * SECONDS_PER_DAY), (b"2", 7 * SECONDS_PER_DAY)],
    )
    async def test_strikes_escalate_through_the_ladder(self, strike, expected_ex):
        pool = _pool()
        pool.get = AsyncMock(return_value=strike)
        assert await _register_notification(pool, "todo-1") is True

        last_call = pool.set.await_args_list[-1]
        assert last_call.args[0] == "gaia_maintenance_notified:todo-1"
        assert last_call.kwargs["ex"] == expected_ex

    async def test_exhausted_ladder_mutes_for_a_month(self):
        pool = _pool()
        pool.get = AsyncMock(return_value="3")
        assert await _register_notification(pool, "todo-1") is False

        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=NOTIFICATION_MUTE_DAYS * SECONDS_PER_DAY
        )


# ---------------------------------------------------------------------------
# _is_user_daytime — quiet-hours gate
# ---------------------------------------------------------------------------


class TestIsUserDaytime:
    async def test_utc_noon_is_daytime(self):
        with patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"timezone": "UTC"})):
            assert await _is_user_daytime("user-1", NOW, {}) is True

    async def test_utc_3am_is_night(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"timezone": "UTC"})):
            assert await _is_user_daytime("user-1", night, {}) is False

    async def test_local_timezone_wins(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"timezone": "Asia/Tokyo"})):
            assert await _is_user_daytime("user-1", night, {}) is True

    async def test_result_is_cached_per_sweep(self):
        lookup = AsyncMock(return_value={"timezone": "UTC"})
        cache: dict[str, bool] = {}
        with patch(f"{MODULE}.get_user_by_id", lookup):
            first = await _is_user_daytime("user-1", NOW, cache)
            second = await _is_user_daytime("user-1", NOW, cache)

        assert first == second
        lookup.assert_awaited_once_with("user-1")

    async def test_user_lookup_failure_does_not_raise(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(side_effect=Exception("mongo down"))),
            patch(f"{MODULE}.log.warning") as warning,
        ):
            result = await _is_user_daytime("user-1", night, {})
        assert result is False
        warning.assert_called_once_with(
            "maintenance_sweep.user_tz_lookup_failed", user_id="user-1", error="mongo down"
        )

    async def test_missing_timezone_resolves_against_none(self):
        daytime = MagicMock(return_value=True)
        with (
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={})),
            patch(f"{MODULE}.is_within_local_daytime", daytime),
        ):
            assert await _is_user_daytime("user-1", NOW, {}) is True
        daytime.assert_called_once_with(NOW, None, 9, 21)


# ---------------------------------------------------------------------------
# _todo_redirect_action / _send_user_dormant_digest
# ---------------------------------------------------------------------------


class TestTodoRedirectAction:
    def test_single_todo_deep_links(self):
        action = _todo_redirect_action("View todo", "todo-9")
        assert action.type == ActionType.REDIRECT
        assert action.style == ActionStyle.PRIMARY
        assert action.label == "View todo"
        assert action.config.redirect.url == "/todos?todoId=todo-9"
        assert action.config.redirect.open_in_new_tab is False
        assert action.config.redirect.close_notification is True

    def test_digest_lands_on_the_todos_list(self):
        action = _todo_redirect_action("Review todos", None)
        assert action.type == ActionType.REDIRECT
        assert action.style == ActionStyle.PRIMARY
        assert action.config.redirect.url == "/todos"
        assert action.config.redirect.open_in_new_tab is False
        assert action.config.redirect.close_notification is True


class TestSendUserDormantDigest:
    async def test_single_todo_digest(self):
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.log.info") as info,
        ):
            await _send_user_dormant_digest(
                "user-1", [_doc(title="Unfinished thing", updated_at=NOW - timedelta(days=7))], NOW
            )

        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.INFO
        assert "type" in request.model_fields_set
        assert request.priority == 2
        assert request.content.title == "1 dormant todo needs attention"
        assert request.content.body == "- Unfinished thing (idle 7d)"
        assert request.metadata == {"todo_count": 1}
        assert request.content.actions[0].label == "View todo"
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"
        info.assert_called_once_with(
            "maintenance_sweep.dormant_digest_sent", user_id="user-1", todo_count=1
        )

    async def test_multi_todo_digest_counts_and_links_to_the_list(self):
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.log.info") as info,
        ):
            await _send_user_dormant_digest(
                "user-1",
                [
                    _doc(id="a", title="One"),
                    _doc(id="b", title="Two", updated_at=NOW - timedelta(days=3)),
                ],
                NOW,
            )

        request = notify.await_args.args[0]
        assert request.type == NotificationType.INFO
        assert "type" in request.model_fields_set
        assert request.priority == 2
        assert request.content.title == "2 dormant todos need attention"
        assert request.content.body == "- One (idle 10d)\n- Two (idle 3d)"
        assert request.content.actions[0].label == "Review todos"
        assert request.content.actions[0].config.redirect.url == "/todos"
        info.assert_called_once_with(
            "maintenance_sweep.dormant_digest_sent", user_id="user-1", todo_count=2
        )

    async def test_notification_failure_is_swallowed(self):
        with (
            patch(
                f"{MODULE}.notification_service.create_notification",
                AsyncMock(side_effect=RuntimeError("notification bus down")),
            ),
            patch(f"{MODULE}.log.warning") as warning,
        ):
            await _send_user_dormant_digest("user-1", [_doc()], NOW)

        warning.assert_called_once_with(
            "maintenance_sweep.dormant_digest_failed", user_id="user-1", error="notification bus down"
        )


class TestSendIndividualNotification:
    async def test_sends_warning_with_view_todo_action(self):
        notify = AsyncMock()
        with patch(f"{MODULE}.notification_service.create_notification", notify):
            await _send_individual_notification(
                "user-1", "Expired: X", "Body text", "todo-1", NotificationType.WARNING
            )

        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.WARNING
        assert request.content.title == "Expired: X"
        assert request.content.body == "Body text"
        assert request.content.actions[0].label == "View todo"
        assert request.content.actions[0].style == ActionStyle.PRIMARY
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"
        assert request.metadata == {"todo_id": "todo-1"}

    async def test_failure_is_logged_not_raised(self):
        with (
            patch(
                f"{MODULE}.notification_service.create_notification",
                AsyncMock(side_effect=RuntimeError("notification bus down")),
            ),
            patch(f"{MODULE}.log.warning") as warning,
        ):
            await _send_individual_notification(
                "user-1", "Expired: X", "Body text", "todo-1", NotificationType.WARNING
            )

        warning.assert_called_once_with(
            "maintenance_sweep.notification_failed", todo_id="todo-1", error="notification bus down"
        )


# ---------------------------------------------------------------------------
# _process_expired / _process_overdue / _process_dormant — the per-tier loops
# ---------------------------------------------------------------------------


def _process_seams(**overrides) -> dict:
    """Mocks for the seams the per-tier loops call, overridable per test."""
    seams = {
        "daytime": AsyncMock(return_value=True),
        "health": AsyncMock(return_value="ARCHIVE: done"),
        "canvas": AsyncMock(return_value=""),
        "archive": AsyncMock(),
        "schedule": AsyncMock(),
        "system_log": AsyncMock(),
        "add_labels": AsyncMock(),
        "notify": AsyncMock(),
    }
    seams.update(overrides)
    return seams


class TestProcessExpired:
    async def test_counts_two_archived_todos_per_user(self):
        pool = _pool()
        seams = _process_seams()
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        todos = [_doc(id="a"), _doc(id="b")]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            archived, notified = await _process_expired(todos, pool, NOW, checks, cache)

        assert (archived, notified) == (2, 0)
        assert checks == {"user-1": 2}
        seams["daytime"].assert_has_awaits(
            [call("user-1", NOW, cache), call("user-1", NOW, cache)]
        )
        seams["health"].assert_awaited()
        assert seams["health"].await_count == 2
        seams["archive"].assert_awaited()
        assert seams["archive"].await_count == 2

    async def test_counts_two_notified_todos(self):
        pool = _pool()
        seams = _process_seams(health=AsyncMock(return_value="NOTIFY: needs a decision"))
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        todos = [_doc(id="a"), _doc(id="b")]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            archived, notified = await _process_expired(todos, pool, NOW, checks, cache)

        assert (archived, notified) == (0, 2)
        assert checks == {"user-1": 2}
        seams["notify"].assert_awaited()
        assert seams["notify"].await_count == 2

    async def test_nighttime_todo_is_deferred_but_later_todos_still_run(self):
        pool = _pool()
        seams = _process_seams(daytime=AsyncMock(side_effect=[False, True]))
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            archived, _notified = await _process_expired(
                [_doc(id="a"), _doc(id="b")], pool, NOW, checks, cache
            )

        assert archived == 1
        assert checks == {"user-1": 1}
        seams["daytime"].assert_has_awaits(
            [call("user-1", NOW, cache), call("user-1", NOW, cache)]
        )
        assert seams["health"].await_count == 1

    async def test_caps_health_checks_at_ten_per_user(self):
        pool = _pool()
        seams = _process_seams()
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        todos = [_doc(id=f"e{i}") for i in range(MAX_HEALTH_CHECKS_PER_USER + 1)]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            archived, _notified = await _process_expired(todos, pool, NOW, checks, cache)

        assert archived == MAX_HEALTH_CHECKS_PER_USER
        assert checks == {"user-1": MAX_HEALTH_CHECKS_PER_USER}
        assert seams["health"].await_count == MAX_HEALTH_CHECKS_PER_USER

    async def test_capped_user_does_not_block_a_fresh_user(self):
        pool = _pool()
        seams = _process_seams()
        checks: dict[str, int] = {"user-1": MAX_HEALTH_CHECKS_PER_USER}
        cache: dict[str, bool] = {}
        todos = [_doc(id="capped", user_id="user-1"), _doc(id="fresh", user_id="user-2")]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            archived, _notified = await _process_expired(todos, pool, NOW, checks, cache)

        assert archived == 1
        assert checks == {"user-1": MAX_HEALTH_CHECKS_PER_USER, "user-2": 1}
        assert seams["health"].await_count == 1

    async def test_fresh_user_is_below_a_cap_of_one(self):
        """Pin the cap check's default: a user with no recorded checks is below the cap.

        With the cap patched to 1, an absent user must still be processed (the
        ``get(uid, 0)`` default is 0 < 1). A default of 1 would wrongly cap them
        before their first health check.
        """
        pool = _pool()
        seams = _process_seams()
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._call_health_check_agent", seams["health"]),
            patch(f"{MODULE}._read_canvas", seams["canvas"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", seams["archive"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
            patch(f"{MODULE}.MAX_HEALTH_CHECKS_PER_USER", 1),
        ):
            archived, _notified = await _process_expired([_doc(id="fresh")], pool, NOW, checks, cache)

        assert archived == 1
        assert checks == {"user-1": 1}
        assert seams["health"].await_count == 1


class TestProcessOverdue:
    async def test_counts_two_notified_overdue_todos(self):
        pool = _pool()
        seams = _process_seams()
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}.todo_repository.add_labels", seams["add_labels"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            notified = await _process_overdue([_doc(id="a"), _doc(id="b")], pool, NOW, cache)

        assert notified == 2
        seams["daytime"].assert_has_awaits(
            [call("user-1", NOW, cache), call("user-1", NOW, cache)]
        )
        assert seams["notify"].await_count == 2
        assert seams["add_labels"].await_count == 2

    async def test_nighttime_todo_is_deferred_but_later_todos_still_run(self):
        pool = _pool()
        seams = _process_seams(daytime=AsyncMock(side_effect=[False, True]))
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}.todo_repository.add_labels", seams["add_labels"]),
            patch(f"{MODULE}.notification_service.create_notification", seams["notify"]),
        ):
            notified = await _process_overdue([_doc(id="a"), _doc(id="b")], pool, NOW, cache)

        assert notified == 1
        seams["daytime"].assert_has_awaits(
            [call("user-1", NOW, cache), call("user-1", NOW, cache)]
        )
        assert seams["notify"].await_count == 1


class TestProcessDormant:
    async def test_counts_requeued_and_collects_needs_attention(self):
        pool = _pool()
        seams = _process_seams(
            health=AsyncMock(
                side_effect=["requeued", "requeued", "needs_attention"]
            )
        )
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        todos = [_doc(id="d1"), _doc(id="d2"), _doc(id="d3")]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._health_check_dormant", seams["health"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", seams["schedule"]),
        ):
            requeued, needs_attention = await _process_dormant(
                todos, pool, NOW, checks, cache
            )

        assert requeued == 2
        assert [t.id for t in needs_attention] == ["d3"]
        assert checks == {"user-1": 3}
        seams["daytime"].assert_has_awaits([call("user-1", NOW, cache)] * 3)
        seams["health"].assert_has_awaits(
            [call(todos[0], pool), call(todos[1], pool), call(todos[2], pool)]
        )
        pool.set.assert_awaited_with("gaia_maintenance_notified:d3", "1", ex=SECONDS_PER_DAY)

    async def test_nighttime_todo_is_deferred_but_later_todos_still_run(self):
        pool = _pool()
        seams = _process_seams(
            daytime=AsyncMock(side_effect=[False, True]),
            health=AsyncMock(return_value="requeued"),
        )
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._health_check_dormant", seams["health"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", seams["schedule"]),
        ):
            requeued, needs_attention = await _process_dormant(
                [_doc(id="a"), _doc(id="b")], pool, NOW, checks, cache
            )

        assert requeued == 1
        assert needs_attention == []
        assert checks == {"user-1": 1}
        seams["daytime"].assert_has_awaits(
            [call("user-1", NOW, cache), call("user-1", NOW, cache)]
        )
        assert seams["health"].await_count == 1

    async def test_caps_health_checks_at_ten_per_user(self):
        pool = _pool()
        seams = _process_seams(health=AsyncMock(return_value="requeued"))
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        todos = [_doc(id=f"d{i}") for i in range(MAX_HEALTH_CHECKS_PER_USER + 1)]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._health_check_dormant", seams["health"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", seams["schedule"]),
        ):
            requeued, needs_attention = await _process_dormant(
                todos, pool, NOW, checks, cache
            )

        assert requeued == MAX_HEALTH_CHECKS_PER_USER
        assert [t.id for t in needs_attention] == [f"d{MAX_HEALTH_CHECKS_PER_USER}"]
        assert checks == {"user-1": MAX_HEALTH_CHECKS_PER_USER}
        assert seams["health"].await_count == MAX_HEALTH_CHECKS_PER_USER

    async def test_capped_user_does_not_block_a_fresh_user(self):
        pool = _pool()
        seams = _process_seams(health=AsyncMock(return_value="requeued"))
        checks: dict[str, int] = {"user-1": MAX_HEALTH_CHECKS_PER_USER}
        cache: dict[str, bool] = {}
        todos = [_doc(id="capped", user_id="user-1"), _doc(id="fresh", user_id="user-2")]
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._health_check_dormant", seams["health"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", seams["schedule"]),
        ):
            requeued, needs_attention = await _process_dormant(
                todos, pool, NOW, checks, cache
            )

        assert requeued == 1
        assert [t.id for t in needs_attention] == ["capped"]
        assert checks == {"user-1": MAX_HEALTH_CHECKS_PER_USER, "user-2": 1}
        assert seams["health"].await_count == 1

    async def test_fresh_user_is_below_a_cap_of_one(self):
        """Pin the cap check's default: a user with no recorded checks is below the cap.

        With the cap patched to 1, an absent user must still be re-queued (the
        ``get(uid, 0)`` default is 0 < 1). A default of 1 would wrongly shunt
        them to the needs-attention digest before their first health check.
        """
        pool = _pool()
        seams = _process_seams(health=AsyncMock(return_value="requeued"))
        checks: dict[str, int] = {}
        cache: dict[str, bool] = {}
        with (
            patch(f"{MODULE}._is_user_daytime", seams["daytime"]),
            patch(f"{MODULE}._health_check_dormant", seams["health"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", seams["schedule"]),
            patch(f"{MODULE}.MAX_HEALTH_CHECKS_PER_USER", 1),
        ):
            requeued, needs_attention = await _process_dormant(
                [_doc(id="fresh")], pool, NOW, checks, cache
            )

        assert requeued == 1
        assert needs_attention == []
        assert checks == {"user-1": 1}
        assert seams["health"].await_count == 1


# ---------------------------------------------------------------------------
# maintenance_sweep_tracked_todos — the cron end to end
# ---------------------------------------------------------------------------


class TestMaintenanceSweep:
    async def test_expired_todo_archived_by_the_health_check(self):
        with _sweep(
            list=[_doc(id="exp-1", expires_at=datetime.now(UTC) - timedelta(hours=1))],
            health="ARCHIVE: done",
        ) as (pool, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:1 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["archive"].assert_awaited_once()
        pool.set.assert_awaited()
        mocks["info"].assert_any_call("maintenance_sweep.scan_started")
        mocks["info"].assert_any_call(
            "maintenance_sweep.done",
            archived=1,
            notified_expired=0,
            notified_overdue=0,
            requeued=0,
            digest_items=0,
        )
        mocks["log_set"].assert_called_once_with(
            archived=1, notified_expired=0, notified_overdue=0, requeued=0, digest_items=0
        )

    async def test_dormant_todo_needing_attention_lands_in_the_digest(self):
        with _sweep(
            list=[_doc(id="dor-1", updated_at=datetime.now(UTC) - timedelta(days=10))],
            health="NEEDS_ATTENTION: waiting on the user",
        ) as (_pool, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:0 digest_items:1"
        )
        mocks["notify"].assert_awaited_once()
        request = mocks["notify"].await_args.args[0]
        assert request.content.title == "1 dormant todo needs attention"
        mocks["info"].assert_any_call("maintenance_sweep.scan_started")
        mocks["info"].assert_any_call(
            "maintenance_sweep.done",
            archived=0,
            notified_expired=0,
            notified_overdue=0,
            requeued=0,
            digest_items=1,
        )
        mocks["log_set"].assert_called_once_with(
            archived=0, notified_expired=0, notified_overdue=0, requeued=0, digest_items=1
        )

    async def test_todo_inside_its_cooldown_is_skipped_entirely(self):
        def _exists(key: str) -> int:
            return 1 if "quiet-1" in key else 0

        with _sweep(
            list=[_doc(id="quiet-1", expires_at=datetime.now(UTC) - timedelta(hours=1))]
        ) as (pool, mocks):
            pool.exists = AsyncMock(side_effect=_exists)
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["health"].assert_not_awaited()
        mocks["info"].assert_any_call("maintenance_sweep.scan_started")
        mocks["info"].assert_any_call(
            "maintenance_sweep.done",
            archived=0,
            notified_expired=0,
            notified_overdue=0,
            requeued=0,
            digest_items=0,
        )
        mocks["log_set"].assert_called_once_with(
            archived=0, notified_expired=0, notified_overdue=0, requeued=0, digest_items=0
        )

    async def test_summary_reflects_each_tier_count(self):
        """Pin the operator-visible summary format with the processing steps faked."""
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=_pool())),
            patch(f"{MODULE}._classify_tracked_todos", AsyncMock(return_value=([], [], []))),
            patch(f"{MODULE}._process_expired", AsyncMock(return_value=(3, 2))),
            patch(f"{MODULE}._process_overdue", AsyncMock(return_value=4)),
            patch(f"{MODULE}._process_dormant", AsyncMock(return_value=(1, [MagicMock()]))),
            patch(f"{MODULE}._send_dormant_digest", AsyncMock()) as digest,
            patch(f"{MODULE}.log.info") as info,
            patch(f"{MODULE}.log.set") as log_set,
        ):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:3 notified_expired:2 notified_overdue:4 requeued:1 digest_items:1"
        )
        digest.assert_awaited_once()
        info.assert_any_call("maintenance_sweep.scan_started")
        info.assert_any_call(
            "maintenance_sweep.done",
            archived=3,
            notified_expired=2,
            notified_overdue=4,
            requeued=1,
            digest_items=1,
        )
        log_set.assert_called_once_with(
            archived=3, notified_expired=2, notified_overdue=4, requeued=1, digest_items=1
        )

    async def test_end_to_end_with_real_daytime_gate_processes_every_tier(self):
        """Run the whole sweep with the real ``_is_user_daytime`` gate (seams only).

        One user per tier so the daytime cache cannot mask a ``now``/``cache``
        argument bug in any single tier's processing step.
        """
        pool = _pool()
        mocks = {
            "list": AsyncMock(
                return_value=[
                    _doc(
                        id="exp-1",
                        user_id="expired-user",
                        expires_at=datetime.now(UTC) - timedelta(hours=1),
                    ),
                    _doc(
                        id="due-1",
                        user_id="overdue-user",
                        due_date=datetime.now(UTC) - timedelta(days=1),
                    ),
                    _doc(
                        id="dor-1",
                        user_id="dormant-user",
                        updated_at=datetime.now(UTC) - timedelta(days=10),
                    ),
                ]
            ),
            "get_pool": AsyncMock(return_value=pool),
            "get_user": AsyncMock(return_value={"timezone": "UTC"}),
            "daytime": MagicMock(return_value=True),
            "canvas": AsyncMock(return_value=""),
            "health": AsyncMock(side_effect=["ARCHIVE: done", "EXECUTE: follow up"]),
            "archive": AsyncMock(),
            "schedule": AsyncMock(),
            "system_log": AsyncMock(),
            "add_labels": AsyncMock(),
            "notify": AsyncMock(),
        }
        with (
            patch(f"{MODULE}.todo_repository.list_active_tracked_all_users", mocks["list"]),
            patch(f"{MODULE}.RedisPoolManager.get_pool", mocks["get_pool"]),
            patch(f"{MODULE}.get_user_by_id", mocks["get_user"]),
            patch(f"{MODULE}.is_within_local_daytime", mocks["daytime"]),
            patch(f"{MODULE}._read_canvas", mocks["canvas"]),
            patch(f"{MODULE}._call_health_check_agent", mocks["health"]),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", mocks["archive"]),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", mocks["schedule"]),
            patch(f"{MODULE}.tracked_todo_service.system_log", mocks["system_log"]),
            patch(f"{MODULE}.todo_repository.add_labels", mocks["add_labels"]),
            patch(f"{MODULE}.notification_service.create_notification", mocks["notify"]),
        ):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:1 notified_expired:0 notified_overdue:1 requeued:1 digest_items:0"
        )
        mocks["archive"].assert_awaited_once()
        mocks["notify"].assert_awaited_once()
        mocks["schedule"].assert_awaited_once()
        mocks["get_user"].assert_has_awaits(
            [call("expired-user"), call("overdue-user"), call("dormant-user")]
        )
        assert len(mocks["daytime"].call_args_list) == 3
        assert all(c.args[0] is not None for c in mocks["daytime"].call_args_list)
        assert all(c.args[1:] == ("UTC", 9, 21) for c in mocks["daytime"].call_args_list)
