"""
Abstract base class for trigger handlers.

All provider-specific trigger handlers must extend this class.
"""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import TriggerConfig, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import log


def _parse_event_start_utc(data: dict[str, Any]) -> datetime | None:
    """Best-effort extraction of an event's start time as a UTC datetime.

    Handles Composio/Google payloads that may ship `start_time` as an ISO-8601
    string with or without offset. Returns None when the field is absent or
    unparseable — callers should skip lag instrumentation in that case.
    """
    raw = data.get("start_time") or data.get("startTime")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class TriggerHandler(ABC):
    """Abstract base for all trigger handlers.

    Each provider (calendar, gmail, github, etc.) implements this interface
    to handle registration, unregistration, and webhook processing.
    """

    @property
    @abstractmethod
    def trigger_names(self) -> list[str]:
        """Return supported trigger names (e.g., ['calendar_event_created']).

        These are the values stored in trigger_data.trigger_name.
        """
        pass

    @property
    @abstractmethod
    def event_types(self) -> set[str]:
        """Return Composio event types this handler processes.

        These are the webhook event types from Composio (e.g., 'GOOGLECALENDAR_...')
        """
        pass

    @abstractmethod
    async def register(
        self,
        user_id: str,
        workflow_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
    ) -> list[str]:
        """Register triggers for a workflow.

        Args:
            user_id: The user ID
            workflow_id: The workflow ID
            trigger_name: The trigger name (e.g., 'calendar_event_created')
            trigger_config: The complete TriggerConfig with typed trigger_data

        Returns:
            List of Composio trigger IDs that were registered
        """
        pass

    async def unregister(self, user_id: str, trigger_ids: list[str]) -> bool:
        """Unregister triggers when workflow is deleted/deactivated.

        Default implementation uses Composio triggers.delete API.
        Override if provider needs custom logic.

        Args:
            user_id: The user ID
            trigger_ids: List of Composio trigger IDs to unregister

        Returns:
            True if all triggers were unregistered successfully
        """
        log.set(
            service="trigger_handler",
            operation="unregister",
            user_id=user_id,
            trigger_count=len(trigger_ids),
        )
        if not trigger_ids:
            return True

        success = True
        composio = get_composio_service()

        for trigger_id in trigger_ids:
            try:
                await asyncio.to_thread(
                    composio.composio.triggers.delete,
                    trigger_id=trigger_id,
                )
                log.debug(f"Deleted trigger: {trigger_id}")
            except Exception as e:
                log.error(f"Failed to delete trigger {trigger_id}: {e}")
                success = False

        return success

    async def _register_triggers_parallel(
        self,
        user_id: str,
        trigger_name: str,
        configs: list[dict[str, Any]],
        composio_slug: str,
        config_description_fn: Callable[[dict[str, Any]], str] | None = None,
    ) -> list[str]:
        """Register multiple triggers in parallel with automatic rollback on failure.

        This is a reusable helper for handlers that create multiple triggers.
        If any registration fails, all successful ones are rolled back.

        Args:
            user_id: The user ID
            trigger_name: The trigger name (for error messages)
            configs: List of Composio trigger configs to register
            composio_slug: The Composio trigger slug
            config_description_fn: Optional function to describe a config for logging

        Returns:
            List of registered trigger IDs (only if ALL succeed)

        Raises:
            TriggerRegistrationError: If any registration fails
        """

        if not configs:
            return []

        composio = get_composio_service()

        async def register_single(config: dict[str, Any]) -> str | None:
            """Register a single trigger and return trigger_id."""
            result = await asyncio.to_thread(
                composio.composio.triggers.create,
                user_id=user_id,
                slug=composio_slug,
                trigger_config=config,
            )
            if result and hasattr(result, "trigger_id"):
                return result.trigger_id
            return None

        # Execute all registrations in parallel
        results = await asyncio.gather(
            *[register_single(cfg) for cfg in configs],
            return_exceptions=True,
        )

        # Collect results and check for failures
        successful_ids: list[str] = []
        has_failure = False
        failure_message = ""

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                has_failure = True
                failure_message = str(result)
                config_desc = (
                    config_description_fn(configs[i]) if config_description_fn else str(configs[i])
                )
                log.error(f"Trigger registration failed for {config_desc}: {result}")
            elif result is not None:
                successful_ids.append(result)

        # If any failed, rollback all successful ones
        if has_failure:
            if successful_ids:
                log.warning(f"Rolling back {len(successful_ids)} triggers due to partial failure")
                rollback_ok = await self.unregister(user_id, successful_ids)
                if not rollback_ok:
                    log.error(
                        f"Rollback FAILED — orphaned Composio triggers: {successful_ids}. "
                        "Manual cleanup may be required."
                    )

            raise TriggerRegistrationError(
                f"Failed to register all {trigger_name} triggers: {failure_message}",
                trigger_name,
                partial_ids=successful_ids,
            )

        return successful_ids

    async def _load_workflows_from_query(
        self, query: dict[str, Any], log_context: str
    ) -> list[Workflow]:
        """Load and validate workflows for a MongoDB query."""
        workflows: list[Workflow] = []
        cursor = workflows_collection.find(query)
        async for workflow_doc in cursor:
            try:
                workflow_doc["id"] = workflow_doc.get("_id")
                if "_id" in workflow_doc:
                    del workflow_doc["_id"]
                workflows.append(Workflow(**workflow_doc))
            except Exception as e:
                log.error(f"Error processing workflow document ({log_context}): {e}")

        return workflows

    @abstractmethod
    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, Any]
    ) -> list[Workflow]:
        """Find workflows that match an incoming webhook event.

        Args:
            event_type: The Composio event type
            trigger_id: The Composio trigger ID from the webhook
            data: The webhook payload data

        Returns:
            List of workflows to execute
        """
        pass

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, str]]:
        """Get dynamic options for a trigger configuration field.

        Optional method for handlers to provide dropdown options for
        configuration fields (e.g., list of channels, boards, repos).

        Supports cascading dropdowns by accepting parent_ids to filter children.

        Args:
            trigger_name: The trigger slug (e.g., 'slack_new_message')
            field_name: The config field name (e.g., 'channel_id')
            user_id: The user ID
            integration_id: The integration ID (e.g., 'slack')
            parent_ids: Parent IDs for cascading options (e.g., workspace IDs)

        Returns:
            List of options as [{"value": "...", "label": "..."}]
            For grouped options: [{"group": "...", "options": [...]}]
            Empty list if no dynamic options available
        """
        return []

    async def process_event(
        self,
        event_type: str,
        trigger_id: str | None,
        user_id: str | None,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Process an incoming webhook event and queue matching workflows.

        Default implementation:
        1. Finds workflows using handler's find_workflows method
        2. Queues each workflow for execution via WorkflowQueueService

        Each handler's find_workflows() determines how to match workflows:
        - Most handlers match by trigger_id (stored in composio_trigger_ids)
        - Gmail matches by user_id (account-level triggers)

        Args:
            event_type: The Composio event type (e.g., 'GMAIL_NEW_GMAIL_MESSAGE')
            trigger_id: The Composio trigger ID from the webhook (may be None)
            user_id: User ID from webhook metadata (may be None)
            data: The complete webhook payload data

        Returns:
            Dict with 'status' and 'message' keys
        """
        now_utc = datetime.now(UTC)
        log.set(
            service="trigger_handler",
            operation="process_event",
            event_type=event_type,
            trigger_id=trigger_id,
            user_id=user_id,
            now_utc=now_utc.isoformat(),
        )

        event_start_utc = _parse_event_start_utc(data)
        if event_start_utc is not None:
            seconds_until_event = int((event_start_utc - now_utc).total_seconds())
            log.set(
                event_start_time_utc=event_start_utc.isoformat(),
                event_start_time_raw=data.get("start_time") or data.get("startTime"),
                seconds_until_event=seconds_until_event,
            )
            countdown = data.get("countdown_window_minutes")
            if isinstance(countdown, int):
                expected_fire = event_start_utc.timestamp() - countdown * 60
                webhook_lag = int(now_utc.timestamp() - expected_fire)
                log.set(
                    countdown_window_minutes=countdown,
                    webhook_lag_seconds=webhook_lag,
                )
                if abs(webhook_lag) > 300:
                    log.warning(
                        "webhook fired far from expected time — "
                        f"lag={webhook_lag}s (positive = late, negative = early)",
                    )

        # Find matching workflows using handler's find_workflows method
        # Each handler decides what identifiers it needs (trigger_id, user_id, etc.)
        workflows = await self.find_workflows(event_type, trigger_id or "", data)

        if not workflows:
            log.info(f"No matching workflows for event: {event_type}")
            return {"status": "success", "message": "No matching workflows"}

        # Queue execution for each matching workflow
        queued_count = 0
        for workflow in workflows:
            try:
                if workflow.id is None:
                    log.error("Workflow has no id, skipping")
                    continue
                await WorkflowQueueService.queue_workflow_execution(
                    workflow.id,
                    workflow.user_id,
                    context={"trigger_data": data},
                )
                queued_count += 1
                log.info(f"Queued workflow {workflow.id} for event {event_type}")
            except Exception as e:
                log.error(f"Failed to queue workflow {workflow.id}: {e}")

        return {
            "status": "success",
            "message": f"Queued {queued_count} workflows",
        }
