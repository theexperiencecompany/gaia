"""Unit tests for app/services/system_workflows/provisioner.py.

Covers:
- provision_system_workflows: no entries, idempotent skip (incl. loop continuation),
  success, notify=False, timezone stamping (set/blank/missing user tz, preserved tz,
  single fetch), DuplicateKeyError, generic error, multi-entry error continuation,
  exact args to find_system_workflow / create_workflow / _notify_workflows_provisioned,
  exact wide-event log fields
- _notify_workflows_provisioned: exact NotificationRequest payload for single vs
  multiple workflows (title, body, actions, metadata, priority), notification failure
- reset_system_workflow_to_default: not found, no registry key (incl. key=None),
  success with exact trigger registration/unregistration/reset args, registration
  failure, empty registration result, unregister failure (non-fatal), manual/schedule/
  integration-without-name skips, description/steps None -> "" / []
"""

from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import DuplicateKeyError
import pytest

from app.constants.log_tags import LogTag
from app.models.notification.notification_models import (
    ActionStyle,
    ActionType,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    WorkflowStep,
)
import app.services.system_workflows.provisioner as provisioner_module
from app.services.system_workflows.provisioner import (
    _notify_workflows_provisioned,
    provision_system_workflows,
    reset_system_workflow_to_default,
)

MODULE = "app.services.system_workflows.provisioner"


def _make_workflow_request(
    title: str = "Test Workflow",
    description: str = "A test workflow",
    *,
    trigger_type: TriggerType = TriggerType.MANUAL,
    trigger_name: str | None = None,
    timezone: str | None = None,
    steps: list[WorkflowStep] | None = None,
) -> CreateWorkflowRequest:
    """Build a real CreateWorkflowRequest with a real TriggerConfig."""
    return CreateWorkflowRequest(
        title=title,
        description=description,
        prompt="do something",
        trigger_config=TriggerConfig(
            type=trigger_type,
            trigger_name=trigger_name,
            timezone=timezone,
        ),
        steps=steps,
    )


def _make_factory(request: CreateWorkflowRequest | None = None) -> MagicMock:
    if request is None:
        request = _make_workflow_request()
    factory = MagicMock(return_value=request)
    return factory


