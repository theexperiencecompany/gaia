"""
Google Sheets trigger handler with cascading dropdown support.
"""

import asyncio
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.composio_schemas import (
    GoogleSheetsGetSheetNamesData,
    GoogleSheetsGetSheetNamesInput,
    GoogleSheetsNewRowPayload,
    GoogleSheetsNewSheetAddedPayload,
    GoogleSheetsSearchSpreadsheetsData,
    GoogleSheetsSearchSpreadsheetsInput,
)
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
                # Use LangChain wrapper pattern
                tool = composio_service.get_tool(
                    "GOOGLESHEETS_SEARCH_SPREADSHEETS",
                    user_id=user_id,
                )
                if not tool:
                    logger.error("Google Sheets search spreadsheets tool not found")
                    return []

                # Invoke tool with typed input
                input_model = GoogleSheetsSearchSpreadsheetsInput(max_results=100)
                result: ToolExecutionResponse = await asyncio.to_thread(
                    tool.invoke,
                    input_model.model_dump(exclude_none=True, by_alias=True),
                )

                # Check response status
                if not result["successful"]:
                    logger.error(f"Google Sheets API error: {result['error']}")
                    return []

                # Extract and parse data
                data = GoogleSheetsSearchSpreadsheetsData.model_validate(result["data"])

                # Convert to options format with shared indicator
                options = []
                for sheet in data.spreadsheets:
                    if not sheet.id or not sheet.name:
                        continue

                    # Check if spreadsheet is shared (not owned by current user)
                    is_shared = sheet.shared or False
                    is_owned_by_me = (
                        any(o.me for o in sheet.owners) if sheet.owners else False
                    )

                    # Create label with shared indicator
                    label = sheet.name
                    if is_shared and not is_owned_by_me:
                        label = f"{sheet.name} (Shared)"

                    options.append({"value": sheet.id, "label": label})

                logger.info(
                    f"Returning {len(options)} Google Sheets spreadsheet options"
                )
                return options

            # Get sheets grouped by spreadsheet (cascading)
            elif field_name == "sheet_names" and parent_ids:
                tool = composio_service.get_tool(
                    "GOOGLESHEETS_GET_SHEET_NAMES",
                    user_id=user_id,
                )
                if not tool:
                    logger.error("Google Sheets get sheet names tool not found")
                    return []

                # Fetch sheet names for all spreadsheets in parallel
                async def fetch_sheets_for_spreadsheet(
                    spreadsheet_id: str,
                ) -> Dict[str, Any] | None:
                    """Fetch sheet names for a single spreadsheet."""
                    input_model = GoogleSheetsGetSheetNamesInput(
                        spreadsheet_id=spreadsheet_id
                    )
                    sheets_result: ToolExecutionResponse = await asyncio.to_thread(
                        tool.invoke,
                        input_model.model_dump(exclude_none=True, by_alias=True),
                    )

                    if not sheets_result["successful"]:
                        logger.error(
                            f"Failed to get sheet names for {spreadsheet_id}: "
                            f"{sheets_result['error']}"
                        )
                        return None

                    sheet_data = GoogleSheetsGetSheetNamesData.model_validate(
                        sheets_result["data"]
                    )
                    sheet_names = sheet_data.sheet_names

                    if not sheet_names:
                        return None

                    # Use spreadsheet_id as group name for now
                    options = [
                        {"value": f"{spreadsheet_id}::{name}", "label": name}
                        for name in sheet_names
                        if name
                    ]
                    return {"group": spreadsheet_id, "options": options}

                # Run all fetches in parallel
                results = await asyncio.gather(
                    *[fetch_sheets_for_spreadsheet(sid) for sid in parent_ids],
                    return_exceptions=True,
                )

                # Filter out None/errors and collect results
                grouped_results = [
                    r for r in results if isinstance(r, dict) and r is not None
                ]

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

        # Get config from trigger_data
        trigger_data = config.get("trigger_data", {})

        # Parse comma-separated IDs
        spreadsheet_ids_str = trigger_data.get("spreadsheet_ids", "")
        spreadsheet_ids = (
            [s.strip() for s in spreadsheet_ids_str.split(",") if s.strip()]
            if spreadsheet_ids_str
            else []
        )

        sheet_names_str = trigger_data.get("sheet_names", "")
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

            # optional: validate payload if it's a new row event
            # Validate payload
            try:
                if "new_row" in event_type.lower():
                    GoogleSheetsNewRowPayload.model_validate(data)
                elif "new_sheet" in event_type.lower():
                    GoogleSheetsNewSheetAddedPayload.model_validate(data)
            except Exception as e:
                logger.debug(f"Google Sheets payload validation failed: {e}")

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
