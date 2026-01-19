"""
Google Docs trigger handler.
"""

from typing import Any, Dict, List, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import GoogleDocsPageAddedPayload
from app.models.trigger_configs import (
    GoogleDocsDocumentDeletedConfig,
    GoogleDocsDocumentUpdatedConfig,
    GoogleDocsNewDocumentConfig,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError


class GoogleDocsTriggerHandler(TriggerHandler):
    """Handler for Google Docs triggers."""

    SUPPORTED_TRIGGERS = [
        "google_docs_new_document",
        "google_docs_document_deleted",
        "google_docs_document_updated",
    ]

    SUPPORTED_EVENTS = {
        "GOOGLEDOCS_PAGE_ADDED_TRIGGER",
        "GOOGLEDOCS_DOCUMENT_DELETED_TRIGGER",
        "GOOGLEDOCS_DOCUMENT_UPDATED_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO = {
        "google_docs_new_document": "GOOGLEDOCS_PAGE_ADDED_TRIGGER",
        "google_docs_document_deleted": "GOOGLEDOCS_DOCUMENT_DELETED_TRIGGER",
        "google_docs_document_updated": "GOOGLEDOCS_DOCUMENT_UPDATED_TRIGGER",
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
        """Register Google Docs triggers.

        Raises:
            TriggerRegistrationError: If trigger registration fails
        """
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown Google Docs trigger: {trigger_name}",
                trigger_name,
            )

        trigger_data = trigger_config.trigger_data

        # Validate trigger_data type if provided
        valid_types = (
            GoogleDocsNewDocumentConfig,
            GoogleDocsDocumentDeletedConfig,
            GoogleDocsDocumentUpdatedConfig,
        )
        if trigger_data is not None and not isinstance(trigger_data, valid_types):
            raise TypeError(
                f"Expected one of {[t.__name__ for t in valid_types]} for trigger '{trigger_name}', "
                f"but got {type(trigger_data).__name__}"
            )

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
        """Find workflows matching a Google Docs trigger event."""
        try:
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            # Optional: validate payload
            try:
                GoogleDocsPageAddedPayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Google Docs payload validation failed: {e}")

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
