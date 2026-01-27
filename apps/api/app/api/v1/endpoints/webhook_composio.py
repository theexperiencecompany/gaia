"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.

Each handler implements its own `process_event()` method which handles:
- Finding matching workflows
- Queuing workflow execution via WorkflowQueueService
"""

from app.config.loggers import mail_webhook_logger as logger
from app.models.webhook_models import ComposioWebhookEvent
from app.services.triggers import get_handler_by_event
from app.utils.webhook_utils import verify_composio_webhook_signature
from fastapi import APIRouter, Request

router = APIRouter()


@router.post("/webhook/composio")
async def webhook_composio(request: Request):
    """Handle incoming Composio webhooks.

    Routes events to the appropriate handler based on event type.
    Each handler manages its own workflow matching and execution logic
    via its `process_event()` method.
    """
    await verify_composio_webhook_signature(request)
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

    # Find handler for this event type
    handler = get_handler_by_event(event_data.type)
    if not handler:
        logger.debug(f"Unhandled webhook type: {event_data.type}")
        return {"status": "success", "message": "Webhook received"}

    # Delegate all processing to the handler
    # Each handler decides how to find workflows and execute them:
    # - Default: find_workflows by trigger_id + WorkflowQueueService
    # - Gmail: queries by user_id instead of trigger_id
    return await handler.process_event(
        event_type=event_data.type,
        trigger_id=event_data.trigger_id,
        user_id=event_data.user_id,
        data=event_data.data,
    )
