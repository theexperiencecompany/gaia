"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.

Each handler implements its own `process_event()` method which handles:
- Finding matching workflows
- Queuing workflow execution via WorkflowQueueService
"""

import asyncio
from typing import Any

from shared.py.wide_events import log
from app.db.redis import redis_cache
from app.models.webhook_models import ComposioWebhookEvent
from app.services.triggers import get_handler_by_event
from app.utils.webhook_utils import verify_composio_webhook_signature
from fastapi import APIRouter, Request

router = APIRouter()

# Prevent GC of fire-and-forget tasks
_webhook_tasks: set[asyncio.Task[Any]] = set()

# Background tasks are cancelled after this many seconds to prevent indefinite hangs.
_WEBHOOK_TASK_TIMEOUT: float = 120.0


async def _process_webhook_event(
    handler: Any, event_data: ComposioWebhookEvent
) -> None:
    """Background task: find matching workflows and queue them."""
    try:
        await asyncio.wait_for(
            handler.process_event(
                event_type=event_data.type,
                trigger_id=event_data.trigger_id,
                user_id=event_data.user_id,
                data=event_data.data,
            ),
            timeout=_WEBHOOK_TASK_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error(
            f"Webhook background processing timed out after {_WEBHOOK_TASK_TIMEOUT}s "
            f"for {event_data.type}"
        )
    except Exception as e:
        log.error(f"Webhook background processing failed for {event_data.type}: {e}")


@router.post("/webhook/composio")
async def webhook_composio(request: Request) -> dict[str, str]:
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
            log.info(f"Duplicate webhook ignored: {webhook_id}")
            return {"status": "success", "message": "Duplicate webhook ignored"}

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
        log.debug(f"Unhandled webhook type: {event_data.type}")
        return {"status": "success", "message": "Webhook received"}

    # Fire-and-forget: return 200 immediately, process in background
    task = asyncio.create_task(_process_webhook_event(handler, event_data))
    _webhook_tasks.add(task)
    task.add_done_callback(_webhook_tasks.discard)

    log.set(operation="webhook_accepted", outcome="success")
    return {"status": "success", "message": "Webhook accepted"}
