"""
Google Sheets trigger handler with cascading dropdown support.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from composio.types import ToolExecutionResponse


class GoogleSheetsTriggerHandler(TriggerHandler):
    """Handler for Google Sheets triggers with multi-select support."""

    SUPPORTED_TRIGGERS = [
        "google_sheets_new_row",
        "google_sheets_new_sheet",
    ]

    SUPPORTED_EVENTS = {
        "GOOGLEDOCS_NEW_ROWS_TRIGGER",
        "GOOGLESHEETS_NEW_ROWS_TRIGGER",
        "GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO = {
        "google_sheets_new_row": "GOOGLESHEETS_NEW_ROWS_TRIGGER",
        "google_sheets_new_sheet": "GOOGLESHEETS_NEW_SHEET_ADDED_TRIGGER",
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
        """Get dynamic options for Google Sheets trigger config fields."""
        try:
            composio_service = get_composio_service()

            # Get spreadsheets list
            if field_name == "spreadsheet_ids":
                # Get search query if provided
                search_query = kwargs.get("search", "").strip()

                # Use LangChain wrapper pattern
                tool = composio_service.get_tool(
                    "GOOGLESHEETS_SEARCH_SPREADSHEETS",
                    user_id=user_id,
                )
                if not tool:
                    logger.error("Google Sheets search spreadsheets tool not found")
                    return []

                # Invoke tool with search params - only use supported fields
                params: Dict[str, Any] = {
                    "max_results": 100,
                }
                if search_query:
                    params["query"] = search_query

                result: ToolExecutionResponse = await asyncio.to_thread(
                    tool.invoke, params
                )

                # Check if result is valid dict
                if not isinstance(result, dict):
                    logger.error(
                        f"Google Sheets API returned invalid response: {result}"
                    )
                    return []

                # Check if successful
                if not result.get("successful", False):
                    logger.error(
                        f"Google Sheets API error: {result.get('error', 'Unknown error')}"
                    )
                    return []

                # Extract spreadsheets from data
                data = result.get("data", {})
                spreadsheets = data.get("spreadsheets", [])

                # Convert to options format with shared indicator
                options = []
                for sheet in spreadsheets:
                    if "id" not in sheet or "name" not in sheet:
                        continue

                    # Check if spreadsheet is shared (not owned by current user)
                    is_shared = sheet.get("shared", False)
                    owners = sheet.get("owners", [])
                    is_owned_by_me = (
                        any(owner.get("me", False) for owner in owners)
                        if owners
                        else False
                    )

                    # Create label with shared indicator
                    label = sheet["name"]
                    if is_shared and not is_owned_by_me:
                        label = f"{sheet['name']} (Shared)"

                    options.append({"value": sheet["id"], "label": label})

                logger.info(
                    f"Returning {len(options)} Google Sheets spreadsheet options"
                )
                return options

            # Get sheets grouped by spreadsheet (cascading)
            elif field_name == "sheet_names" and parent_ids:
                grouped_results = []

                for spreadsheet_id in parent_ids:
                    # Use LangChain wrapper pattern for getting sheet names
                    tool = composio_service.get_tool(
                        "GOOGLESHEETS_GET_SHEET_NAMES",
                        user_id=user_id,
                    )
                    if not tool:
                        logger.error("Google Sheets get sheet names tool not found")
                        continue

                    sheets_result: ToolExecutionResponse = await asyncio.to_thread(
                        tool.invoke, {"spreadsheet_id": spreadsheet_id}
                    )

                    # Check if successful
                    if not sheets_result.get("successful", False):
                        logger.error(
                            f"Failed to get sheet names for {spreadsheet_id}: {sheets_result.get('error', 'Unknown error')}"
                        )
                        continue

                    # Extract sheet names from data
                    data = sheets_result.get("data", {})
                    sheet_names = data.get("sheet_names", [])

                    # Get spreadsheet name from the list (we need to search for it)
                    search_tool = composio_service.get_tool(
                        "GOOGLESHEETS_SEARCH_SPREADSHEETS",
                        user_id=user_id,
                    )
                    if search_tool:
                        # Search for this specific spreadsheet to get its name
                        search_result: ToolExecutionResponse = await asyncio.to_thread(
                            search_tool.invoke,
                            {"max_results": 1000},  # Get all to find our specific one
                        )
                        if search_result.get("successful", False):
                            search_data = search_result.get("data", {})
                            all_spreadsheets = search_data.get("spreadsheets", [])
                            matching_sheet = next(
                                (
                                    s
                                    for s in all_spreadsheets
                                    if s.get("id") == spreadsheet_id
                                ),
                                None,
                            )
                            spreadsheet_name = (
                                matching_sheet.get("name", spreadsheet_id)
                                if matching_sheet
                                else spreadsheet_id
                            )
                        else:
                            spreadsheet_name = spreadsheet_id
                    else:
                        spreadsheet_name = spreadsheet_id

                    # Convert to options format with unique keys
                    # Format: spreadsheet_id::sheet_name (using :: as separator)
                    options = [
                        {"value": f"{spreadsheet_id}::{name}", "label": name}
                        for name in sheet_names
                        if name
                    ]

                    if options:
                        grouped_results.append(
                            {"group": spreadsheet_name, "options": options}
                        )

                logger.info(f"Returning {len(grouped_results)} grouped sheet options")
                return grouped_results

            return []

        except Exception as e:
            logger.error(f"Failed to get Google Sheets options for {field_name}: {e}")
            return []

    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        config: Dict[str, Any],
    ) -> List[str]:
        """Register Google Sheets triggers with multi-select support."""
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            logger.error(f"Unknown Google Sheets trigger: {trigger_name}")
            return []

        composio = get_composio_service()

        # Parse comma-separated IDs
        spreadsheet_ids_str = config.get("spreadsheet_ids", "")
        spreadsheet_ids = (
            [s.strip() for s in spreadsheet_ids_str.split(",") if s.strip()]
            if spreadsheet_ids_str
            else []
        )

        sheet_names_str = config.get("sheet_names", "")
        sheet_names = (
            [s.strip() for s in sheet_names_str.split(",") if s.strip()]
            if sheet_names_str
            else []
        )

        # Register triggers for each combination
        trigger_ids = []
        spreadsheets_to_monitor = (
            spreadsheet_ids if spreadsheet_ids else [None]
        )  # None = all

        for spreadsheet_id in spreadsheets_to_monitor:
            # Skip if user is filtering by sheets but this spreadsheet has none selected
            # This handles the case where user selected spreadsheet but deselected all sheets
            if spreadsheet_id and sheet_names_str and not sheet_names:
                logger.info(
                    f"Skipping spreadsheet {spreadsheet_id} - sheet filtering active but no sheets selected"
                )
                continue

            if trigger_name == "google_sheets_new_row" and sheet_names:
                # Register for each sheet
                for sheet_name in sheet_names:
                    trigger_config: Dict[str, Any] = {}
                    if spreadsheet_id:
                        trigger_config["spreadsheet_id"] = spreadsheet_id
                    if sheet_name:
                        trigger_config["sheet_name"] = sheet_name

                    trigger_id = await self._register_single_trigger(
                        composio, user_id, composio_slug, trigger_config
                    )
                    if trigger_id:
                        trigger_ids.append(trigger_id)
            else:
                # Register for spreadsheet only
                trigger_config = (
                    {"spreadsheet_id": spreadsheet_id} if spreadsheet_id else {}
                )
                trigger_id = await self._register_single_trigger(
                    composio, user_id, composio_slug, trigger_config
                )
                if trigger_id:
                    trigger_ids.append(trigger_id)

        return trigger_ids

    async def _register_single_trigger(
        self,
        composio,
        user_id: str,
        composio_slug: str,
        trigger_config: Dict[str, Any],
    ) -> Optional[str]:
        """Register a single trigger with Composio."""
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
                return result.trigger_id

            return None

        except Exception as e:
            logger.error(f"Failed to register trigger {composio_slug}: {e}")
            return None

    async def unregister(self, user_id: str, trigger_ids: List[str]) -> bool:
        """Unregister Google Sheets triggers."""
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
                logger.info(f"Unregistered Google Sheets trigger: {trigger_id}")
            except Exception as e:
                logger.error(
                    f"Failed to unregister Google Sheets trigger {trigger_id}: {e}"
                )
                success = False

        return success

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: Dict[str, Any]
    ) -> List[Workflow]:
        """Find workflows matching a Google Sheets trigger event."""
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


google_sheets_trigger_handler = GoogleSheetsTriggerHandler()
