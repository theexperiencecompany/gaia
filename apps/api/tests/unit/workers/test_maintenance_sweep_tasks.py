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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.agent import AgentRunOptions
from app.models.agent_models import SilentRunResult
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.workers.tasks.maintenance_sweep_tasks import (
    DORMANT_DAYS,
    NOTIFICATION_BACKOFF_DAYS,
    NOTIFICATION_MUTE_DAYS,
    SECONDS_PER_DAY,
    STRIKE_TTL_DAYS,
    WAITING_LABEL_MAX_DAYS,
    _call_health_check_agent,
    _classify_tracked_todos,
    _has_upcoming_schedule,
    _health_check_dormant,
    _health_check_expired,
    _is_dormant,
    _is_user_daytime,
    _notify_overdue,
    _register_notification,
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

    def test_blocking_label_at_exactly_max_days_is_not_yet_stuck(self):
        """ "Surface" means strictly past the cap — day 8 of an 8-day cap is the
        last quiet day, not the first escalated one."""
        doc = _doc(
            updated_at=NOW - timedelta(days=WAITING_LABEL_MAX_DAYS), labels=["waiting-for-approval"]
        )
        assert _is_dormant(doc, NOW) is False

    def test_missing_updated_at_is_never_dormant(self):
        assert _is_dormant(_doc(updated_at=None), NOW) is False


# ---------------------------------------------------------------------------
# _classify_tracked_todos — tier bucketing
# ---------------------------------------------------------------------------


class TestClassifyTrackedTodos:
    async def _classify(self, pool: MagicMock, todos: list[TodoDocument]):
        with patch(
            f"{MODULE}.todo_repository.list_active_tracked_all_users",
            AsyncMock(return_value=todos),
        ):
            return await _classify_tracked_todos(pool, NOW)

    async def test_buckets_expired_overdue_and_dormant(self):
        pool = _pool()
        todos = [
            _doc(id="exp", expires_at=NOW - timedelta(hours=1), updated_at=NOW),
            _doc(id="due", due_date=NOW - timedelta(days=1), updated_at=NOW),
            _doc(id="dor", updated_at=NOW - timedelta(days=10)),
            _doc(id="fine", updated_at=NOW),
        ]
        expired, overdue, dormant = await self._classify(pool, todos)

        assert [t.id for t in expired] == ["exp"]
        assert [t.id for t in overdue] == ["due"]
        assert [t.id for t in dormant] == ["dor"]

    async def test_todo_in_cooldown_is_skipped(self):
        pool = _pool()
        pool.exists = AsyncMock(side_effect=lambda key: 1 if "todo-1" in key else 0)
        todos = [
            _doc(id="todo-1", expires_at=NOW - timedelta(hours=1)),
            _doc(id="todo-2", expires_at=NOW - timedelta(hours=1)),
        ]
        expired, _overdue, _dormant = await self._classify(pool, todos)

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
        _expired, overdue, _dormant = await self._classify(pool, todos)
        assert overdue == []

    async def test_each_tier_is_capped_at_20(self):
        pool = _pool()
        todos = [_doc(id=f"exp-{i}", expires_at=NOW - timedelta(hours=1)) for i in range(25)] + [
            _doc(id=f"dor-{i}", updated_at=NOW - timedelta(days=10)) for i in range(25)
        ]
        expired, _overdue, dormant = await self._classify(pool, todos)

        assert len(expired) == 20
        assert len(dormant) == 20

    async def test_empty_scan_returns_empty_tiers(self):
        pool = _pool()
        expired, overdue, dormant = await self._classify(pool, [])
        assert (expired, overdue, dormant) == ([], [], [])


# ---------------------------------------------------------------------------
# _health_check_expired — archive / notify / mute
# ---------------------------------------------------------------------------


class TestHealthCheckExpired:
    async def test_archive_decision_archives_and_cooldowns(self):
        pool = _pool()
        archive = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="canvas text")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="ARCHIVE: everything resolved itself"),
            ),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", archive),
        ):
            outcome = await _health_check_expired(_doc(), pool)

        assert outcome == "archived"
        archive.assert_awaited_once_with("todo-1", "user-1", "everything resolved itself")
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY
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
        ):
            outcome = await _health_check_expired(_doc(title="Ship the report"), pool)

        assert outcome == "notified"
        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.WARNING
        assert request.content.title == "Expired: Ship the report"
        assert request.content.body == "Your todo expired and needs a decision."
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"
        assert request.metadata == {"todo_id": "todo-1"}

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
        ):
            outcome = await _health_check_expired(_doc(), pool)

        assert outcome == "muted"
        notify.assert_not_awaited()

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
    async def test_execute_decision_re_queues_with_jitter(self):
        pool = _pool()
        schedule = AsyncMock()
        syslog = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._call_health_check_agent",
                AsyncMock(return_value="EXECUTE: send the follow-up email"),
            ),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", schedule),
            patch(f"{MODULE}.tracked_todo_service.system_log", syslog),
        ):
            before = datetime.now(UTC)
            outcome = await _health_check_dormant(_doc(), pool)
            after = datetime.now(UTC)

        assert outcome == "requeued"
        run_at = schedule.await_args.args[1]
        assert before <= run_at <= after + timedelta(seconds=120)
        assert schedule.await_args.args[0] == "todo-1"
        syslog.assert_awaited_once()
        assert syslog.await_args.args[2] == "maintenance_requeued"
        assert "send the follow-up email" in syslog.await_args.args[3]
        pool.set.assert_awaited_once_with(
            "gaia_maintenance_notified:todo-1", "1", ex=SECONDS_PER_DAY
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
        ):
            outcome = await _health_check_dormant(_doc(), pool)

        assert outcome == "needs_attention"
        schedule.assert_not_awaited()
        pool.set.assert_not_awaited()

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
        assert "2 days ago" in request.content.body
        add_labels.assert_awaited_once_with("todo-1", user_id="user-1", labels=["needs-follow-up"])

    async def test_muted_overdue_sends_nothing(self):
        pool = _pool()
        pool.get = AsyncMock(return_value="4")
        notify = AsyncMock()
        with (
            patch(f"{MODULE}.notification_service.create_notification", notify),
            patch(f"{MODULE}.todo_repository.add_labels", AsyncMock()),
        ):
            result = await _notify_overdue(_doc(), pool)

        assert result is False
        notify.assert_not_awaited()


