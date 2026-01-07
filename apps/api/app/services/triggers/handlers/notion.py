"""
Notion trigger handler.

Handles Notion-specific trigger logic.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set, TypedDict

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from composio.types import ToolExecutionResponse


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

            # Get pagination and search params
            page_size = int(kwargs.get("page_size", 100))
            search_query = kwargs.get("search", "").strip()

            # Determine fetch type based on field name
            fetch_type = None
            if field_name == "database_id" or field_name == "database_ids":
                fetch_type = "databases"
            elif field_name == "page_id" or field_name == "page_ids":
                fetch_type = "pages"

            if not fetch_type:
                return []

            # Use NOTION_FETCH_DATA tool
            tool = composio_service.get_tool("NOTION_FETCH_DATA", user_id=user_id)
            if not tool:
                logger.error("Notion FETCH_DATA tool not found")
                return []

            # Invoke tool with parameters
            params = {
                "fetch_type": fetch_type,
                "page_size": page_size,
            }
            if search_query:
                params["query"] = search_query

            result: ToolExecutionResponse = await asyncio.to_thread(tool.invoke, params)

            # Check if successful
            if not result.get("successful", False):
                logger.error(
                    f"Notion API error: {result.get('error', 'Unknown error')}"
                )
                return []

            # Extract values from data - the response has a 'values' field
            # which contains simplified list of resources with id, title, and type
            data = result.get("data", {})

            if not isinstance(data, dict):
                logger.error("Unexpected data format from Notion API")
                return []

            # The 'values' field contains the simplified projection
            values = data.get("values", [])

            options = []
            for item in values:
                if not isinstance(item, dict):
                    continue

                item_id = item.get("id")
                title = item.get("title", "Untitled")

                if not item_id:
                    continue

                options.append({"value": item_id, "label": title})

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
        config: Dict[str, Any],
    ) -> List[str]:
        """Register Notion triggers."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown Notion trigger: {trigger_name}")
            return []

        composio = get_composio_service()
        trigger_ids = []

        # Handle multi-select support for databases and pages
        if trigger_name == "notion_new_page_in_db":
            # Support both singular and plural for backward compatibility
            database_ids = config.get("database_ids", [])
            if not database_ids and "database_id" in config:
                database_ids = [config["database_id"]]

            if not database_ids:
                logger.warning("No database IDs provided for notion_new_page_in_db")
                return []

            # Register a trigger for each database
            for database_id in database_ids:
                try:
                    result = await asyncio.to_thread(
                        composio.composio.triggers.create,
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
            # Support both singular and plural for backward compatibility
            page_ids = config.get("page_ids", [])
            if not page_ids and "page_id" in config:
                page_ids = [config["page_id"]]

            if not page_ids:
                logger.warning("No page IDs provided for notion_page_updated")
                return []

            # Register a trigger for each page
            for page_id in page_ids:
                try:
                    result = await asyncio.to_thread(
                        composio.composio.triggers.create,
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
        else:
            # notion_all_page_events needs no config
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

        return trigger_ids

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister Notion triggers."""
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
                logger.info(f"Unregistered Notion trigger: {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to unregister Notion trigger {trigger_id}: {e}")
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Notion trigger event."""
        try:
            # Match by specific trigger ID since these are manually registered
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


notion_trigger_handler = NotionTriggerHandler()
