"""Deactivating a user's workflows once their Dodo subscription lapses.

Mirrors ``test_integration_pause.py``: goes through ``WorkflowService`` so a
deactivation also unregisters the workflow's Composio trigger upstream, not
just flips a local flag.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.workflow_models import DeactivationReason
from app.services.workflow.subscription_pause import (
    deactivate_workflows_for_lapsed_subscription,
    reactivate_workflows_for_restored_subscription,
)

MODULE = "app.services.workflow.subscription_pause"

USER_ID = "507f1f77bcf86cd799439011"


def _workflow(workflow_id: str, *, activated: bool = True) -> MagicMock:
    w = MagicMock()
    w.id = workflow_id
    w.activated = activated
    return w


class TestDeactivateWorkflowsForLapsedSubscription:
    async def test_deactivates_every_activated_workflow_the_user_owns(self) -> None:
        first = _workflow("wf-1")
        second = _workflow("wf-2")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[first, second])
            service.deactivate_workflow = AsyncMock()

            deactivated = await deactivate_workflows_for_lapsed_subscription(USER_ID)

        assert deactivated == 2
        assert service.deactivate_workflow.await_args_list == [
            ((first.id, USER_ID), {"reason": DeactivationReason.SUBSCRIPTION_LAPSED}),
            ((second.id, USER_ID), {"reason": DeactivationReason.SUBSCRIPTION_LAPSED}),
        ]

    async def test_scopes_to_the_given_user_only(self) -> None:
        """Deactivating another user's workflows would be a real data-safety bug."""

        async def _activated(user_id: str) -> list[MagicMock]:
            return [_workflow("wf-mine")] if user_id == USER_ID else [_workflow("wf-other")]

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(side_effect=_activated)
            service.deactivate_workflow = AsyncMock()

            await deactivate_workflows_for_lapsed_subscription(USER_ID)

        service.deactivate_workflow.assert_awaited_once_with(
            "wf-mine", USER_ID, reason=DeactivationReason.SUBSCRIPTION_LAPSED
        )

    async def test_one_failure_does_not_abort_the_rest(self) -> None:
        first = _workflow("wf-1")
        second = _workflow("wf-2")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[first, second])
            service.deactivate_workflow = AsyncMock(
                side_effect=[RuntimeError("composio down"), None]
            )

            deactivated = await deactivate_workflows_for_lapsed_subscription(USER_ID)

        # A half-applied deactivation beats none: the second workflow still stopped.
        assert deactivated == 1

    async def test_no_activated_workflows_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[])
            service.deactivate_workflow = AsyncMock()

            assert await deactivate_workflows_for_lapsed_subscription(USER_ID) == 0
            service.deactivate_workflow.assert_not_awaited()

    async def test_rerunning_after_success_deactivates_nothing_again(self) -> None:
        """Idempotency: once a workflow is deactivated it is no longer
        ``activated``, so a second sweep for the same user finds nothing left."""
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])
            service.deactivate_workflow = AsyncMock()
            first_run = await deactivate_workflows_for_lapsed_subscription(USER_ID)

            # The workflow is now deactivated, so the repository would no longer
            # return it as "activated" on a re-run.
            repo.find_activated_for_user = AsyncMock(return_value=[])
            second_run = await deactivate_workflows_for_lapsed_subscription(USER_ID)

        assert first_run == 1
        assert second_run == 0
        service.deactivate_workflow.assert_awaited_once()

    async def test_it_never_deactivates_behind_the_service_and_strands_a_composio_trigger(
        self,
    ) -> None:
        # Writing `activated=False` straight through the repository leaves the
        # workflow's Composio trigger enabled upstream; only
        # WorkflowService.deactivate_workflow unregisters it.
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])
            service.deactivate_workflow = AsyncMock()

            await deactivate_workflows_for_lapsed_subscription(USER_ID)

        service.deactivate_workflow.assert_awaited_once_with(
            "wf-1", USER_ID, reason=DeactivationReason.SUBSCRIPTION_LAPSED
        )
        repo.deactivate.assert_not_called()

    async def test_the_skip_warning_carries_the_workflow_user_and_cause(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])
            service.deactivate_workflow = AsyncMock(side_effect=RuntimeError("composio down"))

            await deactivate_workflows_for_lapsed_subscription(USER_ID)

        mock_log.warning.assert_called_once()
        message, kwargs = mock_log.warning.call_args.args[0], mock_log.warning.call_args.kwargs
        assert "Could not deactivate workflow" in message
        assert kwargs == {
            "workflow_id": "wf-1",
            "user_id": USER_ID,
            "error": "composio down",
            "error_type": "RuntimeError",
        }

    async def test_the_summary_log_fires_only_when_something_was_deactivated(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1")])
            service.deactivate_workflow = AsyncMock()

            await deactivate_workflows_for_lapsed_subscription(USER_ID)

        mock_log.info.assert_called_once()
        message, kwargs = mock_log.info.call_args.args[0], mock_log.info.call_args.kwargs
        assert "Deactivated workflows" in message
        assert kwargs == {"user_id": USER_ID, "deactivated": 1}

    async def test_the_summary_log_is_silent_on_a_no_op_run(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[])
            service.deactivate_workflow = AsyncMock()

            await deactivate_workflows_for_lapsed_subscription(USER_ID)

        mock_log.info.assert_not_called()


class TestReactivateWorkflowsForRestoredSubscription:
    async def test_it_only_reactivates_workflows_this_feature_paused(self) -> None:
        # A workflow the user switched off records no reason, so the reason
        # filter is what stops a resubscribe silently re-enabling it.
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(
                return_value=[_workflow("wf-1", activated=False)]
            )
            service.activate_workflow = AsyncMock()

            reactivated = await reactivate_workflows_for_restored_subscription(USER_ID)

        assert reactivated == 1
        repo.find_paused_for_reason.assert_awaited_once_with(
            USER_ID, DeactivationReason.SUBSCRIPTION_LAPSED
        )
        service.activate_workflow.assert_awaited_once_with("wf-1", USER_ID)

    async def test_no_lapsed_workflows_is_a_no_op(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[])
            service.activate_workflow = AsyncMock()

            assert await reactivate_workflows_for_restored_subscription(USER_ID) == 0
            service.activate_workflow.assert_not_awaited()

    async def test_the_count_accumulates_across_multiple_successes(self) -> None:
        """Two workflows reactivated in one sweep must return 2, not a flag
        reset to 1 on each success — the count feeds the summary log and is
        exactly the kind of bug an increment-vs-assign typo introduces
        silently (mirrors ``reactivated += 1`` vs ``reactivated = 1``)."""
        first = _workflow("wf-1", activated=False)
        second = _workflow("wf-2", activated=False)

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[first, second])
            service.activate_workflow = AsyncMock()

            reactivated = await reactivate_workflows_for_restored_subscription(USER_ID)

        assert reactivated == 2

    async def test_one_failure_does_not_abort_the_rest(self) -> None:
        first = _workflow("wf-1", activated=False)
        second = _workflow("wf-2", activated=False)

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[first, second])
            service.activate_workflow = AsyncMock(
                side_effect=[RuntimeError("integration since expired"), None]
            )

            reactivated = await reactivate_workflows_for_restored_subscription(USER_ID)

        # A half-applied reactivation beats none: the second workflow still resumed.
        assert reactivated == 1

    async def test_it_never_reactivates_behind_the_service_and_strands_a_composio_trigger(
        self,
    ) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(
                return_value=[_workflow("wf-1", activated=False)]
            )
            service.activate_workflow = AsyncMock()

            await reactivate_workflows_for_restored_subscription(USER_ID)

        service.activate_workflow.assert_awaited_once_with("wf-1", USER_ID)
        repo.activate.assert_not_called()

    async def test_the_skip_warning_carries_the_workflow_user_and_cause(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_paused_for_reason = AsyncMock(
                return_value=[_workflow("wf-1", activated=False)]
            )
            service.activate_workflow = AsyncMock(
                side_effect=RuntimeError("integration since expired")
            )

            await reactivate_workflows_for_restored_subscription(USER_ID)

        mock_log.warning.assert_called_once()
        message, kwargs = mock_log.warning.call_args.args[0], mock_log.warning.call_args.kwargs
        assert message == "[WORKFLOW] Could not reactivate workflow for restored subscription"
        assert kwargs == {
            "workflow_id": "wf-1",
            "user_id": USER_ID,
            "error": "integration since expired",
            "error_type": "RuntimeError",
        }

    async def test_the_summary_log_fires_only_when_something_was_reactivated(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_paused_for_reason = AsyncMock(
                return_value=[_workflow("wf-1", activated=False)]
            )
            service.activate_workflow = AsyncMock()

            await reactivate_workflows_for_restored_subscription(USER_ID)

        mock_log.info.assert_called_once()
        message, kwargs = mock_log.info.call_args.args[0], mock_log.info.call_args.kwargs
        assert message == "[WORKFLOW] Reactivated workflows for restored subscription"
        assert kwargs == {"user_id": USER_ID, "reactivated": 1}

    async def test_the_summary_log_is_silent_on_a_no_op_run(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[])
            service.activate_workflow = AsyncMock()

            await reactivate_workflows_for_restored_subscription(USER_ID)

        mock_log.info.assert_not_called()

    async def test_scopes_to_the_given_user_only(self) -> None:
        """Reactivating another user's workflows would be a real data-safety bug."""

        async def _paused(user_id: str, reason: DeactivationReason) -> list[MagicMock]:
            assert reason == DeactivationReason.SUBSCRIPTION_LAPSED
            return (
                [_workflow("wf-mine", activated=False)]
                if user_id == USER_ID
                else [_workflow("wf-other", activated=False)]
            )

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(side_effect=_paused)
            service.activate_workflow = AsyncMock()

            await reactivate_workflows_for_restored_subscription(USER_ID)

        service.activate_workflow.assert_awaited_once_with("wf-mine", USER_ID)

    async def test_rerunning_after_success_reactivates_nothing_again(self) -> None:
        """Idempotency: once resumed, the workflow no longer carries the lapsed
        reason, so a second sweep for the same user finds nothing left."""
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(
                return_value=[_workflow("wf-1", activated=False)]
            )
            service.activate_workflow = AsyncMock()
            first_run = await reactivate_workflows_for_restored_subscription(USER_ID)

            repo.find_paused_for_reason = AsyncMock(return_value=[])
            second_run = await reactivate_workflows_for_restored_subscription(USER_ID)

        assert first_run == 1
        assert second_run == 0
        service.activate_workflow.assert_awaited_once()
