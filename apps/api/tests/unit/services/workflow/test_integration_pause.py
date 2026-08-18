"""Pausing a user's workflows when an integration dies, and resuming on reconnect.

An activated workflow whose integration is dead keeps firing on schedule and
delivers a failed run, which reads to the user as "GAIA is broken" rather than
"Gmail needs reconnecting".
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_models import DeactivationReason
from app.services.workflow.integration_pause import pause_workflows_for_expired_integration
from app.services.workflow.integration_resume import resume_workflows_for_reconnected_integration

PAUSE = "app.services.workflow.integration_pause"
RESUME = "app.services.workflow.integration_resume"

USER_ID = "507f1f77bcf86cd799439011"


def _workflow(workflow_id: str, title: str) -> MagicMock:
    w = MagicMock()
    w.id = workflow_id
    w.title = title
    return w


class TestPause:
    @pytest.mark.regression
    async def test_it_pauses_only_the_workflows_that_need_the_dead_integration(self) -> None:
        gmail_wf = _workflow("wf-1", "Morning digest")
        notion_wf = _workflow("wf-2", "Notes sync")

        with (
            patch(f"{PAUSE}.workflow_repository") as repo,
            patch(f"{PAUSE}.compute_required_integrations") as required,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[gmail_wf, notion_wf])
            repo.deactivate = AsyncMock()
            required.side_effect = lambda steps, trigger: (
                {"gmail"} if steps is gmail_wf.steps else {"notion"}
            )

            paused = await pause_workflows_for_expired_integration(USER_ID, "gmail")

        assert paused == ["Morning digest"]
        repo.deactivate.assert_awaited_once_with(
            "wf-1", USER_ID, reason=DeactivationReason.INTEGRATION_EXPIRED
        )

    async def test_one_failure_does_not_abort_the_rest(self) -> None:
        first = _workflow("wf-1", "First")
        second = _workflow("wf-2", "Second")

        with (
            patch(f"{PAUSE}.workflow_repository") as repo,
            patch(f"{PAUSE}.compute_required_integrations", return_value={"gmail"}),
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[first, second])
            repo.deactivate = AsyncMock(side_effect=[RuntimeError("composio down"), None])

            paused = await pause_workflows_for_expired_integration(USER_ID, "gmail")

        # A half-applied expiry beats none: the second workflow still stopped.
        assert paused == ["Second"]

    async def test_nothing_to_pause_is_not_an_error(self) -> None:
        with (
            patch(f"{PAUSE}.workflow_repository") as repo,
            patch(f"{PAUSE}.compute_required_integrations", return_value={"notion"}),
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1", "Other")])
            repo.deactivate = AsyncMock()

            assert await pause_workflows_for_expired_integration(USER_ID, "gmail") == []
            repo.deactivate.assert_not_awaited()


class TestResume:
    @pytest.mark.regression
    async def test_it_only_resumes_workflows_this_feature_paused(self) -> None:
        # A workflow the user switched off records no reason, so the reason filter
        # is what stops a reconnect silently re-enabling it.
        with (
            patch(f"{RESUME}.workflow_repository") as repo,
            patch(f"{RESUME}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{RESUME}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.activate_workflow = AsyncMock()

            resumed = await resume_workflows_for_reconnected_integration(USER_ID, "gmail")

        assert resumed == 1
        repo.find_paused_for_reason.assert_awaited_once_with(
            USER_ID, DeactivationReason.INTEGRATION_EXPIRED
        )
        service.activate_workflow.assert_awaited_once_with("wf-1", USER_ID)

    @pytest.mark.regression
    async def test_a_workflow_still_missing_another_integration_stays_paused(self) -> None:
        # activate_workflow refuses while any required integration is missing, so
        # reconnecting Gmail must not re-arm a workflow that also needs Notion.
        with (
            patch(f"{RESUME}.workflow_repository") as repo,
            patch(f"{RESUME}.compute_required_integrations", return_value={"gmail", "notion"}),
            patch(f"{RESUME}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.activate_workflow = AsyncMock(
                side_effect=ValueError("Connect Notion to enable this workflow.")
            )

            resumed = await resume_workflows_for_reconnected_integration(USER_ID, "gmail")

        assert resumed == 0

    async def test_it_ignores_workflows_that_do_not_need_this_integration(self) -> None:
        with (
            patch(f"{RESUME}.workflow_repository") as repo,
            patch(f"{RESUME}.compute_required_integrations", return_value={"notion"}),
            patch(f"{RESUME}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Notes")])
            service.activate_workflow = AsyncMock()

            assert await resume_workflows_for_reconnected_integration(USER_ID, "gmail") == 0
            service.activate_workflow.assert_not_awaited()