# ---------------------------------------------------------------------------
# _register_notification — the escalating backoff
# ---------------------------------------------------------------------------


class TestRegisterNotification:
    async def test_first_strike_sets_a_one_day_cooldown(self):
        pool = _pool()
        assert await _register_notification(pool, "todo-1") is True

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
        lookup.assert_awaited_once()

    async def test_user_lookup_failure_does_not_raise(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with patch(f"{MODULE}.get_user_by_id", AsyncMock(side_effect=Exception("mongo down"))):
            result = await _is_user_daytime("user-1", night, {})
        assert result is False


# ---------------------------------------------------------------------------
# _todo_redirect_action / _send_user_dormant_digest
# ---------------------------------------------------------------------------


class TestTodoRedirectAction:
    def test_single_todo_deep_links(self):
        action = _todo_redirect_action("View todo", "todo-9")
        assert action.label == "View todo"
        assert action.config.redirect.url == "/todos?todoId=todo-9"
        assert action.config.redirect.close_notification is True

    def test_digest_lands_on_the_todos_list(self):
        action = _todo_redirect_action("Review todos", None)
        assert action.config.redirect.url == "/todos"


class TestSendUserDormantDigest:
    async def test_single_todo_digest(self):
        notify = AsyncMock()
        with patch(f"{MODULE}.notification_service.create_notification", notify):
            await _send_user_dormant_digest(
                "user-1", [_doc(title="Unfinished thing", updated_at=NOW - timedelta(days=7))], NOW
            )

        request = notify.await_args.args[0]
        assert request.user_id == "user-1"
        assert request.source == NotificationSourceEnum.BACKGROUND_JOB
        assert request.type == NotificationType.INFO
        assert request.content.title == "1 dormant todo needs attention"
        assert request.content.body == "- Unfinished thing (idle 7d)"
        assert request.metadata == {"todo_count": 1}
        assert request.content.actions[0].config.redirect.url == "/todos?todoId=todo-1"

    async def test_multi_todo_digest_counts_and_links_to_the_list(self):
        notify = AsyncMock()
        with patch(f"{MODULE}.notification_service.create_notification", notify):
            await _send_user_dormant_digest(
                "user-1",
                [
                    _doc(id="a", title="One"),
                    _doc(id="b", title="Two", updated_at=NOW - timedelta(days=3)),
                ],
                NOW,
            )

        request = notify.await_args.args[0]
        assert request.content.title == "2 dormant todos need attention"
        assert request.content.body == "- One (idle 10d)\n- Two (idle 3d)"
        assert request.content.actions[0].label == "Review todos"
        assert request.content.actions[0].config.redirect.url == "/todos"

    async def test_notification_failure_is_swallowed(self):
        with patch(
            f"{MODULE}.notification_service.create_notification",
            AsyncMock(side_effect=RuntimeError("notification bus down")),
        ):
            await _send_user_dormant_digest("user-1", [_doc()], NOW)


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

    async def test_summary_reflects_each_tier_count(self):
        """Pin the operator-visible summary format with the processing steps faked."""
        with (
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=_pool())),
            patch(f"{MODULE}._classify_tracked_todos", AsyncMock(return_value=([], [], []))),
            patch(f"{MODULE}._process_expired", AsyncMock(return_value=(3, 2))),
            patch(f"{MODULE}._process_overdue", AsyncMock(return_value=4)),
            patch(f"{MODULE}._process_dormant", AsyncMock(return_value=(1, [MagicMock()]))),
            patch(f"{MODULE}._send_dormant_digest", AsyncMock()) as digest,
        ):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:3 notified_expired:2 notified_overdue:4 requeued:1 digest_items:1"
        )
        digest.assert_awaited_once()


