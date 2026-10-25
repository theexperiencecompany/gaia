"""Bot route for reporting a message a bot could not deliver.

Mounted on the shared /api/v1/bot prefix; the bot API key is the only credential.
"""

from fastapi import APIRouter, HTTPException, Request

from app.api.v1.endpoints.bot import require_bot_api_key
from app.schemas.delivery_failures import (
    DeliveryFailure,
    DeliveryFailureAccepted,
    DeliveryFailureReport,
)
from app.services.delivery_alerts.reporting import queue_delivery_failure
from shared.py.wide_events import log

router = APIRouter()


@router.post(
    "/delivery-failures",
    status_code=202,
    summary="Report Delivery Failure",
    description="Queue a message a bot could not deliver for the delivery-alerts channel.",
)
async def report_bot_delivery_failure(
    request: Request, body: DeliveryFailureReport
) -> DeliveryFailureAccepted:
    """Queue one undelivered bot message for Slack alerting."""
    await require_bot_api_key(request)
    log.set(
        operation="report_delivery_failure",
        delivery_failure={"kind": body.kind.value, "reason": body.reason},
    )
    if request.state.bot_platform != body.platform.value:
        raise HTTPException(
            status_code=403, detail="Platform in body does not match X-Bot-Platform header"
        )

    await queue_delivery_failure(
        DeliveryFailure(**body.model_dump(), reporter=f"{body.platform.value}-bot")
    )
    log.set_ns("delivery_failure", queued=True)
    return DeliveryFailureAccepted()
