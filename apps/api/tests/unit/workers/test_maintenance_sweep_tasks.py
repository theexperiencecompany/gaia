"""Unit tests for app.workers.tasks.maintenance_sweep_tasks.

The cron that keeps tracked todos honest: expired todos get a health-check
agent pass (archive/file a notice), overdue todos get a notice, dormant todos
get re-queued or bundled into a digest notice. What the sweep filed today
(read from the outbox ledger) is what keeps a todo from being checked again,
and the daytime gate must keep it out of the user's night.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
import re
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.llm.client import metered_config
from app.constants.chat import MAX_MESSAGE_LENGTH
from app.constants.todos import CANVAS_PROMPT_MAX_CHARS, TodoActivityEvent
from app.models.todo_models import TodoDocument
from app.models.user_models import UserDocument
from app.services.outbox.models import NoticeOutcome, ProducerKind, SubjectKind
from app.workers.tasks.maintenance_sweep_tasks import (
    DORMANT_DAYS,
    KIND_DORMANT_DIGEST,
    KIND_EXPIRED,
    KIND_OVERDUE,
    WAITING_LABEL_MAX_DAYS,
    _classify_tracked_todos,
    _has_upcoming_schedule,
    _health_check_dormant,
    _health_check_expired,
    _health_check_verdict,
    _is_dormant,
    _is_user_daytime,
    _normalize_all_canvases,
    _notify_overdue,
    _send_user_dormant_digest,
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


def _sweep_patches(**overrides) -> tuple[MagicMock, dict[str, AsyncMock], list]:
    """Build the patches an end-to-end sweep needs, with overridable return values.

    Returns (filed, mocks, patches): filed is the ledger read that says what the sweep already
    filed today (None: nothing), and mocks keys name each seam.
    """
    defaults = {
        "list": [_doc()],
        "migration": [],
        "daytime": True,
        "canvas": "",
        "health": "NEEDS_ATTENTION: nothing to do",
    }
    defaults.update(overrides)
    mocks: dict[str, AsyncMock] = {
        "list": AsyncMock(return_value=defaults["list"]),
        "migration_finder": AsyncMock(return_value=defaults["migration"]),
        "filed": AsyncMock(return_value=None),
        "daytime": AsyncMock(return_value=defaults["daytime"]),
        "canvas": AsyncMock(return_value=defaults["canvas"]),
        "health": AsyncMock(return_value=defaults["health"]),
        "archive": AsyncMock(),
        "schedule": AsyncMock(),
        "store_schedule": AsyncMock(),
        "activity": AsyncMock(),
        "add_labels": AsyncMock(),
        "notify": AsyncMock(),
        "migrate": AsyncMock(return_value=False),
    }
    patches = [
        patch(f"{MODULE}.todo_repository.list_active_tracked_all_users", mocks["list"]),
        patch(
            f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
            mocks["migration_finder"],
            create=True,
        ),
        patch(f"{MODULE}.outbox_items_repository.get_by_report", mocks["filed"]),
        patch(f"{MODULE}._is_user_daytime", mocks["daytime"]),
        patch(f"{MODULE}._read_canvas", mocks["canvas"]),
        patch(f"{MODULE}._health_check_verdict", mocks["health"]),
        patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", mocks["archive"]),
        patch(f"{MODULE}.tracked_todo_service.schedule_execution", mocks["schedule"]),
        patch(f"{MODULE}.todo_repository.update", mocks["store_schedule"]),
        patch(f"{MODULE}.record_activity", mocks["activity"]),
        patch(f"{MODULE}.todo_repository.add_labels", mocks["add_labels"]),
        patch(f"{MODULE}.submit", mocks["notify"]),
        patch(f"{MODULE}.tracked_todo_service.normalize_stored_canvas", mocks["migrate"]),
    ]
    return mocks["filed"], mocks, patches


@contextmanager
def _sweep(**overrides) -> Iterator[tuple[MagicMock, dict[str, AsyncMock]]]:
    """Run an end-to-end sweep with every seam mocked; yields (filed, mocks)."""
    filed, mocks, patches = _sweep_patches(**overrides)
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield filed, mocks


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
        """Day 8 of an 8-day cap is the last quiet day, not the first escalated one."""
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
    async def _classify(self, todos: list[TodoDocument], *, filed: set[str] | None = None):
        """Classify todos; filed names the report ids the ledger already holds."""
        held = filed or set()

        async def get_by_report(_user_id: str, report_id: str) -> object | None:
            return object() if report_id in held else None

        with patch(f"{MODULE}.outbox_items_repository.get_by_report", get_by_report):
            return await _classify_tracked_todos(NOW, todos)

    async def test_buckets_expired_overdue_and_dormant(self):
        todos = [
            _doc(id="exp", expires_at=NOW - timedelta(hours=1), updated_at=NOW),
            _doc(id="due", due_date=NOW - timedelta(days=1), updated_at=NOW),
            _doc(id="dor", updated_at=NOW - timedelta(days=10)),
            _doc(id="fine", updated_at=NOW),
        ]
        expired, overdue, dormant = await self._classify(todos)

        assert [t.id for t in expired] == ["exp"]
        assert [t.id for t in overdue] == ["due"]
        assert [t.id for t in dormant] == ["dor"]

    async def test_a_todo_the_sweep_already_filed_today_is_skipped(self):
        todos = [
            _doc(id="todo-1", expires_at=NOW - timedelta(hours=1)),
            _doc(id="todo-2", expires_at=NOW - timedelta(hours=1)),
        ]
        expired, _overdue, _dormant = await self._classify(
            todos, filed={"sys:todo_expired:todo-1:2026-01-15"}
        )

        assert [t.id for t in expired] == ["todo-2"]

    async def test_an_overdue_todo_filed_today_is_skipped(self):
        todos = [_doc(id="due", due_date=NOW - timedelta(days=1), updated_at=NOW)]

        _expired, overdue, _dormant = await self._classify(
            todos, filed={"sys:todo_overdue:due:2026-01-15"}
        )

        assert overdue == []

    async def test_a_users_dormant_todos_are_skipped_once_todays_digest_is_filed(self):
        todos = [_doc(id="dor", updated_at=NOW - timedelta(days=10))]

        _expired, _overdue, dormant = await self._classify(
            todos, filed={"sys:todo_dormant_digest:user-1:2026-01-15"}
        )

        assert dormant == []

    async def test_yesterdays_notice_does_not_skip_todays_check(self):
        todos = [_doc(id="exp", expires_at=NOW - timedelta(hours=1))]

        expired, _overdue, _dormant = await self._classify(
            todos, filed={"sys:todo_expired:exp:2026-01-14"}
        )

        assert [t.id for t in expired] == ["exp"]

    async def test_due_todo_with_upcoming_schedule_is_not_overdue(self):
        todos = [
            _doc(
                id="sched",
                due_date=NOW - timedelta(days=1),
                scheduled_at=NOW + timedelta(hours=1),
            )
        ]
        _expired, overdue, _dormant = await self._classify(todos)
        assert overdue == []

    async def test_each_tier_is_capped_at_20(self):
        todos = [_doc(id=f"exp-{i}", expires_at=NOW - timedelta(hours=1)) for i in range(25)] + [
            _doc(id=f"dor-{i}", updated_at=NOW - timedelta(days=10)) for i in range(25)
        ]
        expired, _overdue, dormant = await self._classify(todos)

        assert len(expired) == 20
        assert len(dormant) == 20

    async def test_empty_scan_returns_empty_tiers(self):
        expired, overdue, dormant = await self._classify([])
        assert (expired, overdue, dormant) == ([], [], [])


# ---------------------------------------------------------------------------
# _health_check_expired — archive / notify / mute
# ---------------------------------------------------------------------------


class TestHealthCheckExpired:
    async def test_archive_decision_archives_the_todo(self):
        archive = AsyncMock()
        notify = AsyncMock()
        verdict = AsyncMock(return_value="ARCHIVE: everything resolved itself")
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="canvas text")),
            patch(f"{MODULE}._health_check_verdict", verdict),
            patch(f"{MODULE}.tracked_todo_service.archive_tracked_todo", archive),
            patch(f"{MODULE}.submit", notify),
        ):
            outcome = await _health_check_expired(_doc(), NOW)

        assert outcome == "archived"
        # The model call is metered to the todo's owner.
        assert verdict.await_args.args[0] == "user-1"
        archive.assert_awaited_once_with("todo-1", "user-1", "everything resolved itself")
        notify.assert_not_awaited()

    async def test_notify_decision_files_a_notice_named_by_the_day(self):
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._health_check_verdict",
                AsyncMock(return_value="NOTIFY: Your todo expired and needs a decision."),
            ),
            patch(f"{MODULE}.submit", notify),
            patch(f"{MODULE}.record_activity", AsyncMock()) as activity,
        ):
            outcome = await _health_check_expired(_doc(title="Ship the report"), NOW)

        assert outcome == "notified"
        activity.assert_awaited_once_with(
            "todo-1", "user-1", TodoActivityEvent.MAINTENANCE, "reported this todo as expired"
        )
        notice = notify.await_args.args[0]
        assert notice.recipient == "user-1"
        assert notice.producer is ProducerKind.TODO
        assert notice.subject.kind is SubjectKind.TODO_RUN
        assert notice.subject.label == "Ship the report"
        assert notice.outcome is NoticeOutcome.INFO
        assert notice.report_id == f"sys:{KIND_EXPIRED}:todo-1:2026-01-15"
        assert notice.facts == ["Your todo expired and needs a decision."]

    async def test_the_same_day_files_the_same_report_id(self):
        """A second sweep the same day names the same fact, so the outbox takes it once."""
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(f"{MODULE}._health_check_verdict", AsyncMock(return_value="NOTIFY: still open")),
            patch(f"{MODULE}.submit", notify),
            patch(f"{MODULE}.record_activity", AsyncMock()),
        ):
            await _health_check_expired(_doc(), NOW)
            await _health_check_expired(_doc(), NOW + timedelta(hours=2))

        first, second = (c.args[0].report_id for c in notify.await_args_list)
        assert first == second

    async def test_agent_failure_files_nothing(self):
        notify = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._health_check_verdict",
                AsyncMock(side_effect=ValueError("No human message or selected tool")),
            ),
            patch(f"{MODULE}.submit", notify),
            pytest.raises(ValueError, match="No human message"),
        ):
            await _health_check_expired(_doc(), NOW)

        notify.assert_not_awaited()


# ---------------------------------------------------------------------------
# _health_check_dormant — requeue / needs attention
# ---------------------------------------------------------------------------


class TestHealthCheckDormant:
    async def test_execute_decision_re_queues_with_jitter(self):
        schedule = AsyncMock()
        store = AsyncMock()
        syslog = AsyncMock()
        verdict = AsyncMock(return_value="EXECUTE: send the follow-up email")
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(f"{MODULE}._health_check_verdict", verdict),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", schedule),
            patch(f"{MODULE}.todo_repository.update", store) as store,
            patch(f"{MODULE}.record_activity", syslog),
        ):
            before = datetime.now(UTC)
            outcome = await _health_check_dormant(_doc())
            after = datetime.now(UTC)

        assert outcome == "requeued"
        # The model call is metered to the todo's owner.
        assert verdict.await_args.args[0] == "user-1"
        run_at = schedule.await_args.args[1]
        assert before <= run_at <= after + timedelta(seconds=120)
        assert schedule.await_args.args[0] == "todo-1"
        # Stored on the todo too: a run drops a fire its scheduled_at doesn't
        # name, and only a stored time lets the safety net recover a lost job.
        assert store.await_args.args == ("todo-1",)
        assert store.await_args.kwargs["user_id"] == "user-1"
        assert store.await_args.kwargs["update"].model_dump(exclude_unset=True) == {
            "scheduled_at": run_at
        }
        syslog.assert_awaited_once()
        todo_id, user_id, event, detail = syslog.await_args.args
        assert (todo_id, user_id, event) == ("todo-1", "user-1", TodoActivityEvent.MAINTENANCE)
        assert detail.startswith("re-queued after ")
        assert detail.endswith(" idle days to: send the follow-up email")

    async def test_needs_attention_does_not_touch_the_schedule(self):
        schedule = AsyncMock()
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._health_check_verdict",
                AsyncMock(return_value="NEEDS_ATTENTION: blocked on client sign-off"),
            ),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", schedule),
        ):
            outcome = await _health_check_dormant(_doc())

        assert outcome == "needs_attention"
        schedule.assert_not_awaited()

    async def test_agent_failure_is_not_a_needs_attention_verdict(self):
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._health_check_verdict",
                AsyncMock(side_effect=ValueError("No human message or selected tool")),
            ),
            pytest.raises(ValueError, match="No human message"),
        ):
            await _health_check_dormant(_doc())


# ---------------------------------------------------------------------------
# _notify_overdue
# ---------------------------------------------------------------------------


class TestNotifyOverdue:
    async def test_files_a_notice_and_labels_needs_follow_up(self):
        notify = AsyncMock()
        add_labels = AsyncMock()
        with (
            patch(f"{MODULE}.submit", notify),
            patch(f"{MODULE}.todo_repository.add_labels", add_labels),
            patch(f"{MODULE}.record_activity", AsyncMock()) as activity,
        ):
            await _notify_overdue(
                _doc(title="Pay the invoice", due_date=NOW - timedelta(days=2)), NOW
            )

        notice = notify.await_args.args[0]
        assert notice.subject.label == "Pay the invoice"
        assert notice.report_id == f"sys:{KIND_OVERDUE}:todo-1:2026-01-15"
        assert notice.facts == [
            "'Pay the invoice' was due 2 days ago and has no scheduled follow-up."
        ]
        add_labels.assert_awaited_once_with("todo-1", user_id="user-1", labels=["needs-follow-up"])
        activity.assert_awaited_once_with(
            "todo-1",
            "user-1",
            TodoActivityEvent.MAINTENANCE,
            "reported it 2 day(s) overdue with nothing scheduled",
        )

    async def test_a_notice_that_cannot_be_filed_leaves_the_todo_unlabelled(self):
        add_labels = AsyncMock()
        with (
            patch(f"{MODULE}.submit", AsyncMock(side_effect=RuntimeError("redis down"))),
            patch(f"{MODULE}.todo_repository.add_labels", add_labels),
            pytest.raises(RuntimeError, match="redis down"),
        ):
            await _notify_overdue(_doc(due_date=NOW - timedelta(days=2)), NOW)

        add_labels.assert_not_awaited()


# ---------------------------------------------------------------------------
# _is_user_daytime — quiet-hours gate
# ---------------------------------------------------------------------------


class TestIsUserDaytime:
    async def test_utc_noon_is_daytime(self):
        with patch(
            f"{MODULE}.get_user_by_id", AsyncMock(return_value=UserDocument(timezone="UTC"))
        ):
            assert await _is_user_daytime("user-1", NOW, {}) is True

    async def test_utc_3am_is_night(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with patch(
            f"{MODULE}.get_user_by_id", AsyncMock(return_value=UserDocument(timezone="UTC"))
        ):
            assert await _is_user_daytime("user-1", night, {}) is False

    async def test_local_timezone_wins(self):
        night = datetime(2026, 1, 15, 3, 0, tzinfo=UTC)
        with patch(
            f"{MODULE}.get_user_by_id", AsyncMock(return_value=UserDocument(timezone="Asia/Tokyo"))
        ):
            assert await _is_user_daytime("user-1", night, {}) is True

    async def test_result_is_cached_per_sweep(self):
        lookup = AsyncMock(return_value=UserDocument(timezone="UTC"))
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
# _send_user_dormant_digest
# ---------------------------------------------------------------------------


class TestSendUserDormantDigest:
    async def test_single_todo_digest(self):
        notify = AsyncMock()
        with patch(f"{MODULE}.submit", notify):
            await _send_user_dormant_digest(
                "user-1", [_doc(title="Unfinished thing", updated_at=NOW - timedelta(days=7))], NOW
            )

        notice = notify.await_args.args[0]
        assert notice.recipient == "user-1"
        assert notice.producer is ProducerKind.TODO
        assert notice.outcome is NoticeOutcome.INFO
        assert notice.report_id == f"sys:{KIND_DORMANT_DIGEST}:user-1:2026-01-15"
        assert notice.facts == ["'Unfinished thing' has been idle for 7 days."]

    async def test_a_digest_names_every_dormant_todo(self):
        notify = AsyncMock()
        with patch(f"{MODULE}.submit", notify):
            await _send_user_dormant_digest(
                "user-1",
                [
                    _doc(id="a", title="One"),
                    _doc(id="b", title="Two", updated_at=NOW - timedelta(days=3)),
                ],
                NOW,
            )

        assert notify.await_args.args[0].facts == [
            "'One' has been idle for 10 days.",
            "'Two' has been idle for 3 days.",
        ]

    async def test_a_notice_that_cannot_be_filed_is_swallowed(self):
        with patch(f"{MODULE}.submit", AsyncMock(side_effect=RuntimeError("redis down"))):
            await _send_user_dormant_digest("user-1", [_doc()], NOW)


# ---------------------------------------------------------------------------
# maintenance_sweep_tracked_todos — the cron end to end
# ---------------------------------------------------------------------------


class TestMigrateAllLegacyCanvases:
    """The cursor loop's own contract: it pages to a short page, sums every page's migrated count, and stops on the empty page."""

    async def test_empty_scan_returns_zero(self):
        with (
            patch(
                f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
                AsyncMock(return_value=[]),
                create=True,
            ),
            patch(f"{MODULE}._normalize_stored_canvases", AsyncMock(return_value=0)) as migrate,
        ):
            assert await _normalize_all_canvases() == 0

        migrate.assert_not_awaited()

    async def test_sums_every_page_to_a_short_page(self):
        from app.workers.tasks.maintenance_sweep_tasks import _MIGRATION_PAGE_SIZE

        full = [_doc(id=f"a{i}", updated_at=NOW) for i in range(_MIGRATION_PAGE_SIZE)]
        short = [_doc(id="last", updated_at=NOW)]
        finder = AsyncMock(side_effect=[full, short])
        with (
            patch(
                f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
                finder,
                create=True,
            ),
            patch(f"{MODULE}._normalize_stored_canvases", AsyncMock(return_value=2)) as migrate,
        ):
            assert await _normalize_all_canvases() == 4

        assert migrate.await_count == 2
        assert [c.args[0][0].id for c in migrate.await_args_list] == ["a0", "last"]

    async def test_short_first_page_stops_immediately(self):
        """A first page shorter than the size is the whole scan — the loop must stop without a second fetch."""
        finder = AsyncMock(side_effect=[[_doc(id="only", updated_at=NOW)]])
        with (
            patch(
                f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
                finder,
                create=True,
            ),
            patch(f"{MODULE}._normalize_stored_canvases", AsyncMock(return_value=1)),
        ):
            assert await _normalize_all_canvases() == 1

        finder.assert_awaited_once()


class TestMigrateLegacyCanvases:
    """The per-page loop's count: each migrated todo adds one, nothing else."""

    async def test_counts_each_migrated_todo(self):
        from app.workers.tasks.maintenance_sweep_tasks import _normalize_stored_canvases

        todos = [_doc(id="a", updated_at=NOW), _doc(id="b", updated_at=NOW)]
        with patch(
            f"{MODULE}.tracked_todo_service.normalize_stored_canvas",
            AsyncMock(side_effect=[True, True]),
        ) as migrate:
            assert await _normalize_stored_canvases(todos) == 2

        assert migrate.await_count == 2

    async def test_zero_when_nothing_migrates(self):
        from app.workers.tasks.maintenance_sweep_tasks import _normalize_stored_canvases

        with patch(
            f"{MODULE}.tracked_todo_service.normalize_stored_canvas",
            AsyncMock(return_value=False),
        ):
            assert await _normalize_stored_canvases([_doc(id="a", updated_at=NOW)]) == 0

    async def test_a_failing_todo_is_logged_and_skipped(self):
        """One todo raising must not abort the batch, and the failure is logged with the todo id and the error."""
        from app.workers.tasks.maintenance_sweep_tasks import _normalize_stored_canvases

        with (
            patch(
                f"{MODULE}.tracked_todo_service.normalize_stored_canvas",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch(f"{MODULE}.log") as mock_log,
        ):
            assert await _normalize_stored_canvases([_doc(id="a", updated_at=NOW)]) == 0

        mock_log.warning.assert_called_once_with(
            "maintenance_sweep.canvas_normalization_failed",
            todo_id="a",
            error_type="RuntimeError",
            error="boom",
        )

    async def test_a_failing_todo_does_not_stop_later_todos(self):
        from app.workers.tasks.maintenance_sweep_tasks import _normalize_stored_canvases

        with patch(
            f"{MODULE}.tracked_todo_service.normalize_stored_canvas",
            AsyncMock(side_effect=[RuntimeError("boom"), True]),
        ) as migrate:
            assert (
                await _normalize_stored_canvases(
                    [_doc(id="a", updated_at=NOW), _doc(id="b", updated_at=NOW)]
                )
                == 1
            )

        assert migrate.await_count == 2


class TestMaintenanceSweep:
    async def test_every_tracked_todo_gets_the_legacy_canvas_migration(self):
        """The one-shot split rides the sweep over ALL tracked todos — active or completed — not just the active page the tiers classify."""
        todos = [_doc(id="a", updated_at=NOW), _doc(id="b", completed=True, updated_at=NOW)]
        with _sweep(migration=todos) as (_filed, mocks):
            await maintenance_sweep_tracked_todos({})

        assert [c.args[0].id for c in mocks["migrate"].await_args_list] == ["a", "b"]
        # Pins the scan bound: a changed literal would widen or unbind the page.
        mocks["list"].assert_awaited_once_with(limit=200)

    async def test_legacy_migration_pages_past_the_first_page(self):
        """The migration cursor walks every page to a short page, so a legacy todo past the first 200 still migrates, while classification keeps the active-only list."""
        from app.workers.tasks.maintenance_sweep_tasks import _MIGRATION_PAGE_SIZE

        active = [_doc(id="active-1", updated_at=NOW)]
        first_page = [_doc(id=f"migr-{i}", updated_at=NOW) for i in range(_MIGRATION_PAGE_SIZE)]
        last_page = [_doc(id="done-legacy", completed=True, updated_at=NOW)]
        finder = AsyncMock(side_effect=[first_page, last_page])
        classify = AsyncMock(return_value=([], [], []))
        with (
            patch(
                f"{MODULE}.todo_repository.list_active_tracked_all_users",
                AsyncMock(return_value=active),
            ),
            patch(
                f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
                finder,
                create=True,
            ),
            patch(f"{MODULE}._classify_tracked_todos", classify),
            patch(
                f"{MODULE}.tracked_todo_service.normalize_stored_canvas",
                AsyncMock(return_value=False),
            ) as migrate,
        ):
            await maintenance_sweep_tracked_todos({})

        assert finder.await_count == 2
        assert finder.await_args_list[0].kwargs == {
            "limit": _MIGRATION_PAGE_SIZE,
            "after_id": None,
        }
        assert finder.await_args_list[1].kwargs == {
            "limit": _MIGRATION_PAGE_SIZE,
            "after_id": f"migr-{_MIGRATION_PAGE_SIZE - 1}",
        }
        assert migrate.await_count == _MIGRATION_PAGE_SIZE + 1
        assert "done-legacy" in [c.args[0].id for c in migrate.await_args_list]
        assert classify.await_args.args[1] == active

    async def test_migration_failure_does_not_abort_the_sweep(self):
        with _sweep(migration=[_doc(id="a", updated_at=NOW)]) as (_filed, mocks):
            mocks["migrate"].side_effect = RuntimeError("mongo hiccup")
            summary = await maintenance_sweep_tracked_todos({})

        assert summary.startswith("archived:0")

    async def test_expired_todo_archived_by_the_health_check(self):
        with _sweep(
            list=[_doc(id="exp-1", expires_at=datetime.now(UTC) - timedelta(hours=1))],
            health="ARCHIVE: done",
        ) as (_filed, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:1 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["archive"].assert_awaited_once()

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
        notice = mocks["notify"].await_args.args[0]
        assert notice.report_id.startswith(f"sys:{KIND_DORMANT_DIGEST}:user-1:")

    async def test_a_todo_the_sweep_already_filed_today_is_skipped_entirely(self):
        with _sweep(
            list=[_doc(id="quiet-1", expires_at=datetime.now(UTC) - timedelta(hours=1))]
        ) as (filed, mocks):
            filed.return_value = object()
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["health"].assert_not_awaited()

    async def test_summary_reflects_each_tier_count(self):
        """Pin the operator-visible summary format with the processing steps faked."""
        with (
            patch(
                f"{MODULE}.todo_repository.list_active_tracked_all_users",
                AsyncMock(return_value=[]),
            ),
            patch(
                f"{MODULE}.todo_repository.list_tracked_for_legacy_migration",
                AsyncMock(return_value=[]),
                create=True,
            ),
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


def _model_answering(text: str) -> AsyncMock:
    """Stand in for ainvoke_llm with a model that answers text."""
    return AsyncMock(return_value=AIMessage(content=text))


@pytest.mark.unit
class TestHealthCheckVerdict:
    async def test_the_prompt_goes_to_a_bare_model_with_no_tools_bound(self) -> None:
        # The sweep acts on the verdict; a check that could call a tool could act
        # on its own (call_executor was bound while it ran through comms).
        model = MagicMock(name="bare_model")
        invoke = _model_answering("  Still on track  ")
        with (
            patch(f"{MODULE}.resolve_model", return_value=model),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            result = await _health_check_verdict("user-3", "is this todo alive?")

        assert result == "Still on track"
        invoke.assert_awaited_once_with(
            model,
            [HumanMessage(content="is this todo alive?")],
            label="todo_health_check",
            config=metered_config("user-3"),
        )
        model.bind_tools.assert_not_called()

    async def test_an_empty_model_answer_is_an_empty_verdict(self) -> None:
        # The sweep classifies the verdict by reading its text; substituting any
        # placeholder for a missing message would make an empty answer look like
        # a real one to every caller downstream.
        with (
            patch(f"{MODULE}.resolve_model", return_value=MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", _model_answering("")),
        ):
            result = await _health_check_verdict("user-1", "is this todo alive?")

        assert result == ""

    async def test_a_model_failure_is_raised_not_turned_into_a_verdict(self) -> None:
        # A fabricated NEEDS_ATTENTION hid a health check that never ran for months,
        # and on the expired tier it became the body of the user's notification.
        with (
            patch(f"{MODULE}.resolve_model", return_value=MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", AsyncMock(side_effect=TimeoutError("model down"))),
            pytest.raises(TimeoutError, match="model down"),
        ):
            await _health_check_verdict("user-1", "is this todo alive?")


# ---------------------------------------------------------------------------
# Canvas bounding + per-todo containment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCanvasBounding:
    @staticmethod
    def _prompt(invoke: AsyncMock) -> str:
        [message] = invoke.await_args.args[1]
        return str(message.content)

    @pytest.mark.regression
    async def test_an_oversized_canvas_does_not_break_the_health_check_request(self) -> None:
        # Prod: an oversized canvas overran the chat request bound and aborted the
        # whole cron for every user, so the prompt stays under MAX_MESSAGE_LENGTH.
        head = "## Current State\nwaiting on the vendor\n"
        tail = "FINAL CANVAS LINE"
        canvas = head + "x" * (60_000 - len(head) - len(tail)) + tail
        invoke = _model_answering("NEEDS_ATTENTION: still stuck")

        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value=canvas)),
            patch(f"{MODULE}.resolve_model", return_value=MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            outcome = await _health_check_dormant(_doc())

        assert outcome == "needs_attention"
        prompt = self._prompt(invoke)
        assert len(prompt) < MAX_MESSAGE_LENGTH

        # Current State lives near the top and the newest entries are appended
        # at the bottom, so both ends survive and the middle is what is dropped,
        # behind a marker accounting for exactly what went missing.
        marker = re.search(r"\n\[middle of canvas trimmed: (\d+) characters\]\n", prompt)
        assert marker is not None
        before, after = prompt.split(marker.group(0), 1)
        kept_head = before.split("Canvas:\n", 1)[1]
        kept_tail = after.split("\n\nIs there a clear", 1)[0]
        assert kept_head.startswith(head)
        assert kept_tail.endswith(tail)
        assert len(kept_head) + len(kept_tail) + int(marker.group(1)) == len(canvas)
        # The budget is split evenly, and all of it is used.
        assert len(kept_head) == len(kept_tail) == CANVAS_PROMPT_MAX_CHARS // 2

    async def test_a_canvas_under_the_bound_reaches_the_model_untouched(self) -> None:
        canvas = "y" * 1_000
        invoke = _model_answering("NEEDS_ATTENTION: still stuck")

        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value=canvas)),
            patch(f"{MODULE}.resolve_model", return_value=MagicMock()),
            patch(f"{MODULE}.ainvoke_llm", invoke),
        ):
            await _health_check_dormant(_doc())

        prompt = self._prompt(invoke)
        assert f"Canvas:\n{canvas}\n" in prompt
        assert "trimmed" not in prompt


@pytest.mark.unit
class TestSweepSurvivesOneFailingTodo:
    async def test_a_raising_health_check_does_not_cost_the_other_todos_their_sweep(
        self,
    ) -> None:
        # The dormant loop had no per-todo guard, so anything raising inside one
        # health check took the whole cron down with it.
        todos = [
            _doc(id="dor-1", updated_at=datetime.now(UTC) - timedelta(days=10)),
            _doc(id="dor-2", updated_at=datetime.now(UTC) - timedelta(days=10)),
        ]
        with _sweep(list=todos) as (_p, mocks), patch(f"{MODULE}.log") as log:
            mocks["health"].side_effect = [
                RuntimeError("boom"),
                "NEEDS_ATTENTION: waiting on the user",
            ]
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:0 digest_items:1"
        )
        # The survivor is digested; the failed todo is not notified on the
        # strength of a check that never produced a verdict.
        notice = mocks["notify"].await_args.args[0]
        assert notice.facts == ["'Follow up with the client' has been idle for 10 days."]

        # Failing loud is the other half of the fix — a silent skip would hide
        # the next oversized canvas exactly as long as this one hid.
        log.error.assert_called_once_with(
            "maintenance_sweep.dormant_health_check_error",
            todo_id="dor-1",
            user_id="user-1",
            error_type="RuntimeError",
        )


@pytest.mark.unit
class TestExpiredTierContainment:
    async def test_the_expired_prompt_carries_that_todo_s_bounded_canvas(self) -> None:
        # The canvas is the only todo-specific context the expired check gets:
        # reading someone else's canvas (or none at all) turns the verdict into
        # a guess about a todo the agent never saw.
        doc = _doc()
        canvas = AsyncMock(return_value="canvas body text")
        health = AsyncMock(return_value="NOTIFY: still open")
        with (
            patch(f"{MODULE}._read_canvas", canvas),
            patch(f"{MODULE}._health_check_verdict", health),
            patch(f"{MODULE}.submit", AsyncMock()),
        ):
            outcome = await _health_check_expired(doc, NOW)

        assert outcome == "notified"
        canvas.assert_awaited_once_with(doc)
        assert "Canvas:\ncanvas body text\n" in health.await_args.args[1]

    async def test_a_raising_expired_check_is_logged_and_the_other_todos_still_run(
        self,
    ) -> None:
        # Mirror of the dormant containment: one expired todo's failure must not
        # cost every later todo its sweep, and the failure must be loud.
        expired = [
            _doc(id="exp-1", expires_at=datetime.now(UTC) - timedelta(hours=1)),
            _doc(id="exp-2", expires_at=datetime.now(UTC) - timedelta(hours=1)),
        ]
        with _sweep(list=expired) as (_p, mocks), patch(f"{MODULE}.log") as log:
            mocks["health"].side_effect = [RuntimeError("boom"), "ARCHIVE: done"]
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:1 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["archive"].assert_awaited_once_with("exp-2", "user-1", "done")
        log.error.assert_called_once_with(
            "maintenance_sweep.expired_health_check_error",
            todo_id="exp-1",
            user_id="user-1",
            error_type="RuntimeError",
        )

    async def test_a_notifying_expired_check_is_counted_as_notified(self) -> None:
        with _sweep(
            list=[_doc(id="exp-1", expires_at=datetime.now(UTC) - timedelta(hours=1))],
            health="NOTIFY: this one needs a decision",
        ) as (_p, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:1 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["notify"].assert_awaited_once()


@pytest.mark.unit
class TestOverdueTier:
    def _overdue(self, todo_id: str) -> TodoDocument:
        return _doc(id=todo_id, due_date=datetime.now(UTC) - timedelta(days=2))

    async def test_an_overdue_todo_is_notified_labelled_and_counted(self) -> None:
        with _sweep(list=[self._overdue("due-1")]) as (_p, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:1 requeued:0 digest_items:0"
        )
        notice = mocks["notify"].await_args.args[0]
        assert notice.report_id.startswith(f"sys:{KIND_OVERDUE}:due-1:")
        mocks["add_labels"].assert_awaited_once_with(
            "due-1", user_id="user-1", labels=["needs-follow-up"]
        )

    async def test_a_raising_overdue_notification_is_logged_and_the_sweep_continues(
        self,
    ) -> None:
        notify_overdue = AsyncMock(side_effect=[RuntimeError("boom"), True])
        with (
            _sweep(list=[self._overdue("due-1"), self._overdue("due-2")]) as (_p, _mocks),
            patch(f"{MODULE}._notify_overdue", notify_overdue),
            patch(f"{MODULE}.log") as log,
        ):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:1 requeued:0 digest_items:0"
        )
        log.error.assert_called_once_with(
            "maintenance_sweep.overdue_error",
            todo_id="due-1",
            user_id="user-1",
            error_type="RuntimeError",
        )

    async def test_the_night_gate_defers_an_overdue_todo(self) -> None:
        with _sweep(list=[self._overdue("due-1")], daytime=False) as (_p, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:0 digest_items:0"
        )
        mocks["notify"].assert_not_awaited()


@pytest.mark.unit
class TestDormantTierDetails:
    async def test_the_dormant_prompt_carries_that_todo_s_bounded_canvas(self) -> None:
        doc = _doc()
        canvas = AsyncMock(return_value="canvas body text")
        health = AsyncMock(return_value="NEEDS_ATTENTION: blocked")
        with (
            patch(f"{MODULE}._read_canvas", canvas),
            patch(f"{MODULE}._health_check_verdict", health),
        ):
            outcome = await _health_check_dormant(doc)

        assert outcome == "needs_attention"
        canvas.assert_awaited_once_with(doc)
        assert "Canvas:\ncanvas body text\n" in health.await_args.args[1]

    async def test_the_requeue_jitter_spans_ten_to_a_hundred_and_twenty_seconds(self) -> None:
        # The jitter exists to spread re-queued executions across the minutes
        # after a sweep; a zero lower bound would fire them all at once and a
        # wider upper bound would drift past the window the sweep reasons about.
        now_before = datetime.now(UTC)
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value="")),
            patch(
                f"{MODULE}._health_check_verdict",
                AsyncMock(return_value="EXECUTE: send the follow-up email"),
            ),
            patch(f"{MODULE}.tracked_todo_service.schedule_execution", AsyncMock()) as schedule,
            patch(f"{MODULE}.todo_repository.update", AsyncMock()),
            patch(f"{MODULE}.record_activity", AsyncMock()),
            patch(f"{MODULE}.random.randint", return_value=42) as randint,
        ):
            outcome = await _health_check_dormant(_doc())

        assert outcome == "requeued"
        randint.assert_called_once_with(10, 120)
        run_at = schedule.await_args.args[1]
        assert (
            now_before + timedelta(seconds=42)
            <= run_at
            <= datetime.now(UTC) + timedelta(seconds=42)
        )

    async def test_a_requeued_dormant_todo_files_no_notice(self) -> None:
        with _sweep(
            list=[_doc(id="dor-1", updated_at=datetime.now(UTC) - timedelta(days=10))],
            health="EXECUTE: send the follow-up email",
        ) as (_filed, mocks):
            summary = await maintenance_sweep_tracked_todos({})

        assert (
            summary == "archived:0 notified_expired:0 notified_overdue:0 requeued:1 digest_items:0"
        )
        mocks["schedule"].assert_awaited_once()
        mocks["notify"].assert_not_awaited()


@pytest.mark.unit
class TestCanvasBoundIsInclusive:
    async def test_a_canvas_of_exactly_the_bound_is_not_trimmed(self) -> None:
        # The bound is the largest canvas that still fits, not the first one that
        # doesn't: trimming at exactly the cap costs a character of real content
        # and stamps a "0 characters trimmed" marker on an untouched canvas.
        canvas = "z" * CANVAS_PROMPT_MAX_CHARS
        health = AsyncMock(return_value="NEEDS_ATTENTION: still stuck")
        with (
            patch(f"{MODULE}._read_canvas", AsyncMock(return_value=canvas)),
            patch(f"{MODULE}._health_check_verdict", health),
        ):
            await _health_check_dormant(_doc())

        prompt = health.await_args.args[1]
        assert f"Canvas:\n{canvas}\n" in prompt
        assert "trimmed" not in prompt
