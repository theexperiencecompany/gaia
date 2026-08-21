"""
Abstract base class for trigger handlers.

All provider-specific trigger handlers must extend this class.
"""

from abc import ABC, abstractmethod
import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any, Literal, TypedDict

from composio_client import APIStatusError

from app.constants.log_tags import LogTag
from app.models.trigger_config import TriggerOption, TriggerOptionGroup
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow
from app.services.composio.composio_service import get_composio_service
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.batching import buffer_trigger_event, coalesce_window_seconds
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.exceptions import TriggerRegistrationError
from shared.py.wide_events import TriggerContext, log


class TriggerEventResult(TypedDict):
    """What dispatching one webhook event reported.

    ``status`` is ``Literal["success"]`` because the dispatch genuinely has no
    failure return: a workflow that cannot be queued is logged and counted out of
    ``message``, never surfaced here. The webhook endpoint discards this value
    (the call is fire-and-forget), so it is an in-process contract, not a wire one.
    """

    status: Literal["success"]
    message: str


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
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _log_event_timing(data: dict[str, Any], now_utc: datetime) -> None:
    """Attach event-start and webhook-lag instrumentation to the log context."""
    event_start_utc = _parse_event_start_utc(data)
    if event_start_utc is None:
        return
    seconds_until_event = int((event_start_utc - now_utc).total_seconds())
    log.set(
        event_start_time_utc=event_start_utc.isoformat(),
        event_start_time_raw=data.get("start_time") or data.get("startTime"),
        seconds_until_event=seconds_until_event,
    )
    countdown = data.get("countdown_window_minutes")
    if not isinstance(countdown, int):
        return
    expected_fire = event_start_utc.timestamp() - countdown * 60
    webhook_lag = int(now_utc.timestamp() - expected_fire)
    log.set(
        countdown_window_minutes=countdown,
        webhook_lag_seconds=webhook_lag,
    )
    if abs(webhook_lag) > 300:
        log.warning(
            f"{LogTag.TRIGGER} webhook fired far from expected time — lag=s (positive = late, negative = early)",
            webhook_lag=webhook_lag,
        )


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

    @property
    @abstractmethod
    def event_types(self) -> set[str]:
        """Return Composio event types this handler processes.

        These are the webhook event types from Composio (e.g., 'GOOGLECALENDAR_...')
        """

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
            component="trigger_handler",
            operation="unregister",
            user_id=user_id,
            trigger_count=len(trigger_ids),
            trigger=TriggerContext(operation="delete", result_count=len(trigger_ids)),
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
                log.debug(f"{LogTag.TRIGGER} Deleted trigger", trigger_id=trigger_id)
            except Exception as e:
                # Composio answers 410 Gone when the trigger instance is already
                # deleted — the desired end-state, so treat it as a no-op.
                if isinstance(e, APIStatusError) and e.status_code == HTTPStatus.GONE:
                    log.debug(
                        f"{LogTag.TRIGGER} Trigger already gone on Composio, skipping",
                        trigger_id=trigger_id,
                        user_id=user_id,
                    )
                    continue
                log.error(
                    f"{LogTag.TRIGGER} Failed to delete trigger",
                    trigger_id=trigger_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    user_id=user_id,
                )
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
                log.error(
                    f"{LogTag.TRIGGER} Trigger registration failed for",
                    config_desc=config_desc,
                    result=result,
                    user_id=user_id,
                )
            elif result is not None:
                successful_ids.append(result)

        # If any failed, rollback all successful ones
        if has_failure:
            if successful_ids:
                log.warning(
                    f"{LogTag.TRIGGER} Rolling back triggers due to partial failure",
                    successful_ids_count=len(successful_ids),
                    user_id=user_id,
                )
                rollback_ok = await self.unregister(user_id, successful_ids)
                if not rollback_ok:
                    log.error(
                        f"{LogTag.TRIGGER} Rollback FAILED — orphaned Composio triggers: . Manual cleanup may be required.",
                        successful_ids=successful_ids,
                        user_id=user_id,
                    )

            raise TriggerRegistrationError(
                f"Failed to register all {trigger_name} triggers: {failure_message}",
                trigger_name,
                partial_ids=successful_ids,
            )

        return successful_ids

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

    async def get_config_options(
        self,
        trigger_name: str,
        field_name: str,
        user_id: str,
        integration_id: str,
        parent_ids: list[str] | None = None,
        **_kwargs: str,
    ) -> Sequence[TriggerOption | TriggerOptionGroup]:
        """Get dynamic options for a trigger configuration field.

        Optional method for handlers to provide dropdown options for
        configuration fields (e.g., list of channels, boards, repos).

        Supports cascading dropdowns by accepting parent_ids to filter children.

        ``Sequence`` (not ``list``) because ``list`` is invariant: handlers that
        only ever produce flat options override this returning
        ``list[TriggerOption]``.

        Args:
            trigger_name: The trigger slug (e.g., 'slack_new_message')
            field_name: The config field name (e.g., 'channel_id')
            user_id: The user ID
            integration_id: The integration ID (e.g., 'slack')
            parent_ids: Parent IDs for cascading options (e.g., workspace IDs)

        Returns:
            Flat options, or ``TriggerOptionGroup``s for cascading dropdowns.
            Empty when no dynamic options are available.
        """
        return []

    async def process_event(
        self,
        event_type: str,
        trigger_id: str | None,
        user_id: str | None,
        data: dict[str, Any],
    ) -> TriggerEventResult:
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
        trigger_ctx = TriggerContext(operation="dispatch", trigger_type=event_type)
        if trigger_id:
            trigger_ctx["trigger_id"] = trigger_id
        log.set(
            component="trigger_handler",
            operation="process_event",
            event_type=event_type,
            trigger_id=trigger_id,
            user_id=user_id,
            now_utc=now_utc.isoformat(),
            trigger=trigger_ctx,
        )

        _log_event_timing(data, now_utc)

        # Find matching workflows using handler's find_workflows method
        # Each handler decides what identifiers it needs (trigger_id, user_id, etc.)
        workflows = await self.find_workflows(event_type, trigger_id or "", data)
        log.set_ns("trigger", matched_count=len(workflows))

        if not workflows:
            log.set_ns("trigger", fired=False)
            log.info(
                "trigger_no_matching_workflows",
                outcome="no_match",
                event_type=event_type,
                trigger_id=trigger_id,
            )
            return TriggerEventResult(status="success", message="No matching workflows")

        # Queue execution for each matching workflow.
        # Tracked-todo signal context is identical for a given user, so compute
        # it once per user_id and reuse — avoids repeated Mongo + VFS reads when
        # multiple workflows for the same user match one event.
        queued_count = 0
        signal_context_by_user: dict[str, str] = {}
        for workflow in workflows:
            if await self._queue_one_workflow(
                workflow, data, signal_context_by_user, event_type, trigger_id
            ):
                queued_count += 1

        log.set_ns("trigger", fired=queued_count > 0, result_count=queued_count)

        return TriggerEventResult(status="success", message=f"Queued {queued_count} workflows")

    async def _queue_one_workflow(
        self,
        workflow: Workflow,
        data: dict[str, Any],
        signal_context_by_user: dict[str, str],
        event_type: str,
        trigger_id: str | None,
    ) -> bool:
        """Queue a single matched workflow. Returns True if it was queued."""
        try:
            if workflow.id is None:
                log.error(
                    "trigger_workflow_missing_id",
                    event_type=event_type,
                    trigger_id=trigger_id,
                )
                return False
            # Enrich context with tracked todos for signal matching. The
            # trigger_type stamp is what lets the worker tell this run apart
            # from a user's manual "run now" (unstamped, it defaulted to
            # "manual" and was mislabeled in analytics and origin handling).
            context: dict[str, Any] = {"trigger_type": TriggerType.INTEGRATION.value}
            if workflow.user_id not in signal_context_by_user:
                try:
                    signal_context_by_user[
                        workflow.user_id
                    ] = await tracked_todo_service.get_signal_matching_context(workflow.user_id)
                except Exception as e:
                    log.warning(
                        "trigger.signal_context_fetch_failed",
                        user_id=workflow.user_id,
                        error=str(e),
                    )
                    signal_context_by_user[workflow.user_id] = ""
            todos_context = signal_context_by_user[workflow.user_id]
            if todos_context:
                context["tracked_todos_context"] = todos_context

            # A poll-based trigger fires once per item Composio found, so its
            # events are batched into one run instead of one run each. Triggers
            # with no declared interval stay immediate — a meeting reminder held
            # back for its window is a missed meeting.
            window_seconds = coalesce_window_seconds(workflow.trigger_config)
            if window_seconds > 0 and await buffer_trigger_event(
                workflow.id, workflow.user_id, data, window_seconds, context
            ):
                return True

            await WorkflowQueueService.queue_workflow_execution(
                workflow.id,
                workflow.user_id,
                context={**context, "trigger_data": data},
            )
            log.info(
                "trigger_workflow_queued",
                workflow_id=workflow.id,
                user_id=workflow.user_id,
                event_type=event_type,
                trigger_id=trigger_id,
            )
            return True
        except Exception as e:
            log.error(
                "trigger_workflow_queue_failed",
                workflow_id=workflow.id,
                user_id=workflow.user_id,
                event_type=event_type,
                trigger_id=trigger_id,
                error_type=type(e).__name__,
                error=str(e),
                exc_info=True,
            )
            return False