def _existing_wf(
    key: str = "gmail_digest",
    composio_trigger_ids: list[str] | None = None,
    trigger_name: str | None = "gmail_new_email",
) -> MagicMock:
    """A stand-in WorkflowDocument as get_system_workflow_for_user returns it."""
    wf = MagicMock()
    wf.system_workflow_key = key
    wf.trigger_config = MagicMock()
    wf.trigger_config.composio_trigger_ids = composio_trigger_ids
    wf.trigger_config.trigger_name = trigger_name
    return wf


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestProvisionSystemWorkflows:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION", {})
    async def test_no_entries_for_integration(self) -> None:
        # Should return without error, logging the wide-event context + debug line
        await provision_system_workflows("user-1", "slack", "Slack")

        provisioner_module.log.set.assert_called_once_with(
            component="system_workflow_provisioner",
            operation="provision_system_workflows",
            user_id="user-1",
            integration_id="slack",
            integration_display_name="Slack",
        )
        provisioner_module.log.debug.assert_called_once_with(
            f"{LogTag.WORKFLOW} No system workflows defined for integration",
            integration_id="slack",
        )
        provisioner_module.log.info.assert_not_called()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.WorkflowService")
    async def test_idempotent_skip_existing(
        self,
        mock_workflow_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value={"_id": "existing"})
        factory = _make_factory()

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_repo.find_system_workflow.assert_awaited_once_with("user-1", "gmail_digest")
        mock_workflow_svc.create_workflow.assert_not_called()
        factory.assert_not_called()

        provisioner_module.log.info.assert_any_call(
            f"{LogTag.WORKFLOW} System workflow already exists, skipping",
            key="gmail_digest",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.WorkflowService")
    async def test_first_skipped_then_second_provisioned(
        self,
        mock_workflow_svc: MagicMock,
        mock_repo: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        """The idempotency skip must continue the loop, not stop it."""
        mock_repo.find_system_workflow = AsyncMock(side_effect=[{"_id": "existing"}, None])
        mock_workflow_svc.create_workflow = AsyncMock()
        req2 = _make_workflow_request("Second", "second wf")
        factory1 = _make_factory()
        factory2 = _make_factory(req2)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("key1", factory1), ("key2", factory2)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_workflow_svc.create_workflow.assert_awaited_once_with(req2, "user-1")
        mock_notify.assert_awaited_once_with("user-1", "Gmail", [req2])
        factory1.assert_not_called()

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_successful_provisioning(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        req = _make_workflow_request()
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_repo.find_system_workflow.assert_awaited_once_with("user-1", "gmail_digest")
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")
        mock_notify.assert_awaited_once_with("user-1", "Gmail", [req])

        provisioner_module.log.set.assert_called_once_with(
            component="system_workflow_provisioner",
            operation="provision_system_workflows",
            user_id="user-1",
            integration_id="gmail",
            integration_display_name="Gmail",
        )
        provisioner_module.log.info.assert_any_call(
            f"{LogTag.WORKFLOW} Provisioning system workflow(s)",
            entries_count=1,
            user_id="user-1",
            integration_id="gmail",
        )
        provisioner_module.log.info.assert_any_call(
            f"{LogTag.WORKFLOW} Provisioned system workflow for user",
            key="gmail_digest",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_notify_false_suppresses_notification(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        """During onboarding (notify=False) provisioning is silent."""
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        factory = _make_factory()

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail", notify=False)

        mock_workflow_svc.create_workflow.assert_awaited_once()
        mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_schedule_trigger_stamps_user_timezone(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "  America/New_York  "}
        req = _make_workflow_request(trigger_type=TriggerType.SCHEDULE)
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_get_user.assert_awaited_once_with("user-1")
        assert req.trigger_config.timezone == "America/New_York"
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")
        mock_notify.assert_awaited_once_with("user-1", "Gmail", [req])

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_schedule_trigger_defaults_to_utc_when_user_tz_blank(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "   "}
        req = _make_workflow_request(trigger_type=TriggerType.SCHEDULE)
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        assert req.trigger_config.timezone == "UTC"
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_schedule_trigger_defaults_to_utc_when_user_missing(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = None
        req = _make_workflow_request(trigger_type=TriggerType.SCHEDULE)
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        assert req.trigger_config.timezone == "UTC"
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_schedule_trigger_preserves_existing_timezone(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        """A timezone already on the definition is authoritative — no user fetch."""
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        req = _make_workflow_request(trigger_type=TriggerType.SCHEDULE, timezone="Europe/London")
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_get_user.assert_not_awaited()
        assert req.trigger_config.timezone == "Europe/London"
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_non_schedule_trigger_never_fetches_user(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        req = _make_workflow_request(trigger_type=TriggerType.INTEGRATION, trigger_name="x")
        factory = _make_factory(req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_get_user.assert_not_awaited()
        assert req.trigger_config.timezone is None
        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.get_user_by_id")
    async def test_user_timezone_fetched_once_for_multiple_schedules(
        self,
        mock_get_user: AsyncMock,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "Asia/Kolkata"}
        req1 = _make_workflow_request("One", "first", trigger_type=TriggerType.SCHEDULE)
        req2 = _make_workflow_request("Two", "second", trigger_type=TriggerType.SCHEDULE)
        factory1 = _make_factory(req1)
        factory2 = _make_factory(req2)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("key1", factory1), ("key2", factory2)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_get_user.assert_awaited_once_with("user-1")
        assert req1.trigger_config.timezone == "Asia/Kolkata"
        assert req2.trigger_config.timezone == "Asia/Kolkata"

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_duplicate_key_error_skipped(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(side_effect=DuplicateKeyError("dup"))
        factory = _make_factory()

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        # No notification because nothing was created
        mock_notify.assert_not_awaited()

        provisioner_module.log.info.assert_any_call(
            f"{LogTag.WORKFLOW} System workflow already exists for user (concurrent creation), skipping",
            key="gmail_digest",
            user_id="user-1",
        )
        provisioner_module.log.error.assert_not_called()

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_generic_error_continues(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(side_effect=RuntimeError("unexpected"))
        factory = _make_factory()

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            # Should not raise
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_notify.assert_not_awaited()

        provisioner_module.log.error.assert_called_once_with(
            "system_workflow_provision_failed",
            system_workflow_key="gmail_digest",
            user_id="user-1",
            integration_display_name="Gmail",
            error_type="RuntimeError",
            error="unexpected",
            outcome="failed",
            exc_info=True,
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_generic_error_truncates_long_message(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        """The logged error is truncated to 500 chars to bound the log size."""
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(
            side_effect=RuntimeError("x" * 600)
        )
        factory = _make_factory()

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("gmail_digest", factory)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_notify.assert_not_awaited()

        provisioner_module.log.error.assert_called_once_with(
            "system_workflow_provision_failed",
            system_workflow_key="gmail_digest",
            user_id="user-1",
            integration_display_name="Gmail",
            error_type="RuntimeError",
            error="x" * 500,
            outcome="failed",
            exc_info=True,
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}._notify_workflows_provisioned", new_callable=AsyncMock)
    @patch(f"{MODULE}.WorkflowService")
    @patch(f"{MODULE}.workflow_repository")
    async def test_second_entry_provisioned_after_generic_error(
        self,
        mock_repo: MagicMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        """A failed entry is logged and skipped; later entries still provision."""
        mock_repo.find_system_workflow = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(
            side_effect=[RuntimeError("boom"), None]
        )
        factory1 = _make_factory()
        factory2 = _make_factory(_make_workflow_request("Second", "second wf"))

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION",
            {"gmail": [("key1", factory1), ("key2", factory2)]},
        ):
            await provision_system_workflows("user-1", "gmail", "Gmail")

        assert mock_workflow_svc.create_workflow.await_count == 2
        # Only the successfully created workflow is notified
        mock_notify.assert_awaited_once()
        notified = mock_notify.call_args[0][2]
        assert len(notified) == 1
        assert notified[0].title == "Second"

        provisioner_module.log.error.assert_called_once_with(
            "system_workflow_provision_failed",
            system_workflow_key="key1",
            user_id="user-1",
            integration_display_name="Gmail",
            error_type="RuntimeError",
            error="boom",
            outcome="failed",
            exc_info=True,
        )


class TestNotifyWorkflowsProvisioned:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_single_workflow_payload(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_notif_cls.return_value = mock_svc

        req = _make_workflow_request("Email Digest", "Daily digest of important emails")
        await _notify_workflows_provisioned("user-1", "Gmail", [req])

        mock_svc.create_notification.assert_awaited_once()
        notification: NotificationRequest = mock_svc.create_notification.call_args[0][0]
        assert isinstance(notification, NotificationRequest)
        assert notification.user_id == "user-1"
        assert notification.source == NotificationSourceEnum.SYSTEM_WORKFLOWS_PROVISIONED
        assert notification.type == NotificationType.SUCCESS
        assert notification.priority == 2
        assert notification.metadata == {"integration_display_name": "Gmail"}
        assert notification.content.title == "I set up a workflow for your Gmail"
        assert (
            notification.content.body
            == "Here's what I've got running for you:\n\n"
            "• Email Digest — Daily digest of important emails\n\n"
            "You can adjust or turn them off anytime."
        )
        assert len(notification.content.actions) == 1
        action = notification.content.actions[0]
        assert action.type == ActionType.REDIRECT
        assert action.label == "View Workflows"
        assert action.style == ActionStyle.PRIMARY
        assert action.config.api_call is None
        assert action.config.modal is None
        assert action.config.redirect == RedirectConfig(
            url="/workflows", open_in_new_tab=False, close_notification=True
        )

        provisioner_module.log.info.assert_called_once_with(
            f"{LogTag.WORKFLOW} Sent system workflow provisioning notification to user for integration",
            user_id="user-1",
            integration_display_name="Gmail",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_multiple_workflows_payload(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_notif_cls.return_value = mock_svc

        req1 = _make_workflow_request("Digest", "desc1")
        req2 = _make_workflow_request("Sorter", "desc2")
        await _notify_workflows_provisioned("user-1", "Gmail", [req1, req2])

        notification: NotificationRequest = mock_svc.create_notification.call_args[0][0]
        assert notification.content.title == "I set up 2 workflows for your Gmail"
        assert (
            notification.content.body
            == "Here's what I've got running for you:\n\n"
            "• Digest — desc1\n"
            "• Sorter — desc2\n\n"
            "You can adjust or turn them off anytime."
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_notification_failure_does_not_raise(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_svc.create_notification = AsyncMock(side_effect=RuntimeError("notify fail"))
        mock_notif_cls.return_value = mock_svc

        # Should not raise
        await _notify_workflows_provisioned("user-1", "Gmail", [_make_workflow_request()])

        provisioner_module.log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Failed to send provisioning notification for user",
            user_id="user-1",
            error="notify fail",
            error_type="RuntimeError",
            exc_info=True,
        )


class TestResetSystemWorkflowToDefault:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    async def test_workflow_not_found(self, mock_repo: MagicMock) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=None)

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

        mock_repo.get_system_workflow_for_user.assert_awaited_once_with("wf-1", "user-1")

        provisioner_module.log.set.assert_called_once_with(
            component="system_workflow_provisioner",
            operation="reset_system_workflow_to_default",
            user_id="user-1",
            workflow_id="wf-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {})
    async def test_no_registry_entry(self, mock_repo: MagicMock) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(
                key="unknown_key", composio_trigger_ids=None, trigger_name=None
            )
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

        provisioner_module.log.warning.assert_called_once_with(
            f"{LogTag.WORKFLOW} No definition found for system_workflow_key on workflow",
            key="unknown_key",
            workflow_id="wf-1",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {})
    async def test_missing_key_has_no_factory(self, mock_repo: MagicMock) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(
                key=None, composio_trigger_ids=None, trigger_name=None
            )
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

        provisioner_module.log.warning.assert_called_once_with(
            f"{LogTag.WORKFLOW} No definition found for system_workflow_key on workflow",
            key=None,
            workflow_id="wf-1",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_successful_reset_with_triggers(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock()

        step = WorkflowStep(title="Step 1", description="Do the thing")
        req = _make_workflow_request(
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_email",
            steps=[step],
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_awaited_once_with(
            user_id="user-1",
            workflow_id="wf-1",
            trigger_name="gmail_new_email",
            trigger_config=req.trigger_config,
            raise_on_failure=False,
        )
        mock_trigger_svc.unregister_triggers.assert_awaited_once_with(
            user_id="user-1",
            trigger_name="gmail_new_email",
            trigger_ids=["old-t1"],
            workflow_id="wf-1",
        )
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="A test workflow",
            steps=[step],
            trigger_config=req.trigger_config,
            composio_trigger_ids=["new-t1"],
        )

        provisioner_module.log.info.assert_called_once_with(
            f"{LogTag.WORKFLOW} Reset system workflow to default for user",
            key="gmail_digest",
            workflow_id="wf-1",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_reset_with_none_description_and_steps(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=None)
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])

        req = _make_workflow_request(
            description=None,
            trigger_type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_email",
            steps=None,
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="",
            steps=[],
            trigger_config=req.trigger_config,
            composio_trigger_ids=["new-t1"],
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_integration_trigger_without_name_skips_registration(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        """An integration definition without a trigger name cannot register."""
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock()
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(trigger_type=TriggerType.INTEGRATION, trigger_name=None)
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_not_awaited()
        # Old triggers are still unregistered under the existing trigger name
        mock_trigger_svc.unregister_triggers.assert_awaited_once_with(
            user_id="user-1",
            trigger_name="gmail_new_email",
            trigger_ids=["old-t1"],
            workflow_id="wf-1",
        )
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="A test workflow",
            steps=[],
            trigger_config=req.trigger_config,
            composio_trigger_ids=[],
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_schedule_trigger_skips_registration(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock()
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(trigger_type=TriggerType.SCHEDULE)
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_not_awaited()
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="A test workflow",
            steps=[],
            trigger_config=req.trigger_config,
            composio_trigger_ids=[],
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_unregister_skipped_when_no_old_trigger_ids(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=[])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(
            trigger_type=TriggerType.INTEGRATION, trigger_name="gmail_new_email"
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_awaited_once()
        mock_trigger_svc.unregister_triggers.assert_not_awaited()
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="A test workflow",
            steps=[],
            trigger_config=req.trigger_config,
            composio_trigger_ids=["new-t1"],
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_trigger_registration_failure_aborts(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=[])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(side_effect=RuntimeError("fail"))
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(
            trigger_type=TriggerType.INTEGRATION, trigger_name="gmail_new_email"
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False
        mock_trigger_svc.register_triggers.assert_awaited_once()
        mock_trigger_svc.unregister_triggers.assert_not_awaited()
        mock_repo.reset_system_workflow.assert_not_awaited()

        provisioner_module.log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Failed to re-register triggers, aborting reset of",
            workflow_id="wf-1",
            error="fail",
            error_type="RuntimeError",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_empty_trigger_registration_aborts(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=[], trigger_name="t")
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(return_value=[])
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(
            trigger_type=TriggerType.INTEGRATION, trigger_name="gmail_new_email"
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False
        mock_trigger_svc.unregister_triggers.assert_not_awaited()
        mock_repo.reset_system_workflow.assert_not_awaited()

        provisioner_module.log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} New trigger registration returned an empty result, aborting reset to avoid leaving the workflow without triggers",
            workflow_id="wf-1",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_old_trigger_unregister_failure_nonfatal(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock(
            side_effect=RuntimeError("unregister fail")
        )

        req = _make_workflow_request(
            trigger_type=TriggerType.INTEGRATION, trigger_name="gmail_new_email"
        )
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        # Unregister failure is non-fatal — reset should still succeed
        assert result is True
        mock_repo.reset_system_workflow.assert_awaited_once()

        provisioner_module.log.warning.assert_called_once_with(
            f"{LogTag.WORKFLOW} Failed to unregister old triggers during reset of (non-fatal)",
            workflow_id="wf-1",
            error="unregister fail",
            error_type="RuntimeError",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    async def test_manual_trigger_no_registration(
        self,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        """Manual trigger workflows skip trigger registration entirely."""
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(key="manual_wf", composio_trigger_ids=None, trigger_name=None)
        )
        mock_repo.reset_system_workflow = AsyncMock()
        mock_trigger_svc.register_triggers = AsyncMock()
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(trigger_type=TriggerType.MANUAL)
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"manual_wf": factory}):
            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_not_awaited()
        mock_trigger_svc.unregister_triggers.assert_not_awaited()
        mock_repo.reset_system_workflow.assert_awaited_once_with(
            "wf-1",
            title="Test Workflow",
            description="A test workflow",
            steps=[],
            trigger_config=req.trigger_config,
            composio_trigger_ids=[],
        )
