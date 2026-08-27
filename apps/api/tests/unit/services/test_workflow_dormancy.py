"""Unit tests for app.services.workflow.dormancy — the dormant-user workflow sweep."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models.workflow_models import DeactivationReason
from app.services.workflow.dormancy import (
    DORMANCY_THRESHOLD,
    resume_dormancy_paused_workflows,
    sweep_dormant_workflows,
)

_MOD = "app.services.workflow.dormancy"


def _user(user_id: str, days_idle: int | None = 90) -> SimpleNamespace:
    last_active = None if days_idle is None else datetime.now(UTC) - timedelta(days=days_idle)
    return SimpleNamespace(id=user_id, last_active_at=last_active)


def _workflow(workflow_id: str) -> SimpleNamespace:
    return SimpleNamespace(id=workflow_id)


def _patches(
    *,
    users: list[SimpleNamespace],
    workflows_by_user: dict[str, list[SimpleNamespace]],
    deactivate: AsyncMock | None = None,
    chat_active: set[str] | None = None,
    metered_active: set[str] | None = None,
):
    chat_active = chat_active or set()
    metered_active = metered_active or set()
    return (
        patch(
            f"{_MOD}.user_repository.find_dormant_since",
            new_callable=AsyncMock,
            return_value=users,
        ),
        patch(
            f"{_MOD}.conversation_repository.has_activity_since",
            new_callable=AsyncMock,
            side_effect=lambda uid, _cut: uid in chat_active,
        ),
        patch(
            f"{_MOD}.usage_daily_repository.counts_since",
            new_callable=AsyncMock,
            side_effect=lambda uid, _day: {"2026-08-01": 3} if uid in metered_active else {},
        ),
        patch(
            f"{_MOD}.workflow_repository.find_activated_for_user",
            new_callable=AsyncMock,
            side_effect=lambda uid: workflows_by_user.get(uid, []),
        ),
        patch(
            f"{_MOD}.WorkflowService.deactivate_workflow",
            new_callable=AsyncMock,
            side_effect=deactivate.side_effect if deactivate else None,
        )
        if deactivate is None
        else patch(f"{_MOD}.WorkflowService.deactivate_workflow", deactivate),
    )


@pytest.mark.unit
class TestSweepDormantWorkflows:
    async def test_dry_run_reports_the_cohort_without_writing(self):
        deactivate = AsyncMock()
        dormant, no_workflows = _user("u1"), _user("u2")
        p = _patches(
            users=[dormant, no_workflows],
            workflows_by_user={"u1": [_workflow("wf_a"), _workflow("wf_b")], "u2": []},
            deactivate=deactivate,
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows(dry_run=True)

        deactivate.assert_not_awaited()
        assert result.dry_run is True
        assert result.workflows_paused == 0
        # u2 owns nothing activated, so it is not a candidate at all.
        assert [c.user_id for c in result.candidates] == ["u1"]
        assert result.candidates[0].workflow_ids == ["wf_a", "wf_b"]
        # The real stamp, not a placeholder: it is what the dry-run script prints
        # for an operator to judge how stale the cohort actually is.
        assert result.candidates[0].last_active_at == dormant.last_active_at

    async def test_pausing_stamps_the_dormancy_reason(self):
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("u1")],
            workflows_by_user={"u1": [_workflow("wf_a")]},
            deactivate=deactivate,
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows()

        assert result.workflows_paused == 1
        deactivate.assert_awaited_once_with("wf_a", "u1", reason=DeactivationReason.USER_DORMANT)

    async def test_one_failing_workflow_does_not_abort_the_sweep(self):
        deactivate = AsyncMock(side_effect=[RuntimeError("composio down"), None])
        p = _patches(
            users=[_user("u1"), _user("u2")],
            workflows_by_user={"u1": [_workflow("wf_a")], "u2": [_workflow("wf_b")]},
            deactivate=deactivate,
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows()

        assert result.failures == 1
        assert result.workflows_paused == 1

    async def test_a_user_never_seen_active_counts_as_dormant(self):
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("u1", days_idle=None)],
            workflows_by_user={"u1": [_workflow("wf_a")]},
            deactivate=deactivate,
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows()

        assert result.workflows_paused == 1
        assert result.candidates[0].last_active_at is None

    # Deliberately carries no regression marker. That marker means "this bug
    # existed on the base revision", and the regression-proof lane re-runs marked
    # tests against base to prove they go red there. This whole module is new, so
    # on base the file cannot even be collected — an error, which the lane rightly
    # refuses to accept as proof. Both tests below are still mutation-checked on
    # this branch (drop the `_is_really_dormant` call and they go red).
    async def test_recent_chat_keeps_a_user_out_of_the_cohort(self):
        """`last_active_at` is bumped only by a WorkOS web login, so a user who
        lives in a bot looks dormant on it while using GAIA daily. On production
        that was 210 users owning 1,965 activated workflows at a 30-day cutoff."""
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("bot_user"), _user("really_gone")],
            workflows_by_user={
                "bot_user": [_workflow("wf_a")],
                "really_gone": [_workflow("wf_b")],
            },
            deactivate=deactivate,
            chat_active={"bot_user"},
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows()

        assert [c.user_id for c in result.candidates] == ["really_gone"]
        deactivate.assert_awaited_once_with(
            "wf_b", "really_gone", reason=DeactivationReason.USER_DORMANT
        )

    async def test_recent_metered_usage_keeps_a_user_out_of_the_cohort(self):
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("api_user")],
            workflows_by_user={"api_user": [_workflow("wf_a")]},
            deactivate=deactivate,
            metered_active={"api_user"},
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows()

        assert result.candidates == []
        deactivate.assert_not_awaited()

    async def test_automation_only_usage_rows_do_not_mask_dormancy(self):
        """A pure-automation day writes a usage_daily row with cost but count 0.
        Truthiness of the returned dict read that as "active", so a user whose
        only footprint was their own workflow firing could never be swept."""
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("wf_only")],
            workflows_by_user={"wf_only": [_workflow("wf_a")]},
            deactivate=deactivate,
        )
        with (
            p[0],
            p[1],
            patch(
                f"{_MOD}.usage_daily_repository.counts_since",
                new_callable=AsyncMock,
                return_value={"2026-08-01": 0, "2026-08-02": 0},
            ),
            p[3],
            p[4],
        ):
            result = await sweep_dormant_workflows()

        assert result.workflows_paused == 1
        deactivate.assert_awaited_once_with(
            "wf_a", "wf_only", reason=DeactivationReason.USER_DORMANT
        )

    async def test_max_users_bounds_one_run(self):
        """Pausing unregisters Composio triggers per workflow, so an unbounded
        first run over a long backlog is a burst of third-party calls."""
        deactivate = AsyncMock()
        p = _patches(
            users=[_user("u1"), _user("u2"), _user("u3")],
            workflows_by_user={
                "u1": [_workflow("wf_a")],
                "u2": [_workflow("wf_b")],
                "u3": [_workflow("wf_c")],
            },
            deactivate=deactivate,
        )
        with p[0], p[1], p[2], p[3], p[4]:
            result = await sweep_dormant_workflows(max_users=2)

        assert [c.user_id for c in result.candidates] == ["u1", "u2"]
        assert result.workflows_paused == 2

    @pytest.mark.parametrize("bad", [timedelta(0), timedelta(days=-1)])
    async def test_a_non_positive_threshold_is_refused(self, bad: timedelta):
        """A zero threshold puts the cutoff at this instant, so EVERY prior
        activity timestamp falls before it and every user reads as dormant —
        `--days 0` would pause the whole product. A negative one is worse: the
        cutoff moves into the future."""
        find_dormant = AsyncMock(return_value=[])
        with (
            patch(f"{_MOD}.user_repository.find_dormant_since", find_dormant),
            pytest.raises(ValueError, match="must be positive"),
        ):
            await sweep_dormant_workflows(threshold=bad)

        # Refused at the boundary: the cohort query never even ran.
        find_dormant.assert_not_awaited()

    async def test_both_activity_signals_are_asked_about_the_same_cutoff(self):
        """The cutoff must reach BOTH repositories, and reach usage_daily in the
        `YYYY-MM-DD` shape its `date` field is stored as. Nothing else pins this:
        the doubles elsewhere discard the argument, so a wrong (or wrongly
        formatted) cutoff would still report the user dormant — the direction
        that pauses a live user's workflows."""
        chat = AsyncMock(return_value=False)
        metered = AsyncMock(return_value={})
        with (
            patch(
                f"{_MOD}.user_repository.find_dormant_since",
                new_callable=AsyncMock,
                return_value=[_user("u1")],
            ),
            patch(f"{_MOD}.conversation_repository.has_activity_since", chat),
            patch(f"{_MOD}.usage_daily_repository.counts_since", metered),
            patch(
                f"{_MOD}.workflow_repository.find_activated_for_user",
                new_callable=AsyncMock,
                return_value=[_workflow("wf_a")],
            ),
            patch(f"{_MOD}.WorkflowService.deactivate_workflow", new_callable=AsyncMock),
        ):
            result = await sweep_dormant_workflows(threshold=timedelta(days=90))

        assert chat.await_args.args == ("u1", result.cutoff)
        assert metered.await_args.args == ("u1", result.cutoff.strftime("%Y-%m-%d"))

    async def test_the_threshold_defaults_to_thirty_days(self):
        """A month of silence on every human signal is dormancy. The old 90 was
        covering for signals automation could pollute; see DORMANCY_THRESHOLD."""
        assert timedelta(days=30) == DORMANCY_THRESHOLD

    async def test_the_cutoff_honours_the_threshold(self):
        find_dormant = AsyncMock(return_value=[])
        with (
            patch(f"{_MOD}.user_repository.find_dormant_since", find_dormant),
            patch(
                f"{_MOD}.workflow_repository.find_activated_for_user",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await sweep_dormant_workflows(threshold=timedelta(days=7))

        cutoff = find_dormant.await_args.args[0]
        assert (datetime.now(UTC) - cutoff).days == 7
        assert result.cutoff == cutoff


@pytest.mark.unit
class TestResumeDormancyPausedWorkflows:
    async def test_only_dormancy_paused_workflows_are_resumed(self):
        find_paused = AsyncMock(return_value=[_workflow("wf_a")])
        activate = AsyncMock()
        with (
            patch(f"{_MOD}.workflow_repository.find_paused_for_reason", find_paused),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 1
        # The reason is what keeps a user's own deactivation out of the result set.
        find_paused.assert_awaited_once_with("u1", DeactivationReason.USER_DORMANT)
        activate.assert_awaited_once_with("wf_a", "u1")

    async def test_a_workflow_that_cannot_be_reactivated_is_skipped(self):
        """A disconnected integration must not block the user's other workflows."""
        activate = AsyncMock(side_effect=[ValueError("Connect Gmail to enable this."), None])
        with (
            patch(
                f"{_MOD}.workflow_repository.find_paused_for_reason",
                new_callable=AsyncMock,
                return_value=[_workflow("wf_a"), _workflow("wf_b")],
            ),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 1

    async def test_nothing_paused_is_a_no_op(self):
        activate = AsyncMock()
        with (
            patch(
                f"{_MOD}.workflow_repository.find_paused_for_reason",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_MOD}.WorkflowService.activate_workflow", activate),
        ):
            resumed = await resume_dormancy_paused_workflows("u1")

        assert resumed == 0
        activate.assert_not_awaited()
