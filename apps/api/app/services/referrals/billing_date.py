"""Read and move a referrer's Dodo next_billing_date, mirroring each move onto the local row."""

import asyncio
from datetime import UTC, datetime

from app.models.webhook_models import DodoSubscriptionData
from app.services.payments.payment_service import payment_service
from app.services.payments.subscription_events import (
    SubscriptionEvent,
    SubscriptionEventKind,
    apply_subscription_event,
)
from shared.py.wide_events import log


async def live_billing_date(dodo_subscription_id: str) -> datetime:
    """Return the next charge date Dodo holds for this subscription now."""
    live = await asyncio.to_thread(
        payment_service.client.subscriptions.retrieve, dodo_subscription_id
    )
    return live.next_billing_date.astimezone(UTC)


async def set_billing_date(
    dodo_subscription_id: str, target: datetime, *, referrer_user_id: str, audit: str
) -> datetime:
    """Set the next charge to target in Dodo and locally; returns the date Dodo now holds."""
    updated = await asyncio.to_thread(
        payment_service.client.subscriptions.update,
        dodo_subscription_id,
        next_billing_date=target,
    )
    await apply_subscription_event(
        SubscriptionEvent(
            kind=SubscriptionEventKind.BILLING_DATE_MOVED,
            occurred_at=datetime.now(UTC),
            data=DodoSubscriptionData.model_validate(updated.model_dump(mode="json")),
        )
    )
    log.audit(audit, actor=referrer_user_id, resource=dodo_subscription_id, provider="dodo")
    return updated.next_billing_date.astimezone(UTC)
