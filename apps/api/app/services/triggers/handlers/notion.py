"""
Notion trigger handler.

Handles Notion-specific trigger logic.
"""

import asyncio
from typing import Any, ClassVar, Literal

from app.constants.log_tags import LogTag
from app.db.repositories.workflows import workflow_repository
from app.models.composio_schemas import (
    NotionAllPageEventsPayload,
    NotionFetchDataData,
    NotionFetchDataInput,
    NotionPageAddedPayload,
    NotionPageUpdatedPayload,
)
from app.models.trigger_config import TriggerOption
from app.models.trigger_configs import (
    NotionAllPageEventsConfig,
    NotionNewPageInDbConfig,
    NotionPageUpdatedConfig,
)
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.triggers.base import TriggerHandler
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import log


class NotionTriggerHandler(TriggerHandler):
    """Handler for Notion triggers."""

    SUPPORTED_TRIGGERS: ClassVar[list[str]] = [
        "notion_new_page_in_db",
        "notion_page_updated",
        "notion_all_page_events",
    ]

    SUPPORTED_EVENTS: ClassVar[set[str]] = {
        "NOTION_PAGE_ADDED_TO_DATABASE",
        "NOTION_PAGE_UPDATED_TRIGGER",
        "NOTION_ALL_PAGE_EVENTS_TRIGGER",
    }

    TRIGGER_TO_COMPOSIO: ClassVar[dict[str, str]] = {
        "notion_new_page_in_db": "NOTION_PAGE_ADDED_TO_DATABASE",
        "notion_page_updated": "NOTION_PAGE_UPDATED_TRIGGER",
        "notion_all_page_events": "NOTION_ALL_PAGE_EVENTS_TRIGGER",
    }

    @property
    def trigger_names(self) -> list[str]:
        return self.SUPPORTED_TRIGGERS

    @property
    def event_types(self) -> set[str]:
        return self.SUPPORTED_EVENTS

    async def get_config_options(
        self,
        trigger_name: str,  # noqa: ARG002 -- framework contract
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: list[str] | None = None,  # noqa: ARG002 -- framework contract
        **kwargs: str,
    ) -> list[TriggerOption]:
        """Get dynamic options for Notion trigger config fields."""
        try:
            composio_service = get_composio_service()

            # Use NOTION_FETCH_DATA tool
            tool = composio_service.get_tool("NOTION_FETCH_DATA", user_id=user_id)
            if not tool:
                log.error(f"{LogTag.TRIGGER} Notion FETCH_DATA tool not found")
                return []

            # Determine fetch_type based on field_name
            fetch_type: Literal["pages", "databases", "all"]
            if field_name == "database_id":
                fetch_type = "databases"
            elif field_name == "page_id":
                fetch_type = "pages"
            else:
                log.warning(
                    f"{LogTag.TRIGGER} Unknown Notion field, fetching all",
                    field_name=field_name,
                    user_id=user_id,
                    integration_id=integration_id,
                )
                fetch_type = "all"

            # Invoke tool with typed input
            input_model = NotionFetchDataInput(
                fetch_type=fetch_type,
                page_size=100,
                query=kwargs.get("search"),
            )

            log.debug(
                f"{LogTag.TRIGGER} Notion fetch input",
                input_fields=sorted(input_model.model_dump().keys()),
            )

            result = await asyncio.to_thread(tool.invoke, input_model.model_dump(exclude_none=True))

            if not result["successful"]:
                log.error(
                    f"{LogTag.TRIGGER} Notion API error",
                    error=result["error"],
                    user_id=user_id,
                    integration_id=integration_id,
                )
                return []

            # Extract and parse data
            data = NotionFetchDataData.model_validate(result["data"])
            items = data.get_items()
            options = []

            for item in items:
                if not item.id:
                    continue

                label = item.title or "Untitled"
                options.append(TriggerOption(value=item.id, label=label))

            log.info(
                f"{LogTag.TRIGGER} Returning Notion options",
                options_count=len(options),
                field_name=field_name,
            )
            return options

        except Exception as e:
            log.error(
                f"{LogTag.TRIGGER} Failed to get Notion options for",
                field_name=field_name,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
                integration_id=integration_id,
            )
            return []

    async def register(
        self,
        user_id: str,
        _workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> list[str]:
        """Register Notion triggers with parallel execution and rollback.

        If any trigger registration fails, all successfully created triggers
        are rolled back to maintain atomicity.

        Raises:
            TriggerRegistrationError: If any trigger registration fails
        """
        composio_slug = self.TRIGGER_TO_COMPOSIO.get(trigger_name)
        if not composio_slug:
            raise TriggerRegistrationError(
                f"Unknown Notion trigger: {trigger_name}",
                trigger_name,
            )

        trigger_data = trigger_config.trigger_data

        # Build list of configs to register based on trigger type
        configs: list[dict[str, Any]] = []

        if trigger_name == "notion_new_page_in_db":
            if not isinstance(trigger_data, NotionNewPageInDbConfig):
                raise TypeError(
                    f"Expected NotionNewPageInDbConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            database_ids = trigger_data.database_ids

            if not database_ids:
                log.warning(f"{LogTag.TRIGGER} No database IDs provided for notion_new_page_in_db")
                return []

            for database_id in database_ids:
                configs.append({"database_id": database_id})

        elif trigger_name == "notion_page_updated":
            if not isinstance(trigger_data, NotionPageUpdatedConfig):
                raise TypeError(
                    f"Expected NotionPageUpdatedConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__ if trigger_data else 'None'}"
                )
            page_ids = trigger_data.page_ids

            if not page_ids:
                log.warning(f"{LogTag.TRIGGER} No page IDs provided for notion_page_updated")
                return []

            for page_id in page_ids:
                configs.append({"page_id": page_id})

        elif trigger_name == "notion_all_page_events":
            if trigger_data is not None and not isinstance(trigger_data, NotionAllPageEventsConfig):
                raise TypeError(
                    f"Expected NotionAllPageEventsConfig for trigger '{trigger_name}', "
                    f"but got {type(trigger_data).__name__}"
                )
            configs.append({})

        else:
            raise TriggerRegistrationError(
                f"Unknown Notion trigger: {trigger_name}",
                trigger_name,
            )

        # Use the base class helper for parallel registration with rollback
        return await self._register_triggers_parallel(
            user_id=user_id,
            trigger_name=trigger_name,
            configs=configs,
            composio_slug=composio_slug,
        )

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, Any]
    ) -> list[Workflow]:
        """Find workflows matching a Notion trigger event."""
        log.set_ns("trigger", integration_id="notion", trigger_type=event_type)
        try:
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
                log.debug(
                    f"{LogTag.TRIGGER} Notion payload validation failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )

            # Match by specific trigger ID since these are manually registered
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


notion_trigger_handler = NotionTriggerHandler()
