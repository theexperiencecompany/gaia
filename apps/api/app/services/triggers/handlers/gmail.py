"""
Gmail trigger handler.

Handles Gmail new message trigger processing.
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.triggers.base import TriggerHandler


class GmailTriggerHandler(TriggerHandler):
    """Handler for Gmail triggers."""

    SUPPORTED_TRIGGERS = ["gmail_new_message"]

    SUPPORTED_EVENTS = {"GMAIL_NEW_GMAIL_MESSAGE"}

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
        config: Dict[str, Any],
    ) -> List[str]:
        """Gmail triggers are automatically handled by Composio connection.

        No explicit registration needed - triggers fire on connected account.
        """
        logger.info(f"Gmail trigger enabled for workflow {workflow_id}")
        return []  # No explicit trigger IDs for Gmail

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Gmail triggers don't need unregistration."""
        return True

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows with Gmail/email triggers for a user."""
        try:
            user_id = data.get("user_id")
            if not user_id:
                logger.error("No user_id in Gmail webhook data")
                return []

            query = {
                "user_id": user_id,
                "activated": True,
                "trigger_config.type": TriggerType.EMAIL,
                "trigger_config.enabled": True,
            }

            cursor = workflows_collection.find(query)
            workflows = []

            async for workflow_doc in cursor:
                try:
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]
                    workflow = Workflow(**workflow_doc)
                    workflows.append(workflow)
                except Exception as e:
                    logger.error(f"Error processing workflow: {e}")
                    continue

            return workflows

        except Exception as e:
            logger.error(f"Error finding Gmail workflows: {e}")
            return []


gmail_trigger_handler = GmailTriggerHandler()
