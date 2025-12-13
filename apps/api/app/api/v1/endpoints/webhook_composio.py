from app.config.loggers import mail_webhook_logger as logger
from app.models.webhook_models import ComposioWebhookEvent
from app.services.mail.mail_webhook_service import queue_email_processing
from app.utils.webhook_utils import verify_composio_webhook_signature
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.post(
    "/webhook/composio",
)
async def webhook_composio(
    request: Request,
):
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

    # Process specific webhook types
    if event_data.type == "GMAIL_NEW_GMAIL_MESSAGE":
        # Extract user_id from the webhook event
        user_id = event_data.user_id

        if not user_id:
            logger.error("User ID is missing in Composio webhook")
            raise HTTPException(
                status_code=422,
                detail="User ID must be provided in webhook data.",
            )

        # Queue email processing with Composio data
        return await queue_email_processing(user_id, event_data.data)

    # Log unhandled webhook types for monitoring
    return {"status": "success", "message": "Webhook received"}
