"""Unit tests for app/services/system_workflows/provisioner.py.

Covers:
- provision_system_workflows: no entries, idempotent skip, success, DuplicateKeyError, generic error
- _notify_workflows_provisioned: single vs multiple workflows, notification failure
- reset_system_workflow_to_default: not found, no registry key, success with trigger re-registration,
  trigger registration failure, old trigger unregister failure (non-fatal)
"""

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

from pymongo.errors import DuplicateKeyError
import pytest

MODULE = "app.services.system_workflows.provisioner"


def _make_workflow_request(
    title: str = "Test Workflow",
    description: str = "A test workflow",
) -> MagicMock:
    """Build a mock CreateWorkflowRequest."""
    req = MagicMock()
    req.title = title
    req.description = description
    req.prompt = "do something"
    req.steps = []
    req.trigger_config = MagicMock()
    return req


def _make_factory(request: MagicMock | None = None) -> MagicMock:
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
    with patch(f"{MODULE}.log") as mock_log:
        yield mock_log


class TestProvisionSystemWorkflows:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION", {})
    async def test_no_entries_for_integration(self) -> None:
        from app.services.system_workflows.provisioner import provision_system_workflows

        # Should return without error
        await provision_system_workflows("user-1", "slack", "Slack")

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
            from app.services.system_workflows.provisioner import (
                provision_system_workflows,
            )

            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_workflow_svc.create_workflow.assert_not_called()
        factory.assert_not_called()

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
            from app.services.system_workflows.provisioner import (
                provision_system_workflows,
            )

            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_workflow_svc.create_workflow.assert_awaited_once_with(req, "user-1")
        mock_notify.assert_awaited_once()

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
            from app.services.system_workflows.provisioner import (
                provision_system_workflows,
            )

            await provision_system_workflows("user-1", "gmail", "Gmail")

        # No notification because nothing was created
        mock_notify.assert_not_awaited()

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
            from app.services.system_workflows.provisioner import (
                provision_system_workflows,
            )

            # Should not raise
            await provision_system_workflows("user-1", "gmail", "Gmail")

        mock_notify.assert_not_awaited()


