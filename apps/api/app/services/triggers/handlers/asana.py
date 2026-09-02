"""
Asana trigger handler.
"""

from typing import Any, ClassVar

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.trigger_configs import AsanaTaskTriggerConfig
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import log


class AsanaTriggerHandler(TriggerHandler):
    """Handler for Asana triggers."""

    SUPPORTED_TRIGGERS: ClassVar[list[str]] = ["asana_task_trigger"]

    # Composio retired ASANA_TASK_TRIGGER; the live slug is ASANA_TASK_CREATED.
    SUPPORTED_EVENTS: ClassVar[set[str]] = {"ASANA_TASK_CREATED"}

    TRIGGER_TO_COMPOSIO: ClassVar[dict[str, str]] = {
        "asana_task_trigger": "ASANA_TASK_CREATED",
    }

    @property
    def trigger_names(self) -> list[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> set[str]:
        return self.SUPPORTED_EVENTS

    async def register(
        self,
        user_id: str,
        _owner_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> list[str]:
        """Register Asana triggers.

        Raises:
            TriggerRegistrationError: If trigger registration fails
        """

        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown Asana trigger: {trigger_name}",
                trigger_name,
            )

        trigger_data = trigger_config.trigger_data

        # Validate trigger_data type
        if not isinstance(trigger_data, AsanaTaskTriggerConfig):
            raise TypeError(
                f"Expected AsanaTaskTriggerConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
            )

        # Composio's ASANA_TASK_CREATED requires a project GID; the legacy
        # workspace_id field is no longer part of the trigger config.
        if not trigger_data.project_gid:
            raise TriggerRegistrationError(
                "asana_task_trigger now requires project_gid "
                "(Composio retired the unscoped ASANA_TASK_TRIGGER)",
                trigger_name,
            )
        composio_trigger_config: dict[str, Any] = {
            "project_gid": trigger_data.project_gid,
        }

        # Use the base class helper for consistent error handling
        return await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=[composio_trigger_config],
            composio_slug=composio_slug,
        )

    async def find_workflows(
        self, event_type: str, trigger_id: str, _data: dict[str, Any]
    ) -> list[Workflow]:
        """Find workflows matching an Asana trigger event."""
        log.set_ns("trigger", integration_id="asana", trigger_type=event_type)
        try:
            workflows: list[Workflow] = []
            workflows.extend(await workflow_repository.find_active_by_composio_trigger(trigger_id))
            return workflows

        except Exception as e:
            log.error(
                f"{LogTag.TRIGGER} Error finding workflows for trigger",
                trigger_id=trigger_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []


asana_trigger_handler = AsanaTriggerHandler()
