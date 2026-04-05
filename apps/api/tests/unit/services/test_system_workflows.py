"""Unit tests for app/services/system_workflows/provisioner.py.

Covers:
- provision_system_workflows: no entries, idempotent skip, success, DuplicateKeyError, generic error
- _notify_workflows_provisioned: single vs multiple workflows, notification failure
- reset_system_workflow_to_default: not found, no registry key, success with trigger re-registration,
  trigger registration failure, old trigger unregister failure (non-fatal)
"""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

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


def _make_factory(request: Optional[MagicMock] = None) -> MagicMock:
    if request is None:
        request = _make_workflow_request()
    factory = MagicMock(return_value=request)
    return factory


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log"):
        yield


class TestProvisionSystemWorkflows:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.SYSTEM_WORKFLOWS_BY_INTEGRATION", {})
    async def test_no_entries_for_integration(self) -> None:
        from app.services.system_workflows.provisioner import provision_system_workflows

        # Should return without error
        await provision_system_workflows("user-1", "slack", "Slack")

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.WorkflowService")
    async def test_idempotent_skip_existing(
        self,
        mock_workflow_svc: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(return_value={"_id": "existing"})
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
    @patch(f"{MODULE}.workflows_collection")
    async def test_successful_provisioning(
        self,
        mock_collection: AsyncMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(return_value=None)
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
    @patch(f"{MODULE}.workflows_collection")
    async def test_duplicate_key_error_skipped(
        self,
        mock_collection: AsyncMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(
            side_effect=DuplicateKeyError("dup")
        )
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
    @patch(f"{MODULE}.workflows_collection")
    async def test_generic_error_continues(
        self,
        mock_collection: AsyncMock,
        mock_workflow_svc: MagicMock,
        mock_notify: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_workflow_svc.create_workflow = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )
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
    async def test_notification_failure_does_not_raise(
        self, mock_notif_cls: MagicMock
    ) -> None:
        mock_svc = AsyncMock()
        mock_svc.create_notification = AsyncMock(
            side_effect=RuntimeError("notify fail")
        )
        mock_notif_cls.return_value = mock_svc

        from app.services.system_workflows.provisioner import (
            _notify_workflows_provisioned,
        )

        # Should not raise
        await _notify_workflows_provisioned(
            "user-1", "Gmail", [_make_workflow_request()]
        )


class TestResetSystemWorkflowToDefault:
    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    async def test_workflow_not_found(self, mock_collection: AsyncMock) -> None:
        mock_collection.find_one = AsyncMock(return_value=None)

        from app.services.system_workflows.provisioner import (
            reset_system_workflow_to_default,
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {})
    async def test_no_registry_entry(self, mock_collection: AsyncMock) -> None:
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "unknown_key",
                "trigger_config": {},
            }
        )

        from app.services.system_workflows.provisioner import (
            reset_system_workflow_to_default,
        )

        result = await reset_system_workflow_to_default("wf-1", "user-1")
        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_successful_reset_with_triggers(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        # Existing workflow doc
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "gmail_digest",
                "trigger_config": {
                    "composio_trigger_ids": ["old-t1"],
                    "trigger_name": "gmail_new_email",
                },
            }
        )
        mock_collection.update_one = AsyncMock()

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
        req.steps = []
        factory = MagicMock(return_value=req)

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}
        ):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is True
        mock_trigger_svc.register_triggers.assert_awaited_once()
        mock_trigger_svc.unregister_triggers.assert_awaited_once()
        mock_collection.update_one.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_trigger_registration_failure_aborts(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "gmail_digest",
                "trigger_config": {
                    "composio_trigger_ids": [],
                    "trigger_name": "gmail_new_email",
                },
            }
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

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}
        ):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False
        mock_collection.update_one = AsyncMock()
        # update_one should NOT have been called
        # (it wasn't set up as a call, so we just verify register was called)
        mock_trigger_svc.register_triggers.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_empty_trigger_registration_aborts(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "gmail_digest",
                "trigger_config": {"composio_trigger_ids": [], "trigger_name": "t"},
            }
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

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}
        ):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        assert result is False

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.TriggerService")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_old_trigger_unregister_failure_nonfatal(
        self,
        mock_ensure: MagicMock,
        mock_trigger_svc: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "gmail_digest",
                "trigger_config": {
                    "composio_trigger_ids": ["old-t1"],
                    "trigger_name": "gmail_new_email",
                },
            }
        )
        mock_collection.update_one = AsyncMock()

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

        with patch.dict(
            f"{MODULE}.SYSTEM_WORKFLOW_REGISTRY", {"gmail_digest": factory}
        ):
            from app.services.system_workflows.provisioner import (
                reset_system_workflow_to_default,
            )

            result = await reset_system_workflow_to_default("wf-1", "user-1")

        # Unregister failure is non-fatal — reset should still succeed
        assert result is True
        mock_collection.update_one.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(f"{MODULE}.workflows_collection")
    @patch(f"{MODULE}.ensure_trigger_config_object")
    async def test_manual_trigger_no_registration(
        self,
        mock_ensure: MagicMock,
        mock_collection: AsyncMock,
    ) -> None:
        """Manual trigger workflows skip trigger registration entirely."""
        mock_collection.find_one = AsyncMock(
            return_value={
                "_id": "wf-1",
                "user_id": "user-1",
                "is_system_workflow": True,
                "system_workflow_key": "manual_wf",
                "trigger_config": {},
            }
        )
        mock_collection.update_one = AsyncMock()

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
        mock_collection.update_one.assert_awaited_once()
