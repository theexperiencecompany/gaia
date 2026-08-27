"""Argument-level coverage for the system-run guards in execute_workflow_by_id.

The onboarding lookup, the daily cost-budget call and the skip-path re-arm are
asserted on the arguments they receive: a call-count-only assertion cannot tell
a correct call from one made for the wrong user, feature or workflow.
"""

from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.limit_upsell import LimitHitOrigin, current_limit_origin
from app.workers.tasks.workflow_tasks import _resolve_workflow_user, execute_workflow_by_id

MODULE = "app.workers.tasks.workflow_tasks"


class _Run(NamedTuple):
    result: str
    scheduler: MagicMock
    user_get: AsyncMock
    budget: AsyncMock
    log: MagicMock


def _workflow(user_id: str = "user-1", occurrence_count: int = 2) -> MagicMock:
    wf = MagicMock()
    wf.id = "wf-1"
    wf.user_id = user_id
    wf.steps = []
    wf.repeat = True
    wf.activated = True
    wf.occurrence_count = occurrence_count
    return wf


def _user(completed: bool) -> MagicMock:
    user = MagicMock()
    user.onboarding = {"completed": completed}
    return user


async def _run_task(
    workflow: MagicMock,
    user: MagicMock,
    context: dict[str, Any] | None,
    rearm_error: Exception | None = None,
    budget_side_effect: Callable[..., Awaitable[None]] | None = None,
) -> _Run:
    scheduler = MagicMock()
    scheduler.get_task = AsyncMock(return_value=workflow)
    scheduler.claim_scheduled_for_execution = AsyncMock(return_value=True)
    scheduler.handle_recurring_task = AsyncMock(side_effect=rearm_error)
    user_get = AsyncMock(return_value=user)
    with (
        patch(f"{MODULE}.workflow_scheduler", scheduler),
        patch(f"{MODULE}.user_repository.get", user_get),
        patch(
            f"{MODULE}.enforce_daily_cost_budget",
            new_callable=AsyncMock,
            side_effect=budget_side_effect,
        ) as budget,
        patch(f"{MODULE}.create_execution", new_callable=AsyncMock) as create,
        patch(
            f"{MODULE}.execute_workflow_as_chat",
            new_callable=AsyncMock,
            return_value=("conv-1", []),
        ),
        patch(f"{MODULE}.complete_execution", new_callable=AsyncMock),
        patch(f"{MODULE}.WorkflowService.increment_execution_count", new_callable=AsyncMock),
        patch(f"{MODULE}.capture_event"),
        patch(f"{MODULE}.log") as log,
    ):
        create.return_value = MagicMock(execution_id="exec-1")
        result = await execute_workflow_by_id({}, "wf-1", context)
    return _Run(result, scheduler, user_get, budget, log)


class TestSystemRunGuards:
    async def test_onboarding_is_checked_for_the_workflows_owner(self) -> None:
        run = await _run_task(
            _workflow("owner-7"), _user(completed=False), {"trigger_type": "schedule"}
        )
        assert "has not completed onboarding" in run.result
        run.user_get.assert_awaited_once_with("owner-7")

    async def test_budget_enforced_for_owner_on_workflow_execution_feature(self) -> None:
        run = await _run_task(
            _workflow("owner-7"), _user(completed=True), {"trigger_type": "schedule"}
        )
        run.budget.assert_awaited_once_with(
            "owner-7",
            feature_key="trigger_workflow_executions",
        )

    @pytest.mark.parametrize(
        ("trigger_type", "expected"),
        [
            ("schedule", LimitHitOrigin.BACKGROUND),
            ("integration", LimitHitOrigin.BACKGROUND),
            ("manual", LimitHitOrigin.INTERACTIVE),
        ],
    )
    async def test_the_budget_wall_runs_under_the_origin_the_trigger_implies(
        self, trigger_type: str, expected: LimitHitOrigin
    ) -> None:
        """Which email a limit hit sends. Asserted at the wall rather than on the
        call's arguments: the origin now reaches the seam through the run's
        context, so the argument list cannot show whether it is right."""
        seen: list[LimitHitOrigin] = []

        async def _record(*_args: object, **_kwargs: object) -> None:
            seen.append(current_limit_origin())

        await _run_task(
            _workflow("owner-7"),
            _user(completed=True),
            {"trigger_type": trigger_type},
            budget_side_effect=_record,
        )

        assert seen == [expected]

    async def test_skipped_recurring_workflow_still_arms_next_occurrence(self) -> None:
        workflow = _workflow(occurrence_count=2)
        run = await _run_task(workflow, _user(completed=False), {"trigger_type": "schedule"})
        run.scheduler.handle_recurring_task.assert_awaited_once_with(workflow, 3)

    async def test_rearm_failure_on_skip_names_the_workflow(self) -> None:
        run = await _run_task(
            _workflow(),
            _user(completed=False),
            {"trigger_type": "schedule"},
            rearm_error=RuntimeError("boom"),
        )
        run.log.error.assert_called_once()
        assert "wf-1" in run.log.error.call_args.args[0]
        assert "boom" in run.log.error.call_args.args[0]


