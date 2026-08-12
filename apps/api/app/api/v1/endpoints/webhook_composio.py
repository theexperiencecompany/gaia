"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.

Each handler implements its own `process_event()` method which handles:
- Finding matching workflows
- Queuing workflow execution via WorkflowQueueService
"""

import asyncio

from fastapi import APIRouter, Request

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.webhook_models import ComposioWebhookAckResponse, ComposioWebhookEvent
from app.services.triggers import get_handler_by_event
from app.services.triggers.base import TriggerHandler
from app.utils.webhook_utils import verify_composio_webhook_signature
from shared.py.wide_events import log, spawn_logged_task

router = APIRouter()

# Background tasks are cancelled after this many seconds to prevent indefinite hangs.
_WEBHOOK_TASK_TIMEOUT: float = 120.0


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
            timeout=_WEBHOOK_TASK_TIMEOUT,
        )
    except TimeoutError:
        log.error(
            f"{LogTag.COMPOSIO} Webhook background processing timed out",
            timeout_s=_WEBHOOK_TASK_TIMEOUT,
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


@router.post("/webhook/composio")
async def webhook_composio(request: Request) -> ComposioWebhookAckResponse:
    """Handle incoming Composio webhooks.

    Routes events to the appropriate handler based on event type.
    Returns 200 immediately; workflow matching and queueing happen
    in a fire-and-forget background task.
    """
    await verify_composio_webhook_signature(request)

    webhook_id = request.headers.get("webhook-id", "")
    if webhook_id:
        already_processed = not await redis_cache.client.set(
            f"webhook:composio:{webhook_id}", "1", nx=True, ex=3600
        )
        if already_processed:
            log.info(f"{LogTag.COMPOSIO} Duplicate webhook ignored", webhook_id=webhook_id)
            return ComposioWebhookAckResponse(message="Duplicate webhook ignored")

    body = await request.json()
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
