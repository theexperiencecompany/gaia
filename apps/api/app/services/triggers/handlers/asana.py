"""
Asana trigger handler.
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.trigger_configs import AsanaTaskTriggerConfig
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError


class AsanaTriggerHandler(TriggerHandler):
    """Handler for Asana triggers."""

    SUPPORTED_TRIGGERS = ["asana_task_trigger"]

    SUPPORTED_EVENTS = {"ASANA_TASK_TRIGGER"}

    TRIGGER_TO_COMPOSIO = {
        "asana_task_trigger": "ASANA_TASK_TRIGGER",
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

        # Build trigger config with optional filters
        composio_trigger_config: Dict[str, Any] = {}
        if trigger_data.project_id:
            composio_trigger_config["project_id"] = trigger_data.project_id
        if trigger_data.workspace_id:
            composio_trigger_config["workspace_id"] = trigger_data.workspace_id

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
        """Find workflows matching an Asana trigger event."""
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


asana_trigger_handler = AsanaTriggerHandler()