@pytest.mark.unit
class TestHealthCheckAgentCall:
    async def test_a_queued_dispatch_is_not_a_health_check_result(self) -> None:
        # The executor was busy, so the request was queued and answered with an
        # acknowledgement; returning that text as the check's verdict marked a
        # todo healthy on the strength of work that had not happened.
        agent = AsyncMock(
            return_value=SilentRunResult(
                message="That task is queued behind the one already running.",
                tool_data={},
                queued_task_id="task-9",
            )
        )
        with (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"name": "User"})),
        ):
            result = await _call_health_check_agent("todo-1", "user-1", "is this todo alive?")

        assert result.startswith("NEEDS_ATTENTION")
        assert "queued" in result
        assert "already running" not in result

    async def test_the_run_is_tagged_as_a_maintenance_health_check(self) -> None:
        # The trigger context is the only thing that tells the agent stack this
        # turn is a background health check rather than a chat message, and it
        # carries the todo the verdict belongs to. A dropped ``options=``, a
        # renamed key or a renamed trigger type all make the run anonymous, and
        # nothing downstream complains — it just stops being attributable.
        captured: dict[str, object] = {}

        async def fake_call_agent_silent(
            request: MessageRequestWithHistory,
            conversation_id: str,
            user: AuthenticatedUser,
            options: AgentRunOptions | None = None,
        ) -> SilentRunResult:
            captured["request"] = request
            captured["conversation_id"] = conversation_id
            captured["user"] = user
            captured["options"] = options
            return SilentRunResult(message="  Still on track  ", tool_data={})

        with (
            patch(f"{MODULE}.call_agent_silent", fake_call_agent_silent),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"name": "User"})),
        ):
            result = await _call_health_check_agent("todo-7", "user-3", "is this todo alive?")

        # A non-empty verdict is returned stripped, not blanked.
        assert result == "Still on track"

        options = captured["options"]
        assert isinstance(options, AgentRunOptions)
        assert options.trigger_context == {
            "trigger_type": "maintenance_health_check",
            "todo_id": "todo-7",
        }

    async def test_a_queued_dispatch_is_logged_with_the_todo_and_task_ids(self) -> None:
        # The queued verdict is deliberately vague ("not run"), so the log line is
        # the only place the operator learns WHICH todo was skipped and WHICH
        # in-flight task blocked it. Losing either id makes the warning unactionable.
        agent = AsyncMock(
            return_value=SilentRunResult(
                message="That task is queued behind the one already running.",
                tool_data={},
                queued_task_id="task-9",
            )
        )
        with (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"name": "User"})),
            patch(f"{MODULE}.log") as log,
        ):
            result = await _call_health_check_agent("todo-1", "user-1", "is this todo alive?")

        assert result == "NEEDS_ATTENTION: Health check queued behind an in-flight run; not run"
        log.warning.assert_called_once_with(
            "maintenance_sweep.health_check_queued",
            todo_id="todo-1",
            queued_task_id="task-9",
        )

    async def test_an_empty_agent_message_is_an_empty_verdict(self) -> None:
        # The sweep classifies the verdict by reading its text; substituting any
        # placeholder for a missing message would make an empty answer look like
        # a real one to every caller downstream.
        agent = AsyncMock(return_value=SilentRunResult(message="", tool_data={}))
        with (
            patch(f"{MODULE}.call_agent_silent", agent),
            patch(f"{MODULE}.get_user_by_id", AsyncMock(return_value={"name": "User"})),
        ):
            result = await _call_health_check_agent("todo-1", "user-1", "is this todo alive?")

        assert result == ""
