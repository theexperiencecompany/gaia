"""
Google Docs trigger handler.
"""

import asyncio
from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler


class GoogleDocsTriggerHandler(TriggerHandler):
    """Handler for Google Docs triggers."""

    SUPPORTED_TRIGGERS = [
        "google_docs_new_document",
    ]

    SUPPORTED_EVENTS = {
        "GOOGLEDOCS_PAGE_ADDED_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO = {
        "google_docs_new_document": "GOOGLEDOCS_PAGE_ADDED_TRIGGER",
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
        config: Dict[str, Any],
    ) -> List[str]:
        """Register Google Docs triggers."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown Google Docs trigger: {trigger_name}")
            return []

        composio = get_composio_service()
        trigger_config: Dict[str, Any] = {}

        # New Document Added trigger usually doesn't need config to monitor entire workspace
        # If config is needed in future, map it here.

        try:
            result = await asyncio.to_thread(
                composio.composio.triggers.create,
                user_id=user_id,
                slug=composio_slug,
                trigger_config=trigger_config,
            )

            if result and hasattr(result, "trigger_id"):
                logger.info(
                    f"Registered {composio_slug} for user {user_id}: {result.trigger_id}"
                )
                return [result.trigger_id]

            return []

        except Exception as e:
            logger.error(f"Failed to register Google Docs trigger {trigger_name}: {e}")
            return []

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister Google Docs triggers."""
        if not trigger_ids:
            return True

        success = True
        composio = get_composio_service()

        for trigger_id in trigger_ids:
            try:
                await asyncio.to_thread(
                    composio.composio.triggers.disable,
                    trigger_id=trigger_id,
                )
                logger.info(f"Unregistered Google Docs trigger: {trigger_id}")
            except Exception as e:
                logger.error(
                    f"Failed to unregister Google Docs trigger {trigger_id}: {e}"
                )
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Google Docs trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.APP,
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


google_docs_trigger_handler = GoogleDocsTriggerHandler()
