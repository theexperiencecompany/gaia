"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.

Each trigger handler implements its own `process_event()` method which handles:
- Finding matching workflows
- Queuing workflow execution via WorkflowQueueService

Connection-lifecycle events take a separate path: they carry none of the trigger
identifiers, and their only effect is pausing the workflows that needed the dead
integration and running the shared integration expiry transition.
"""

import asyncio
from typing import Any, cast

from composio.core.models.webhook_events import is_connection_expired_event
from fastapi import APIRouter, Request
from pydantic import ValidationError

from app.config.oauth_config import get_integration_by_config, get_integration_by_toolkit
from app.constants.integrations import (
    DEAD_CONNECTION_STATUSES,
    WEBHOOK_TASK_TIMEOUT,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.webhook_models import (
    ComposioConnectionEvent,
    ComposioWebhookAckResponse,
    ComposioWebhookEvent,
)
from app.services.integrations.integration_expiry import ExpiryOptions, expire_user_integration
from app.services.triggers import get_handler_by_event
from app.services.triggers.base import TriggerHandler
from app.services.workflow.integration_pause import pause_workflows_for_expired_integration
from app.utils.webhook_utils import verify_composio_webhook_signature
from shared.py.wide_events import log, spawn_logged_task

router = APIRouter()


async def _process_webhook_event(handler: TriggerHandler, event_data: ComposioWebhookEvent) -> None:
    """Background task: find matching workflows and queue them."""
    try:
        await asyncio.wait_for(
            handler.process_event(
                event_type=event_data.type,
                # Handlers match against trigger_config.composio_trigger_ids, which
                # stores the trigger NANO id (ti_...) returned by triggers.create().
                # Composio's webhook puts that nano id in `trigger_nano_id` and the
                # trigger's internal UUID in `trigger_id` — matching against the UUID
                # never hits, so forward the nano id (falling back to the UUID).
                trigger_id=event_data.trigger_nano_id or event_data.trigger_id,
                user_id=event_data.user_id,
                data=event_data.data,
            ),
            timeout=WEBHOOK_TASK_TIMEOUT,
        )
    except TimeoutError:
        log.error(
            f"{LogTag.COMPOSIO} Webhook background processing timed out",
            timeout_s=WEBHOOK_TASK_TIMEOUT,
            event_type=event_data.type,
            user_id=event_data.user_id,
        )
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Webhook background processing failed",
            event_type=event_data.type,
            user_id=event_data.user_id,
            error_type=type(e).__name__,
            error=str(e),
        )


async def _expire_connection(
    user_id: str, integration_id: str, reason: str | None, connected_account_id: str
) -> None:
    """Background task: pause the dependent workflows, then run the expiry transition.

    Pausing is the caller's job because ``integration_expiry`` cannot import the
    workflow layer without closing an import cycle (see its module docstring).
    Both steps share one timeout budget.
    """
    try:
        async with asyncio.timeout(WEBHOOK_TASK_TIMEOUT):
            paused = await pause_workflows_for_expired_integration(user_id, integration_id)
            await expire_user_integration(
                user_id,
                integration_id,
                ExpiryOptions(
                    reason=reason,
                    trigger="webhook",
                    notify=True,
                    connected_account_id=connected_account_id,
                    paused_workflows=paused,
                ),
            )
    except TimeoutError:
        log.error(
            f"{LogTag.COMPOSIO} Connection expiry processing timed out",
            timeout_s=WEBHOOK_TASK_TIMEOUT,
            user_id=user_id,
            integration_id=integration_id,
        )


def _handle_connection_event(body: dict[str, Any]) -> ComposioWebhookAckResponse:
    """Route a Composio connection-lifecycle event onto the shared expiry transition.

    Always acknowledges: an envelope GAIA cannot parse, an integration it does not
    recognise, or a status that is not terminal are all logged and dropped, because
    a non-200 makes Composio redeliver the same unusable event indefinitely.
    """
    # Confirms the delivered shape against the SDK TypedDicts without ever
    # touching `data.state`, which carries the account's access/refresh tokens.
    log.set_ns(
        "composio_connection",
        envelope_keys=sorted(body),
        data_keys=sorted(body["data"]) if isinstance(body.get("data"), dict) else None,
    )

    try:
        event = ComposioConnectionEvent.model_validate(body)
    except ValidationError as e:
        log.error(
            f"{LogTag.COMPOSIO} Unparseable connection event — dropped",
            event_type=body.get("type"),
            error_type=type(e).__name__,
            error=str(e),
        )
        return ComposioWebhookAckResponse(message="Connection event not understood")

    data = event.data
    integration = get_integration_by_config(data.auth_config.id) or get_integration_by_toolkit(
        data.toolkit.slug
    )
    log.set_ns(
        "composio_connection",
        connected_account_id=data.id,
        status=data.status,
        status_reason=data.status_reason,
        toolkit=data.toolkit.slug,
        auth_config_id=data.auth_config.id,
        integration_id=integration.id if integration else None,
    )
    log.set(user={"id": data.user_id})

    if integration is None:
        log.warning(
            f"{LogTag.COMPOSIO} Connection event for an unrecognised integration — dropped",
            toolkit=data.toolkit.slug,
            auth_config_id=data.auth_config.id,
        )
        return ComposioWebhookAckResponse(message="Unknown integration ignored")

    if data.status not in DEAD_CONNECTION_STATUSES:
        log.info(
            f"{LogTag.COMPOSIO} Connection event with a live status — no expiry",
            status=data.status,
            integration_id=integration.id,
        )
        return ComposioWebhookAckResponse(message="Connection status not terminal")

    spawn_logged_task(
        "composio_connection_expiry",
        _expire_connection(data.user_id, integration.id, data.status_reason, data.id),
        user={"id": data.user_id},
        webhook={"event_type": event.type, "integration_id": integration.id},
    )

    log.set(operation="webhook_accepted", outcome="success")
    return ComposioWebhookAckResponse(message="Connection event accepted")


@router.post("/webhook/composio")
async def webhook_composio(request: Request) -> ComposioWebhookAckResponse:
    """Handle incoming Composio webhooks — trigger messages and connection lifecycle.

    Routes events to the appropriate handler based on event type.
    Returns 200 immediately; workflow matching and queueing, and the connection
    expiry transition, happen in a fire-and-forget background task.
    """
    await verify_composio_webhook_signature(request)

    # pragma: no mutate — Starlette header lookup is case-insensitive, so a
    # case change to the header name is a provable no-op.
    webhook_id = request.headers.get("webhook-id", "")  # pragma: no mutate
    if webhook_id:
        already_processed = not await redis_cache.client.set(
            f"webhook:composio:{webhook_id}", "1", nx=True, ex=3600
        )
        if already_processed:
            log.info(f"{LogTag.COMPOSIO} Duplicate webhook ignored", webhook_id=webhook_id)
            return ComposioWebhookAckResponse(message="Duplicate webhook ignored")

    body = await request.json()

    # Branch on the RAW type. ComposioWebhookEvent's validator uppercases `type`,
    # so a parsed model can never match the SDK's lowercase event-name literal —
    # and connection events carry none of the trigger identifiers that model
    # requires as `str`, so constructing it first would raise before routing.
    if is_connection_expired_event(body):
        # The SDK type guard narrows to its ConnectionExpiredEvent TypedDict; the
        # handler re-validates the payload itself rather than trusting that shape.
        return _handle_connection_event(cast(dict[str, Any], body))

    if not isinstance(body, dict):
        # Composio only ever sends an object, so this is a malformed delivery.
        # Ack anyway: the dedupe key above is already claimed, so raising here
        # would have Composio redeliver a body it can never parse — and that
        # redelivery would then be swallowed as a duplicate.
        log.error(
            f"{LogTag.COMPOSIO} Webhook body is not a JSON object — dropped",
            body_type=type(body).__name__,
        )
        return ComposioWebhookAckResponse(message="Webhook body not understood")

    data = body.get("data")

    event_data = ComposioWebhookEvent(
        connection_id=data.get("connection_id"),
        connection_nano_id=data.get("connection_nano_id"),
        trigger_nano_id=data.get("trigger_nano_id"),
        trigger_id=data.get("trigger_id"),
        user_id=data.get("user_id"),
        data=data,
        timestamp=body.get("timestamp"),
        type=body.get("type"),
    )
    log.set(
        user={"id": event_data.user_id},
        webhook={"event_type": event_data.type, "trigger_id": event_data.trigger_id},
    )

    # Find handler for this event type
    handler = get_handler_by_event(event_data.type)
    if not handler:
        log.debug(f"{LogTag.COMPOSIO} Unhandled webhook type", event_type=event_data.type)
        return ComposioWebhookAckResponse(message="Webhook received")

    # Fire-and-forget: return 200 immediately, process in background
    spawn_logged_task(
        "composio_webhook_processing",
        _process_webhook_event(handler, event_data),
        user={"id": event_data.user_id},
        webhook={"event_type": event_data.type, "trigger_id": event_data.trigger_id},
    )

    log.set(operation="webhook_accepted", outcome="success")
    return ComposioWebhookAckResponse(message="Webhook accepted")
