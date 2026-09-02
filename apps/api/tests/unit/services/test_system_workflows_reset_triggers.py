"""Direct unit tests for the two trigger-handling helpers extracted from
``reset_system_workflow_to_default`` during the PLR0912 complexity refactor
(commit 58a9f12fa5's follow-up): ``_reregister_triggers_for_reset`` and
``_unregister_old_triggers_for_reset`` in
``app/services/system_workflows/provisioner.py``.

``test_system_workflows.py`` exercises both only indirectly through the full
``reset_system_workflow_to_default`` flow — this drives each branch directly
with exact-value assertions on return values and log calls.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.system_workflows.provisioner import (
    _reregister_triggers_for_reset,
    _unregister_old_triggers_for_reset,
)

MODULE = "app.services.system_workflows.provisioner"


def _integration_trigger(trigger_name: str | None = "gmail_new_email") -> TriggerConfig:
    return TriggerConfig(type=TriggerType.INTEGRATION, trigger_name=trigger_name)


def _schedule_trigger() -> TriggerConfig:
    return TriggerConfig(type=TriggerType.SCHEDULE)


@pytest.fixture(autouse=True)
def _patch_log():
    with patch(f"{MODULE}.log") as mock_log:
        yield mock_log


class TestReregisterTriggersForReset:
    async def test_non_integration_trigger_needs_no_registration(self, _patch_log) -> None:
        result = await _reregister_triggers_for_reset(_schedule_trigger(), "wf-1", "user-1")
        assert result == []
        _patch_log.error.assert_not_called()

    async def test_integration_trigger_with_no_trigger_name_needs_no_registration(
        self, _patch_log
    ) -> None:
        result = await _reregister_triggers_for_reset(
            _integration_trigger(trigger_name=None), "wf-1", "user-1"
        )
        assert result == []
        _patch_log.error.assert_not_called()

    async def test_successful_registration_returns_the_new_ids(self, _patch_log) -> None:
        trigger_config = _integration_trigger("gmail_new_email")
        register = AsyncMock(return_value=["trig-1", "trig-2"])
        with patch(f"{MODULE}.TriggerService.register_triggers", register):
            result = await _reregister_triggers_for_reset(trigger_config, "wf-1", "user-1")

        assert result == ["trig-1", "trig-2"]
        register.assert_awaited_once_with(
            user_id="user-1",
            workflow_id="wf-1",
            trigger_name="gmail_new_email",
            trigger_config=trigger_config,
            raise_on_failure=False,
        )
        _patch_log.error.assert_not_called()

    async def test_registration_exception_aborts_with_none_and_logs(self, _patch_log) -> None:
        trigger_config = _integration_trigger("gmail_new_email")
        register = AsyncMock(side_effect=RuntimeError("composio unreachable"))
        with patch(f"{MODULE}.TriggerService.register_triggers", register):
            result = await _reregister_triggers_for_reset(trigger_config, "wf-1", "user-1")

        assert result is None
        _patch_log.error.assert_called_once_with(
            "[WORKFLOW] Failed to re-register triggers, aborting reset of",
            workflow_id="wf-1",
            error="composio unreachable",
            error_type="RuntimeError",
            user_id="user-1",
        )

    async def test_empty_registration_result_aborts_with_none_and_logs(self, _patch_log) -> None:
        trigger_config = _integration_trigger("gmail_new_email")
        register = AsyncMock(return_value=[])
        with patch(f"{MODULE}.TriggerService.register_triggers", register):
            result = await _reregister_triggers_for_reset(trigger_config, "wf-1", "user-1")

        assert result is None
        _patch_log.error.assert_called_once_with(
            "[WORKFLOW] New trigger registration returned an empty result, aborting reset to"
            " avoid leaving the workflow without triggers",
            workflow_id="wf-1",
            user_id="user-1",
        )


class TestUnregisterOldTriggersForReset:
    async def test_no_old_trigger_ids_is_a_no_op(self, _patch_log) -> None:
        unregister = AsyncMock()
        with patch(f"{MODULE}.TriggerService.unregister_triggers", unregister):
            await _unregister_old_triggers_for_reset([], "gmail_new_email", "wf-1", "user-1")

        unregister.assert_not_awaited()
        _patch_log.warning.assert_not_called()

    async def test_no_trigger_name_is_a_no_op(self, _patch_log) -> None:
        unregister = AsyncMock()
        with patch(f"{MODULE}.TriggerService.unregister_triggers", unregister):
            await _unregister_old_triggers_for_reset(["old-1"], None, "wf-1", "user-1")

        unregister.assert_not_awaited()
        _patch_log.warning.assert_not_called()

    async def test_unregisters_the_exact_old_trigger_ids(self, _patch_log) -> None:
        unregister = AsyncMock()
        with patch(f"{MODULE}.TriggerService.unregister_triggers", unregister):
            await _unregister_old_triggers_for_reset(
                ["old-1", "old-2"], "gmail_new_email", "wf-1", "user-1"
            )

        unregister.assert_awaited_once_with(
            user_id="user-1",
            trigger_name="gmail_new_email",
            trigger_ids=["old-1", "old-2"],
            workflow_id="wf-1",
        )
        _patch_log.warning.assert_not_called()

    async def test_a_failure_is_swallowed_and_logged_as_non_fatal(self, _patch_log) -> None:
        unregister = AsyncMock(side_effect=RuntimeError("composio timeout"))
        with patch(f"{MODULE}.TriggerService.unregister_triggers", unregister):
            await _unregister_old_triggers_for_reset(
                ["old-1"], "gmail_new_email", "wf-1", "user-1"
            )  # must not raise

        _patch_log.warning.assert_called_once_with(
            "[WORKFLOW] Failed to unregister old triggers during reset of (non-fatal)",
            workflow_id="wf-1",
            error="composio timeout",
            error_type="RuntimeError",
            user_id="user-1",
        )
