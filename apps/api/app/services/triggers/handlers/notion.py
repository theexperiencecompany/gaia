"""
Notion trigger handler.

Handles Notion-specific trigger logic.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set, TypedDict

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import (
    NotionAllPageEventsPayload,
    NotionFetchDataData,
    NotionFetchDataInput,
    NotionPageAddedPayload,
    NotionPageUpdatedPayload,
)
from app.models.trigger_configs import (
    NotionAllPageEventsConfig,
    NotionNewPageInDbConfig,
    NotionPageUpdatedConfig,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler


class NotionTitleProperty(TypedDict):
    plain_text: str


class NotionRichText(TypedDict):
    plain_text: str


class NotionProperty(TypedDict):
    type: str
    title: Optional[List[NotionTitleProperty]]  # For title property


class NotionSearchResult(TypedDict):
    id: str
    object: str  # 'page' or 'database'
    url: str
    properties: Dict[
        str, Any
    ]  # Properties are complex, typing loosely for now but checking types in logic
    title: Optional[List[NotionRichText]]  # For databases, title is top level


class NotionResponseData(TypedDict):
    results: List[NotionSearchResult]
    has_more: bool
    next_cursor: Optional[str]


class NotionTriggerHandler(TriggerHandler):
    """Handler for Notion triggers."""

    SUPPORTED_TRIGGERS = [
        "notion_new_page_in_db",
        "notion_page_updated",
        "notion_all_page_events",
    ]

    SUPPORTED_EVENTS = {
        "NOTION_PAGE_ADDED_TO_DATABASE",
        "NOTION_PAGE_UPDATED_TRIGGER",
        "NOTION_ALL_PAGE_EVENTS_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO = {
        "notion_new_page_in_db": "NOTION_PAGE_ADDED_TO_DATABASE",
        "notion_page_updated": "NOTION_PAGE_UPDATED_TRIGGER",
        "notion_all_page_events": "NOTION_ALL_PAGE_EVENTS_TRIGGER",
    }

    @property
    def trigger_names(self) -> List[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> Set[str]:
        return self.SUPPORTED_EVENTS

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Get dynamic options for Notion trigger config fields."""
        try:
            composio_service = get_composio_service()

            # Use NOTION_FETCH_DATA tool
            tool = composio_service.get_tool("NOTION_FETCH_DATA", user_id=user_id)
            if not tool:
                logger.error("Notion FETCH_DATA tool not found")
                return []

            # Determine fetch_type based on field_name
            if field_name == "database_id":
                fetch_type = "databases"
            elif field_name == "page_id":
                fetch_type = "pages"
            else:
                logger.warning(f"Unknown Notion field '{field_name}', fetching all")
                fetch_type = "all"

            # Invoke tool with typed input
            input_model = NotionFetchDataInput(
                fetch_type=fetch_type,
                page_size=100,
                query=kwargs.get("search"),
            )

            logger.debug(f"Notion fetch input: {input_model.model_dump()}")

            result = await asyncio.to_thread(
                tool.invoke, input_model.model_dump(exclude_none=True)
            )

            if not result["successful"]:
                logger.error(f"Notion API error: {result['error']}")
                return []

            # Extract and parse data
            data = NotionFetchDataData.model_validate(result["data"])
            items = data.get_items()
            options = []

            for item in items:
                if not item.id:
                    continue

                label = item.title or "Untitled"
                options.append({"value": item.id, "label": label})

            logger.info(f"Returning {len(options)} Notion {field_name} options")
            return options

        except Exception as e:
            logger.error(f"Failed to get Notion options for {field_name}: {e}")
            return []

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register Notion triggers."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown Notion trigger: {trigger_name}")
            return []

        composio = get_composio_service()
        trigger_ids = []
        trigger_data = trigger_config.trigger_data

        # Handle multi-select support for databases and pages
        if trigger_name == "notion_new_page_in_db":
            if not isinstance(trigger_data, NotionNewPageInDbConfig):
                raise TypeError(
                    f"Expected NotionNewPageInDbConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            database_ids = trigger_data.database_ids

            if not database_ids:
                logger.warning("No database IDs provided for notion_new_page_in_db")
                return []

            # Register a trigger for each database
            for database_id in database_ids:
                try:
                    # Direct synchronous call
                    result = composio.composio.triggers.create(
                        user_id=user_id,
                        slug=composio_slug,
                        trigger_config={"database_id": database_id},
                    )
                    if result and hasattr(result, "trigger_id"):
                        logger.info(
                            f"Registered {composio_slug} for database {database_id}: {result.trigger_id}"
                        )
                        trigger_ids.append(result.trigger_id)
                except Exception as e:
                    logger.error(
                        f"Failed to register trigger for database {database_id}: {e}"
                    )

        elif trigger_name == "notion_page_updated":
            if not isinstance(trigger_data, NotionPageUpdatedConfig):
                raise TypeError(
                    f"Expected NotionPageUpdatedConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            page_ids = trigger_data.page_ids

            if not page_ids:
                logger.warning("No page IDs provided for notion_page_updated")
                return []

            # Register a trigger for each page
            for page_id in page_ids:
                try:
                    result = composio.composio.triggers.create(
                        user_id=user_id,
                        slug=composio_slug,
                        trigger_config={"page_id": page_id},
                    )
                    if result and hasattr(result, "trigger_id"):
                        logger.info(
                            f"Registered {composio_slug} for page {page_id}: {result.trigger_id}"
                        )
                        trigger_ids.append(result.trigger_id)
                except Exception as e:
                    logger.error(f"Failed to register trigger for page {page_id}: {e}")

        elif trigger_name == "notion_all_page_events":
            # Validate type even though no config is needed
            if trigger_data is not None and not isinstance(
                trigger_data, NotionAllPageEventsConfig
            ):
                raise TypeError(
                    f"Expected NotionAllPageEventsConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__}"
                )
            try:
                result = await asyncio.to_thread(
                    composio.composio.triggers.create,
                    user_id=user_id,
                    slug=composio_slug,
                    trigger_config={},
                )
                if result and hasattr(result, "trigger_id"):
                    logger.info(
                        f"Registered {composio_slug} for user {user_id}: {result.trigger_id}"
                    )
                    trigger_ids.append(result.trigger_id)
            except Exception as e:
                logger.error(f"Failed to register Notion trigger {trigger_name}: {e}")
        else:
            logger.error(f"Unknown Notion trigger: {trigger_name}")
            return []

        return trigger_ids

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Notion trigger event."""
        try:
            # Match by specific trigger ID since these are manually registered
            query = {
                "activated": True,
                "trigger_config.type": TriggerType.INTEGRATION,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_id,
            }

            # optional: validate payload for page added events
            # Validate payload
            try:
                if "new_page" in event_type.lower():
                    NotionPageAddedPayload.model_validate(data)
                elif "page_updated" in event_type.lower():
                    NotionPageUpdatedPayload.model_validate(data)
                elif "all_page_events" in event_type.lower():
                    NotionAllPageEventsPayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Notion payload validation failed: {e}")

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


notion_trigger_handler = NotionTriggerHandler()
