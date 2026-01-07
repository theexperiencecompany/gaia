"""
Composio webhook endpoint.

Handles incoming webhooks from Composio and routes them to the appropriate handlers.
Uses the trigger registry for extensible event handling.
"""

from app.config.loggers import mail_webhook_logger as logger
from app.models.webhook_models import ComposioWebhookEvent
from app.services.mail.mail_webhook_service import queue_email_processing
from app.services.triggers import get_handler_by_event
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.webhook_utils import verify_composio_webhook_signature
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.post("/webhook/composio")
async def webhook_composio(request: Request):
    """Handle incoming Composio webhooks.

    Routes events to the appropriate handler based on event type.
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

    # Handle Gmail (special case - pre-existing behavior)
    if event_data.type == "GMAIL_NEW_GMAIL_MESSAGE":
        user_id = event_data.user_id
        if not user_id:
            logger.error("User ID is missing in Composio webhook")
            raise HTTPException(
                status_code=422,
                detail="User ID must be provided in webhook data.",
            )
        return await queue_email_processing(user_id, event_data.data)

    # Try to find a registered handler for this event type
    handler = get_handler_by_event(event_data.type)
    if handler:
        trigger_id = event_data.trigger_id
        if not trigger_id:
            logger.error(f"Trigger ID missing for event: {event_data.type}")
            raise HTTPException(
                status_code=422,
                detail="Trigger ID must be provided.",
            )

        # Find matching workflows using the handler
        workflows = await handler.find_workflows(
            event_data.type, trigger_id, event_data.data
        )

        if not workflows:
            logger.info(f"No matching workflows for trigger: {trigger_id}")
            return {"status": "success", "message": "No matching workflows"}

        # Queue execution for each matching workflow
        queued_count = 0
        for workflow in workflows:
            try:
                if workflow.id is None:
                    logger.error("Workflow has no id, skipping")
                    continue
                await WorkflowQueueService.queue_workflow_execution(
                    workflow.id,
                    workflow.user_id,
                    context={"trigger_data": event_data.data},
                )
                queued_count += 1
                logger.info(f"Queued workflow {workflow.id} for trigger {trigger_id}")
            except Exception as e:
                logger.error(f"Failed to queue workflow {workflow.id}: {e}")

        return {
            "status": "success",
            "message": f"Queued {queued_count} workflows",
        }

    # Unhandled event type
    logger.debug(f"Unhandled webhook type: {event_data.type}")
    return {"status": "success", "message": "Webhook received"}
