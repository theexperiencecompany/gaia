"""Unit tests for the paid-only-gate workflow-deactivation migration.

Two behaviors decide whether a production run is safe: `--dry-run` (the
default) must never write, and `--execute` must touch exactly the users with
no active subscription — never a paying user's workflows.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from scripts.deactivate_workflows_for_free_users import (
    find_free_user_candidates,
    run_migration,
)

MODULE = "scripts.deactivate_workflows_for_free_users"

FREE_USER = "free-user-1"
PRO_USER = "pro-user-1"


def _workflow(workflow_id: str) -> MagicMock:
    w = MagicMock()
    w.id = workflow_id
    return w


class TestFindFreeUserCandidates:
    async def test_skips_users_with_an_active_subscription(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository") as subscription_repo,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(
                return_value=[FREE_USER, PRO_USER]
            )
            subscription_repo.get_active_for_user = AsyncMock(
                side_effect=lambda user_id: MagicMock() if user_id == PRO_USER else None
            )
            workflow_repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])

            candidates = await find_free_user_candidates()

        assert [c.user_id for c in candidates] == [FREE_USER]

    async def test_skips_a_free_user_with_no_activated_workflows(self) -> None:
        """distinct_users_with_activated_workflows already filters this, but the
        candidate build must not blow up or fabricate an entry if it ever returns
        a user whose workflows were deactivated between the two reads."""
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository") as subscription_repo,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(
                return_value=[FREE_USER]
            )
            subscription_repo.get_active_for_user = AsyncMock(return_value=None)
            workflow_repo.find_activated_for_user = AsyncMock(return_value=[])

            candidates = await find_free_user_candidates()

        assert candidates == []

    async def test_candidate_carries_every_activated_workflow_id(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository") as subscription_repo,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(
                return_value=[FREE_USER]
            )
            subscription_repo.get_active_for_user = AsyncMock(return_value=None)
            workflow_repo.find_activated_for_user = AsyncMock(
                return_value=[_workflow("wf-1"), _workflow("wf-2")]
            )

            (candidate,) = await find_free_user_candidates()

        assert candidate.workflow_ids == ["wf-1", "wf-2"]


class TestRunMigration:
    async def test_dry_run_writes_nothing(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository") as subscription_repo,
            patch(f"{MODULE}.deactivate_workflows_for_lapsed_subscription") as deactivate,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(
                return_value=[FREE_USER]
            )
            subscription_repo.get_active_for_user = AsyncMock(return_value=None)
            workflow_repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])
            deactivate.return_value = 1

            result = await run_migration(dry_run=True)

        assert result.dry_run is True
        assert len(result.free_users) == 1
        assert result.workflows_deactivated == 0
        deactivate.assert_not_awaited()

    async def test_execute_deactivates_exactly_the_free_users_workflows(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository") as subscription_repo,
            patch(f"{MODULE}.deactivate_workflows_for_lapsed_subscription") as deactivate,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(
                return_value=[FREE_USER, PRO_USER]
            )
            subscription_repo.get_active_for_user = AsyncMock(
                side_effect=lambda user_id: MagicMock() if user_id == PRO_USER else None
            )
            workflow_repo.find_activated_for_user = AsyncMock(
                return_value=[_workflow("wf-1"), _workflow("wf-2")]
            )
            deactivate.return_value = 2

            result = await run_migration(dry_run=False)

        assert result.dry_run is False
        assert result.workflows_deactivated == 2
        deactivate.assert_awaited_once_with(FREE_USER)

    async def test_no_free_users_deactivates_nothing(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as workflow_repo,
            patch(f"{MODULE}.subscription_repository"),
            patch(f"{MODULE}.deactivate_workflows_for_lapsed_subscription") as deactivate,
        ):
            workflow_repo.distinct_users_with_activated_workflows = AsyncMock(return_value=[])

            result = await run_migration(dry_run=False)

        assert result.free_users == []
        assert result.workflows_deactivated == 0
        deactivate.assert_not_awaited()
