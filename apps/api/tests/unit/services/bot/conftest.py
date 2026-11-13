"""Fixtures shared by the bot service tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.payment_models import (
    CreateSubscriptionResponse,
    PlanDuration,
    PlanResponse,
    PlanTier,
    ProCheckout,
)


@pytest.fixture
def make_checkout() -> Callable[[str], AsyncMock]:
    """Build a create_pro_checkout stand-in that returns a Dodo checkout with this link."""

    def build(payment_link: str) -> AsyncMock:
        return AsyncMock(
            return_value=ProCheckout(
                plan=PlanResponse(
                    id="plan_pro",
                    dodo_product_id="prod_pro",
                    name="Pro",
                    plan_type=PlanTier.PRO,
                    description=None,
                    amount=3000,
                    currency="USD",
                    duration=PlanDuration.MONTHLY,
                    max_users=None,
                    is_active=True,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                checkout=CreateSubscriptionResponse(
                    subscription_id="cs_1",
                    payment_link=payment_link,
                    status="payment_link_created",
                ),
            )
        )

    return build