class TestNotifyWorkflowsProvisioned:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_single_workflow_title(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_notif_cls.return_value = mock_svc

        from app.services.system_workflows.provisioner import (
            _notify_workflows_provisioned,
        )

        req = _make_workflow_request("Email Digest", "Daily digest of important emails")
        await _notify_workflows_provisioned("user-1", "Gmail", [req])

        mock_svc.create_notification.assert_awaited_once()
        call_args = mock_svc.create_notification.call_args
        notification = call_args[0][0]
        assert "I set up a workflow" in notification.content.title
        assert "Gmail" in notification.content.title

    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_multiple_workflows_title(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_notif_cls.return_value = mock_svc

        from app.services.system_workflows.provisioner import (
            _notify_workflows_provisioned,
        )

        req1 = _make_workflow_request("Digest", "desc1")
        req2 = _make_workflow_request("Sorter", "desc2")
        await _notify_workflows_provisioned("user-1", "Gmail", [req1, req2])

        notification = mock_svc.create_notification.call_args[0][0]
        assert "2 workflows" in notification.content.title

    @pytest.mark.asyncio
    @patch(f"{MODULE}.NotificationService")
    async def test_notification_failure_does_not_raise(self, mock_notif_cls: MagicMock) -> None:
        mock_svc = AsyncMock()
        mock_svc.create_notification = AsyncMock(side_effect=RuntimeError("notify fail"))
        mock_notif_cls.return_value = mock_svc

        from app.services.system_workflows.provisioner import (
            _notify_workflows_provisioned,
        )

        # Should not raise
        await _notify_workflows_provisioned("user-1", "Gmail", [_make_workflow_request()])


class TestResetSystemWorkflowToDefault:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    async def test_workflow_not_found(self, mock_repo: MagicMock) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=None)

        from app.services.system_workflows.provisioner import (
            reset_system_workflow_to_default,
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {})
    async def test_no_registry_entry(self, mock_repo: MagicMock) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(
                key="unknown_key", composio_trigger_ids=None, trigger_name=None
            )
        )

        from app.services.system_workflows.provisioner import (
            reset_system_workflow_to_default,
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_successful_reset_with_triggers(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        # Existing workflow doc
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()

        # Mock trigger config object
        trigger_config = MagicMock()
        trigger_config.trigger_name = "gmail_new_email"
        trigger_config.model_dump.return_value = {
            "type": "integration",
            "trigger_name": "gmail_new_email",
        }
        mock_ensure.return_value = trigger_config

        from app.models.workflow_models import TriggerType

        trigger_config.type = TriggerType.INTEGRATION

        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request()
        req.steps = ["step-1"]
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True

        # The workflow id and user id must flow through to both trigger calls.
        assert mock_trigger_svc.register_triggers.await_args.kwargs["user_id"] == "user-1"
        assert mock_trigger_svc.register_triggers.await_args.kwargs["workflow_id"] == "wf-1"
        assert mock_trigger_svc.unregister_triggers.await_args.kwargs["user_id"] == "user-1"
        assert mock_trigger_svc.unregister_triggers.await_args.kwargs["workflow_id"] == "wf-1"
        assert mock_trigger_svc.unregister_triggers.await_args.kwargs["trigger_ids"] == ["old-t1"]

        # The definition re-applied to the document is assembled from the factory
        # request plus the freshly registered trigger ids.
        mock_repo.reset_system_workflow.assert_awaited_once()
        definition = mock_repo.reset_system_workflow.await_args.args[1]
        assert definition.title == req.title
        assert definition.description == req.description
        assert definition.prompt == req.prompt
        assert definition.steps == ["step-1"]
        assert definition.trigger_config is trigger_config
        assert definition.composio_trigger_ids == ["new-t1"]

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_trigger_registration_failure_aborts(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=[])
        )

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.INTEGRATION
        trigger_config.trigger_name = "gmail_new_email"
        trigger_config.model_dump.return_value = {}
        mock_ensure.return_value = trigger_config

        mock_trigger_svc.register_triggers = AsyncMock(side_effect=RuntimeError("fail"))

        req = _make_workflow_request()
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False
        mock_repo.reset_system_workflow = AsyncMock()
        # update_one should NOT have been called
        # (it wasn't set up as a call, so we just verify register was called)
        mock_trigger_svc.register_triggers.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_empty_trigger_registration_aborts(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=[], trigger_name="t")
        )

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.INTEGRATION
        trigger_config.trigger_name = "gmail_new_email"
        trigger_config.model_dump.return_value = {}
        mock_ensure.return_value = trigger_config

        mock_trigger_svc.register_triggers = AsyncMock(return_value=[])

        req = _make_workflow_request()
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_old_trigger_unregister_failure_nonfatal(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.INTEGRATION
        trigger_config.trigger_name = "gmail_new_email"
        trigger_config.model_dump.return_value = {"type": "integration"}
        mock_ensure.return_value = trigger_config

        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock(
            side_effect=RuntimeError("unregister fail")
        )

        req = _make_workflow_request()
        req.steps = []
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        # Unregister failure is non-fatal — reset should still succeed
        assert result is True
        mock_repo.reset_system_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_manual_trigger_no_registration(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        """Manual trigger workflows skip trigger registration entirely."""
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(key="manual_wf", composio_trigger_ids=None, trigger_name=None)
        )
        mock_repo.reset_system_workflow = AsyncMock()

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.MANUAL
        trigger_config.trigger_name = None
        trigger_config.model_dump.return_value = {"type": "manual"}
        mock_ensure.return_value = trigger_config

        req = _make_workflow_request()
        req.steps = []
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"manual_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_repo.reset_system_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_restores_prompt(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        """The run executes workflow.prompt, so reset must restore it too."""
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(key="manual_wf", composio_trigger_ids=None, trigger_name=None)
        )
        mock_repo.reset_system_workflow = AsyncMock()

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.MANUAL
        trigger_config.trigger_name = None
        trigger_config.model_dump.return_value = {"type": "manual"}
        mock_ensure.return_value = trigger_config

        req = _make_workflow_request()
        req.prompt = "the factory prompt"
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"manual_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        definition = mock_repo.reset_system_workflow.await_args.args[1]
        assert definition.prompt == "the factory prompt"

    def _schedule_trigger_config(self) -> MagicMock:
        from datetime import datetime

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.SCHEDULE
        trigger_config.trigger_name = None
        trigger_config.cron_expression = "0 8 * * *"
        trigger_config.timezone = None
        trigger_config.next_run = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)
        trigger_config.model_dump.return_value = {"type": "schedule"}
        return trigger_config

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_by_id")
    @patch(f"{MODULE}.workflow_scheduler")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_stamps_timezone_and_recomputes_next_run(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
        mock_scheduler: MagicMock,
        mock_get_user: MagicMock,
    ) -> None:
        """Schedule definitions carry no timezone; reset must stamp the profile
        timezone (as provisioning does) and recompute next_run from the cron."""
        existing = _existing_wf(key="sched_wf", composio_trigger_ids=None, trigger_name=None)
        existing.activated = False
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=existing)
        mock_repo.reset_system_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "Asia/Kolkata"}
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        trigger_config = self._schedule_trigger_config()
        mock_ensure.return_value = trigger_config

        factory = MagicMock(return_value=_make_workflow_request())

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"sched_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        assert trigger_config.timezone == "Asia/Kolkata"
        mock_get_user.assert_awaited_once_with("user-1")
        trigger_config.update_next_run.assert_called_once_with(user_timezone="Asia/Kolkata")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("profile", [{}, {"timezone": "   "}])
    @patch(f"{MODULE}.get_user_by_id")
    @patch(f"{MODULE}.workflow_scheduler")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_timezone_falls_back_to_utc(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
        mock_scheduler: MagicMock,
        mock_get_user: MagicMock,
        profile: dict[str, str],
    ) -> None:
        """A profile with a blank/missing timezone falls back to exactly UTC."""
        existing = _existing_wf(key="sched_wf", composio_trigger_ids=None, trigger_name=None)
        existing.activated = False
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=existing)
        mock_repo.reset_system_workflow = AsyncMock()
        mock_get_user.return_value = profile
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        trigger_config = self._schedule_trigger_config()
        mock_ensure.return_value = trigger_config

        factory = MagicMock(return_value=_make_workflow_request())

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"sched_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        assert trigger_config.timezone == "UTC"
        trigger_config.update_next_run.assert_called_once_with(user_timezone="UTC")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_by_id")
    @patch(f"{MODULE}.workflow_scheduler")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_rearms_activated_schedule_workflow(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
        mock_scheduler: MagicMock,
        mock_get_user: MagicMock,
    ) -> None:
        """An activated workflow whose reset yields a schedule trigger must get a
        queued fire, or it sits with a cron and no future run."""
        existing = _existing_wf(key="sched_wf", composio_trigger_ids=None, trigger_name=None)
        existing.activated = True
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=existing)
        mock_repo.reset_system_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "UTC"}
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        trigger_config = self._schedule_trigger_config()
        mock_ensure.return_value = trigger_config

        factory = MagicMock(return_value=_make_workflow_request())

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"sched_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_scheduler.schedule_workflow_execution.assert_awaited_once_with(
            "wf-1",
            trigger_config.next_run,
            repeat="0 8 * * *",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_by_id")
    @patch(f"{MODULE}.workflow_scheduler")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_reports_failure_when_rearm_fails(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
        mock_scheduler: MagicMock,
        mock_get_user: MagicMock,
        _patch_log: MagicMock,
    ) -> None:
        """A reset whose re-arm could not queue a fire must not report success —
        the workflow would look reset but never run again."""
        existing = _existing_wf(key="sched_wf", composio_trigger_ids=None, trigger_name=None)
        existing.activated = True
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=existing)
        mock_repo.reset_system_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "UTC"}
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=False)

        trigger_config = self._schedule_trigger_config()
        mock_ensure.return_value = trigger_config

        factory = MagicMock(return_value=_make_workflow_request())

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"sched_wf": factory}):
            from app.constants.log_tags import LogTag
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False
        _patch_log.error.assert_called_once_with(
            f"{LogTag.WORKFLOW} Reset applied but re-arming the schedule failed",
            workflow_id="wf-1",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.get_user_by_id")
    @patch(f"{MODULE}.workflow_scheduler")
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_reset_does_not_arm_deactivated_schedule_workflow(
        self,
        mock_ensure: MagicMock,
        mock_repo: MagicMock,
        mock_scheduler: MagicMock,
        mock_get_user: MagicMock,
    ) -> None:
        """Reset preserves liveness: a deactivated workflow must not gain a fire."""
        existing = _existing_wf(key="sched_wf", composio_trigger_ids=None, trigger_name=None)
        existing.activated = False
        mock_repo.get_system_workflow_for_user = AsyncMock(return_value=existing)
        mock_repo.reset_system_workflow = AsyncMock()
        mock_get_user.return_value = {"timezone": "UTC"}
        mock_scheduler.schedule_workflow_execution = AsyncMock(return_value=True)

        trigger_config = self._schedule_trigger_config()
        mock_ensure.return_value = trigger_config

        factory = MagicMock(return_value=_make_workflow_request())

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"sched_wf": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_scheduler.schedule_workflow_execution.assert_not_awaited()


class TestReregisterIntegrationTriggers:
    """The extracted helper that re-registers a reset's fresh integration triggers."""

    @staticmethod
    def _integration_config(trigger_name: str | None = "gmail_new_email") -> MagicMock:
        from app.models.workflow_models import TriggerType

        cfg = MagicMock()
        cfg.type = TriggerType.INTEGRATION
        cfg.trigger_name = trigger_name
        return cfg

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_registers_with_exact_arguments(self, mock_trigger_svc: MagicMock) -> None:
        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        cfg = self._integration_config()

        from app.services.system_workflows.provisioner import (
            _reregister_integration_triggers,
        )

        result = await _reregister_integration_triggers("user-1", "wf-1", cfg)

        assert result == ["new-t1"]
        mock_trigger_svc.register_triggers.assert_awaited_once_with(
            user_id="user-1",
            workflow_id="wf-1",
            trigger_name="gmail_new_email",
            trigger_config=cfg,
            raise_on_failure=False,
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_non_integration_returns_empty_without_registering(
        self, mock_trigger_svc: MagicMock
    ) -> None:
        mock_trigger_svc.register_triggers = AsyncMock()
        # INTEGRATION type but no trigger_name — the `and` in the guard means this
        # is NOT a registerable integration, so it must short-circuit to [].
        cfg = self._integration_config(trigger_name=None)

        from app.services.system_workflows.provisioner import (
            _reregister_integration_triggers,
        )

        result = await _reregister_integration_triggers("user-1", "wf-1", cfg)

        assert result == []
        mock_trigger_svc.register_triggers.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_registration_error_aborts_with_none_and_logs(
        self, mock_trigger_svc: MagicMock, _patch_log: MagicMock
    ) -> None:
        mock_trigger_svc.register_triggers = AsyncMock(side_effect=RuntimeError("boom"))
        cfg = self._integration_config()

        from app.services.system_workflows.provisioner import (
            _reregister_integration_triggers,
        )

        result = await _reregister_integration_triggers("user-1", "wf-1", cfg)

        assert result is None
        _patch_log.error.assert_called_once_with(
            "[WORKFLOW] Failed to re-register triggers, aborting reset of",
            workflow_id="wf-1",
            error="boom",
            error_type="RuntimeError",
            user_id="user-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_empty_registration_aborts_with_none_and_logs(
        self, mock_trigger_svc: MagicMock, _patch_log: MagicMock
    ) -> None:
        mock_trigger_svc.register_triggers = AsyncMock(return_value=[])
        cfg = self._integration_config()

        from app.services.system_workflows.provisioner import (
            _reregister_integration_triggers,
        )

        result = await _reregister_integration_triggers("user-1", "wf-1", cfg)

        assert result is None
        _patch_log.error.assert_called_once_with(
            "[WORKFLOW] New trigger registration returned an empty result, aborting reset "
            "to avoid leaving the workflow without triggers",
            workflow_id="wf-1",
            user_id="user-1",
        )


class TestUnregisterOldTriggers:
    """The extracted best-effort teardown of a reset's pre-existing triggers."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_unregisters_with_exact_arguments(self, mock_trigger_svc: MagicMock) -> None:
        mock_trigger_svc.unregister_triggers = AsyncMock()

        from app.services.system_workflows.provisioner import _unregister_old_triggers

        await _unregister_old_triggers("user-1", "wf-1", "gmail_new_email", ["old-1"])

        mock_trigger_svc.unregister_triggers.assert_awaited_once_with(
            user_id="user-1",
            trigger_name="gmail_new_email",
            trigger_ids=["old-1"],
            workflow_id="wf-1",
        )

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_skips_when_no_old_triggers(self, mock_trigger_svc: MagicMock) -> None:
        mock_trigger_svc.unregister_triggers = AsyncMock()

        from app.services.system_workflows.provisioner import _unregister_old_triggers

        # No old ids but a trigger_name — the `and` guard means nothing to tear down.
        await _unregister_old_triggers("user-1", "wf-1", "gmail_new_email", [])

        mock_trigger_svc.unregister_triggers.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.TriggerService")
    async def test_unregister_error_is_nonfatal_and_logged(
        self, mock_trigger_svc: MagicMock, _patch_log: MagicMock
    ) -> None:
        mock_trigger_svc.unregister_triggers = AsyncMock(side_effect=RuntimeError("nope"))

        from app.services.system_workflows.provisioner import _unregister_old_triggers

        # Must NOT raise — teardown failure is best-effort.
        await _unregister_old_triggers("user-1", "wf-1", "gmail_new_email", ["old-1"])

        _patch_log.warning.assert_called_once_with(
            "[WORKFLOW] Failed to unregister old triggers during reset of (non-fatal)",
            workflow_id="wf-1",
            error="nope",
            error_type="RuntimeError",
            user_id="user-1",
        )


class TestResetDefinitionAssembly:
    """The definition re-applied on reset falls back correctly on empty fields."""

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflow_repository")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_empty_description_falls_back_to_empty_string(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_repo: MagicMock,
    ) -> None:
        mock_repo.get_system_workflow_for_user = AsyncMock(
            return_value=_existing_wf(composio_trigger_ids=["old-t1"])
        )
        mock_repo.reset_system_workflow = AsyncMock()

        from app.models.workflow_models import TriggerType

        trigger_config = MagicMock()
        trigger_config.type = TriggerType.INTEGRATION
        trigger_config.trigger_name = "gmail_new_email"
        mock_ensure.return_value = trigger_config

        mock_trigger_svc.register_triggers = AsyncMock(return_value=["new-t1"])
        mock_trigger_svc.unregister_triggers = AsyncMock()

        req = _make_workflow_request(description="")
        req.steps = []
        factory = MagicMock(return_value=req)

        with patch.dict(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        definition = mock_repo.reset_system_workflow.await_args.args[1]
        assert definition.description == ""
        assert definition.steps == []
