"""Pausing a user's workflows when an integration dies, and resuming on reconnect.

An activated workflow whose integration is dead keeps firing on schedule and
delivers a failed run, which reads to the user as "GAIA is broken" rather than
"Gmail needs reconnecting". Both halves go through ``WorkflowService`` so the
workflow's Composio trigger follows the workflow's state upstream.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow_models import DeactivationReason
from app.services.workflow.integration_pause import (
    pause_workflows_for_expired_integration,
    resume_workflows_for_reconnected_integration,
)

MODULE = "app.services.workflow.integration_pause"

USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture(autouse=True)
def subscription_side():
    """Todo subscriptions ride along on both halves; most tests only care about
    workflows, so the calls are stubbed here and asserted in TestSubscriptions."""
    with (
        patch(f"{MODULE}.pause_subscriptions_for_trigger_names", new_callable=AsyncMock) as pause,
        patch(f"{MODULE}.resync_subscriptions_for_trigger_names", new_callable=AsyncMock) as resync,
    ):
        yield MagicMock(pause=pause, resync=resync)


def _workflow(workflow_id: str, title: str, *, activated: bool = True) -> MagicMock:
    w = MagicMock()
    w.id = workflow_id
    w.title = title
    w.activated = activated
    return w


class TestPause:
    async def test_it_pauses_only_the_workflows_that_need_the_dead_integration(self) -> None:
        gmail_wf = _workflow("wf-1", "Morning digest")
        notion_wf = _workflow("wf-2", "Notes sync")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations") as required,
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[gmail_wf, notion_wf])
            service.deactivate_workflow = AsyncMock()
            required.side_effect = lambda steps, trigger: (
                {"gmail"} if steps is gmail_wf.steps else {"notion"}
            )

            paused = await pause_workflows_for_expired_integration(USER_ID, "gmail")

        assert paused == ["Morning digest"]
        service.deactivate_workflow.assert_awaited_once_with(
            "wf-1", USER_ID, reason=DeactivationReason.INTEGRATION_EXPIRED
        )

    async def test_one_failure_does_not_abort_the_rest(self) -> None:
        first = _workflow("wf-1", "First")
        second = _workflow("wf-2", "Second")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[first, second])
            service.deactivate_workflow = AsyncMock(
                side_effect=[RuntimeError("composio down"), None]
            )

            paused = await pause_workflows_for_expired_integration(USER_ID, "gmail")

        # A half-applied expiry beats none: the second workflow still stopped.
        assert paused == ["Second"]

    async def test_a_second_expiry_event_does_not_re_pause_or_re_count_a_workflow(self) -> None:
        # Composio can send several dead-status events for one account. The
        # returned titles drive the notification copy ("2 workflows are paused"),
        # so a workflow the first event already stopped must not be counted
        # again — the activated-only query is what keeps that true.
        owned = [
            _workflow("wf-1", "Morning digest"),
            _workflow("wf-2", "Invoice filing", activated=False),
        ]

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[w for w in owned if w.activated])
            service.deactivate_workflow = AsyncMock()

            paused = await pause_workflows_for_expired_integration(USER_ID, "gmail")

        assert paused == ["Morning digest"]
        service.deactivate_workflow.assert_awaited_once_with(
            "wf-1", USER_ID, reason=DeactivationReason.INTEGRATION_EXPIRED
        )

    async def test_it_never_deactivates_behind_the_service_and_strands_a_composio_trigger(
        self,
    ) -> None:
        # Writing `activated=False` straight through the repository leaves the
        # workflow's Composio trigger enabled upstream; only
        # WorkflowService.deactivate_workflow unregisters it (its own tests cover
        # that). So the seam itself is the behaviour worth pinning here.
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.deactivate_workflow = AsyncMock()

            await pause_workflows_for_expired_integration(USER_ID, "gmail")

        service.deactivate_workflow.assert_awaited_once_with(
            "wf-1", USER_ID, reason=DeactivationReason.INTEGRATION_EXPIRED
        )
        repo.deactivate.assert_not_called()

    async def test_nothing_to_pause_is_not_an_error(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"notion"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1", "Other")])
            service.deactivate_workflow = AsyncMock()

            assert await pause_workflows_for_expired_integration(USER_ID, "gmail") == []
            service.deactivate_workflow.assert_not_awaited()


class TestResume:
    async def test_it_only_resumes_workflows_this_feature_paused(self) -> None:
        # A workflow the user switched off records no reason, so the reason filter
        # is what stops a reconnect silently re-enabling it.
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.activate_workflow = AsyncMock()

            resumed = await resume_workflows_for_reconnected_integration(USER_ID, "gmail")

        assert resumed == 1
        repo.find_paused_for_reason.assert_awaited_once_with(
            USER_ID, DeactivationReason.INTEGRATION_EXPIRED
        )
        service.activate_workflow.assert_awaited_once_with("wf-1", USER_ID)

    async def test_a_workflow_still_missing_another_integration_stays_paused(self) -> None:
        # activate_workflow refuses while any required integration is missing, so
        # reconnecting Gmail must not re-arm a workflow that also needs Notion.
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail", "notion"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.activate_workflow = AsyncMock(
                side_effect=ValueError("Connect Notion to enable this workflow.")
            )

            resumed = await resume_workflows_for_reconnected_integration(USER_ID, "gmail")

        assert resumed == 0

    async def test_it_ignores_workflows_that_do_not_need_this_integration(self) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"notion"}),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[_workflow("wf-1", "Notes")])
            service.activate_workflow = AsyncMock()

            assert await resume_workflows_for_reconnected_integration(USER_ID, "gmail") == 0
            service.activate_workflow.assert_not_awaited()


class TestScanUsesItsArguments:
    """The tests above answer from fixed return values, which cannot tell a
    correct argument from a nulled or dropped one — every argument-passing
    mutation in both functions survived them. These fakes answer from what they
    are handed, so a wrong argument changes the outcome instead of going
    unnoticed."""

    @staticmethod
    def _requirements_of(*owners: MagicMock):
        """``compute_required_integrations`` keyed on BOTH arguments of one workflow."""

        def _required(steps: object, trigger_config: object) -> set[str]:
            for owner in owners:
                if steps is owner.steps and trigger_config is owner.trigger_config:
                    return {"gmail"}
            return set()

        return _required

    async def test_pause_scans_the_workflows_of_the_user_being_expired(self) -> None:
        """Scanning another user's workflows would pause a stranger's automations."""
        mine = _workflow("wf-1", "Morning digest")

        async def _activated(user_id: str) -> list[MagicMock]:
            return [mine] if user_id == USER_ID else []

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", self._requirements_of(mine)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(side_effect=_activated)
            service.deactivate_workflow = AsyncMock()

            assert await pause_workflows_for_expired_integration(USER_ID, "gmail") == [
                "Morning digest"
            ]

    async def test_pause_keeps_scanning_past_a_workflow_that_does_not_need_it(self) -> None:
        """The unrelated workflow is FIRST: a loop that breaks instead of continuing
        would leave the one that actually needs Gmail running on a dead account."""
        unrelated = _workflow("wf-1", "Notes sync")
        needs_gmail = _workflow("wf-2", "Morning digest")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", self._requirements_of(needs_gmail)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[unrelated, needs_gmail])
            service.deactivate_workflow = AsyncMock()

            assert await pause_workflows_for_expired_integration(USER_ID, "gmail") == [
                "Morning digest"
            ]

    async def test_the_skip_warning_carries_the_workflow_user_integration_and_cause(self) -> None:
        """This warning is the only trace a workflow was left running on a dead
        integration — stripped of its ids it cannot be acted on."""
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value={"gmail"}),
            patch(f"{MODULE}.WorkflowService") as service,
            patch(f"{MODULE}.log") as mock_log,
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[_workflow("wf-1", "Digest")])
            service.deactivate_workflow = AsyncMock(side_effect=RuntimeError("composio down"))

            await pause_workflows_for_expired_integration(USER_ID, "gmail")

        mock_log.warning.assert_called_once()
        message, kwargs = mock_log.warning.call_args.args[0], mock_log.warning.call_args.kwargs
        assert "Could not pause workflow" in message
        assert kwargs == {
            "workflow_id": "wf-1",
            "user_id": USER_ID,
            "integration_id": "gmail",
            "error": "composio down",
            "error_type": "RuntimeError",
        }

    async def test_resume_reads_requirements_from_this_workflow_not_another(self) -> None:
        needs_gmail = _workflow("wf-1", "Digest")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", self._requirements_of(needs_gmail)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[needs_gmail])
            service.activate_workflow = AsyncMock()

            assert await resume_workflows_for_reconnected_integration(USER_ID, "gmail") == 1

    async def test_resume_keeps_scanning_past_a_workflow_that_does_not_need_it(self) -> None:
        unrelated = _workflow("wf-1", "Notes sync")
        needs_gmail = _workflow("wf-2", "Digest")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", self._requirements_of(needs_gmail)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[unrelated, needs_gmail])
            service.activate_workflow = AsyncMock()

            assert await resume_workflows_for_reconnected_integration(USER_ID, "gmail") == 1

    async def test_resume_counts_every_workflow_it_brings_back(self) -> None:
        """A count that assigns instead of accumulating reports "1 workflow
        resumed" no matter how many actually came back."""
        first = _workflow("wf-1", "Digest")
        second = _workflow("wf-2", "Invoices")

        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", self._requirements_of(first, second)),
            patch(f"{MODULE}.WorkflowService") as service,
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[first, second])
            service.activate_workflow = AsyncMock()

            assert await resume_workflows_for_reconnected_integration(USER_ID, "gmail") == 2


