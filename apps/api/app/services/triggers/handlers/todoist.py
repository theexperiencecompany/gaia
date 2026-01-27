"""
Todoist trigger handler.
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.trigger_configs import TodoistNewTaskCreatedConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError


class TodoistTriggerHandler(TriggerHandler):
    """Handler for Todoist triggers."""

    SUPPORTED_TRIGGERS = ["todoist_new_task_created"]

    SUPPORTED_EVENTS = {"TODOIST_NEW_TASK_CREATED"}

    TRIGGER_TO_COMPOSIO = {
        "todoist_new_task_created": "TODOIST_NEW_TASK_CREATED",
    }

    @property
    def trigger_names(self) -> List[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> Set[str]:
        return self.SUPPORTED_EVENTS

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register Todoist triggers.

        Raises:
            TriggerRegistrationError: If trigger registration fails
        """
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown Todoist trigger: {trigger_name}",
                trigger_name,
            )

        trigger_data = trigger_config.trigger_data

        # Validate trigger_data type if provided
        if trigger_data is not None and not isinstance(
            trigger_data, TodoistNewTaskCreatedConfig
        ):
            raise TypeError(
                f"Expected TodoistNewTaskCreatedConfig for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__}"
            )

        # No config needed for Todoist new task trigger
        composio_trigger_config: Dict[str, Any] = {}

        # Use the base class helper for consistent error handling
        return await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=[composio_trigger_config],
            composio_slug=composio_slug,
        )

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Todoist trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            cursor = workflows_collection.find(query)
            workflows: List[Workflow] = []

            async for workflow_doc in cursor:
                try:
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]
                    workflow = Workflow(**workflow_doc)
                    workflows.append(workflow)
                except Exception as e:
                    logger.error(f"Error processing workflow document: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding workflows for trigger {trigger_id}: {e}")
            return []


todoist_trigger_handler = TodoistTriggerHandler()