def _timezone_workflow(schedule_tz: str | None) -> MagicMock:
    workflow = _workflow()
    workflow.trigger_config = MagicMock(timezone=schedule_tz)
    return workflow


def _profile(timezone: str | None) -> dict[str, Any]:
    return {"email": "ada@example.com", "name": "Ada", "timezone": timezone}


@pytest.mark.unit
class TestResolveWorkflowUser:
    """The clock a scheduled run executes on.

    An ARQ worker has no request and no ``X-Timezone`` header, so this function
    is the only thing standing between a user's 8am digest and one that arrives
    at 8am UTC. Both run paths read the zone straight back off
    ``user_data["timezone"]``: the agent through ``build_agent_config`` and the
    replay through ``$now`` / ``$today``.
    """

    async def _resolve(
        self, profile: dict[str, Any] | Exception | None, schedule_tz: str | None
    ) -> tuple[dict[str, Any], MagicMock]:
        lookup = AsyncMock(
            side_effect=profile if isinstance(profile, Exception) else None,
            return_value=None if isinstance(profile, Exception) else profile,
        )
        with (
            patch(f"{MODULE}.get_user_by_id", lookup),
            patch(f"{MODULE}.log") as log,
        ):
            user_data = await _resolve_workflow_user(_timezone_workflow(schedule_tz), "user-1")
        lookup.assert_awaited_once_with("user-1")
        return dict(user_data), log

    async def test_a_real_profile_zone_wins_over_the_schedule_zone(self) -> None:
        """The user's own clock is the one they meant, wherever the schedule was
        created from."""
        user_data, log = await self._resolve(_profile("Asia/Kolkata"), "America/New_York")

        assert user_data["timezone"] == "Asia/Kolkata"
        assert user_data["user_id"] == "user-1"
        assert user_data["email"] == "ada@example.com"
        log.set.assert_called_once_with(workflow_agent_timezone="Asia/Kolkata")
        log.warning.assert_not_called()

    async def test_a_utc_profile_zone_defers_to_the_schedule_zone(self) -> None:
        """UTC on a profile is the default nobody chose, so a schedule that names
        a real zone is better information than it.

        Trusting it would run every digest hours off for users who never opened
        the timezone setting.
        """
        for stored in ("UTC", "utc"):
            user_data, _ = await self._resolve(_profile(stored), "America/New_York")
            assert user_data["timezone"] == "America/New_York", stored

    async def test_a_blank_profile_zone_falls_back_to_the_schedule_zone(self) -> None:
        """Whitespace in the profile is not a timezone."""
        for stored in (None, "", "   "):
            user_data, _ = await self._resolve(_profile(stored), "America/New_York")
            assert user_data["timezone"] == "America/New_York", stored

    async def test_no_zone_anywhere_falls_back_to_utc_and_says_so(self) -> None:
        """UTC here is a real degradation, not a neutral default: the run lands
        at the wrong hour for everyone outside UTC. It has to be visible in the
        logs, with the workflow and user that hit it.
        """
        user_data, log = await self._resolve(_profile(None), None)

        assert user_data["timezone"] == "UTC"
        log.set.assert_called_once_with(workflow_agent_timezone="UTC")
        assert "UTC" in log.warning.call_args.args[0]
        assert log.warning.call_args.kwargs["workflow_id"] == "wf-1"
        assert log.warning.call_args.kwargs["user_id"] == "user-1"

    async def test_a_blank_schedule_zone_is_not_a_zone_either(self) -> None:
        user_data, _ = await self._resolve(_profile(None), "   ")

        assert user_data["timezone"] == "UTC"

    async def test_a_missing_profile_still_produces_a_usable_user_bag(self) -> None:
        """A user row that has gone missing must not take the run down with it;
        the schedule's own zone is still the right clock."""
        user_data, _ = await self._resolve(None, "America/New_York")

        assert user_data["user_id"] == "user-1"
        assert user_data["timezone"] == "America/New_York"

    async def test_a_failing_profile_lookup_still_returns_the_user_id(self) -> None:
        """The caller runs the workflow with whatever comes back, so this has to
        be a usable bag rather than an exception that kills the fire.

        The failure is logged with the exception type and text, because a run
        that silently switched to UTC is otherwise indistinguishable from one
        that was always UTC.
        """
        user_data, log = await self._resolve(RuntimeError("mongo down"), "America/New_York")

        assert user_data == {"user_id": "user-1"}
        assert log.warning.call_args.kwargs["error_type"] == "RuntimeError"
        assert log.warning.call_args.kwargs["error"] == "mongo down"
        assert log.warning.call_args.kwargs["user_id"] == "user-1"
        assert log.warning.call_args.kwargs["workflow_id"] == "wf-1"