class TestSubscriptions:
    """A todo subscription on a dead integration is as broken as a workflow, and
    less visible — nothing about the todo shows the watch has stopped working."""

    @staticmethod
    def _lookup_only(expected_id: str, slug: str):
        """``get_integration_by_id`` that answers from its argument: the
        trigger-bearing integration only for ``expected_id``, ``None`` for
        anything else. A lookup keyed on the wrong id (or a nulled one) resolves
        no triggers, so the subscription call changes instead of going unnoticed."""

        def _get(integration_id: str) -> MagicMock | None:
            if integration_id != expected_id:
                return None
            return MagicMock(
                associated_triggers=[MagicMock(workflow_trigger_schema=MagicMock(slug=slug))]
            )

        return _get

    async def test_expiry_pauses_the_integrations_todo_subscriptions(
        self, subscription_side
    ) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value=set()),
            patch(f"{MODULE}.WorkflowService"),
            patch(
                f"{MODULE}.get_integration_by_id",
                side_effect=self._lookup_only("gmail", "gmail_new_message"),
            ),
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[])

            await pause_workflows_for_expired_integration(USER_ID, "gmail")

        subscription_side.pause.assert_awaited_once_with(USER_ID, {"gmail_new_message"})

    async def test_reconnect_resyncs_the_integrations_todo_subscriptions(
        self, subscription_side
    ) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value=set()),
            patch(f"{MODULE}.WorkflowService"),
            patch(
                f"{MODULE}.get_integration_by_id",
                side_effect=self._lookup_only("gmail", "gmail_new_message"),
            ),
        ):
            repo.find_paused_for_reason = AsyncMock(return_value=[])

            await resume_workflows_for_reconnected_integration(USER_ID, "gmail")

        subscription_side.resync.assert_awaited_once_with(USER_ID, {"gmail_new_message"})

    async def test_an_unknown_integration_touches_no_subscriptions(self, subscription_side) -> None:
        with (
            patch(f"{MODULE}.workflow_repository") as repo,
            patch(f"{MODULE}.compute_required_integrations", return_value=set()),
            patch(f"{MODULE}.WorkflowService"),
            patch(f"{MODULE}.get_integration_by_id", return_value=None),
        ):
            repo.find_activated_for_user = AsyncMock(return_value=[])

            await pause_workflows_for_expired_integration(USER_ID, "nope")

        subscription_side.pause.assert_awaited_once_with(USER_ID, set())
