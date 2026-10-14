"""Test data factories for GAIA API tests."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from bson import ObjectId
from composio.types import Tool
import composio_client
from dodopayments.types import Subscription
import httpx

from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.models.user_models import AuthenticatedUser
from app.models.webhook_models import DodoPaymentData
from app.services.referrals.offer import ProPlans


def make_user_id() -> str:
    """Return a fresh GAIA user id: a real ObjectId, as UserId and every capture require."""
    return str(ObjectId())


def make_authenticated_user(**overrides: Any) -> AuthenticatedUser:
    """Build the request.state.user a signed-in test caller carries.

    Built as a WorkOS session; overrides are AuthenticatedUser fields.
    """
    defaults: dict[str, Any] = {
        "user_id": make_user_id(),
        "auth_provider": "workos",
        "email": "test@example.com",
        "name": "Test User",
        "created_at": datetime.now(UTC),
        "is_active": True,
    }
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def make_user(**overrides) -> dict:
    defaults = {
        "user_id": make_user_id(),
        "email": "test@example.com",
        "name": "Test User",
        "created_at": datetime.now(UTC).isoformat(),
        "is_active": True,
        "plan": "free",
        "onboarding_completed": True,
    }
    defaults.update(overrides)
    return defaults


def make_conversation(user_id: str | None = None, **overrides) -> dict:
    defaults = {
        "conversation_id": str(uuid4()),
        "user_id": user_id or make_user_id(),
        "description": "Test conversation",
        "messages": [],
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(overrides)
    return defaults


def make_state(**overrides) -> dict:
    """Build a dict-shaped agent state for tests.

    The compiled graph state is a plain dict (TypedDict) at runtime, so a dict
    with the messages channel plus a few representative extra keys is a faithful
    stand-in and exercises middleware passthrough of non-schema keys.
    """
    defaults = {
        "query": "Hello, how are you?",
        "messages": [],
        "current_datetime": datetime.now(UTC).isoformat(),
        "memory_user_id": str(uuid4()),
        "memories": [],
        "memories_stored": False,
        "conversation_id": str(uuid4()),
    }
    defaults.update(overrides)
    return defaults


def make_composio_tool(
    slug: str = "GMAIL_FETCH_MESSAGES",
    output_parameters: dict | None = None,
) -> Tool:
    """Build the minimum Composio tool descriptor wrap_tool needs."""
    return Tool(
        slug=slug,
        name=slug,
        description="Fetch messages.",
        # `title` is load-bearing: the wrapper builds a pydantic model class from
        # each schema and uses it as the class name.
        input_parameters={"type": "object", "title": "GmailFetchMessagesRequest", "properties": {}},
        output_parameters=output_parameters
        or {"type": "object", "title": "GmailFetchMessagesResponse", "properties": {}},
        toolkit={"slug": "gmail", "name": "Gmail", "logo": ""},
        tags=[],
        scopes=[],
        version="latest",
        available_versions=["latest"],
        # Mixed casing is the SDK's, not a typo: `displayName` is aliased while its
        # siblings are not.
        deprecated={
            "available_versions": ["latest"],
            "displayName": "Fetch messages",
            "is_deprecated": False,
            "toolkit": {"slug": "gmail", "name": "Gmail", "logo": ""},
            "version": "latest",
        },
        is_deprecated=False,
        no_auth=False,
    )


def make_tool_call(name: str, args: dict | None = None, call_id: str | None = None) -> dict:
    return {
        "name": name,
        "args": args or {},
        "id": call_id or f"call_{uuid4().hex[:24]}",
        "type": "tool_call",
    }


def make_config(
    user_id: str | None = None,
    thread_id: str | None = None,
    **overrides,
) -> dict:
    configurable = {
        "user_id": user_id or make_user_id(),
        "thread_id": thread_id or str(uuid4()),
    }
    configurable.update(overrides.pop("configurable", {}))
    config = {
        "configurable": configurable,
    }
    config.update(overrides)
    return config


def make_mcp_config(**overrides) -> dict:
    defaults = {
        "server_name": "test-mcp-server",
        "server_url": "http://localhost:8080",  # NOSONAR
        "transport": "sse",
        "enabled": True,
        "tools": [],
    }
    defaults.update(overrides)
    return defaults


def make_integration(provider: str, **overrides) -> dict:
    defaults = {
        "integration_id": str(uuid4()),
        "provider": provider,
        "user_id": make_user_id(),
        "status": "active",
        "credentials": {
            "access_token": f"test_token_{uuid4().hex[:8]}",
            "refresh_token": f"test_refresh_{uuid4().hex[:8]}",
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    defaults.update(overrides)
    return defaults


def make_integration_config(
    integration_id: str = "gmail",
    name: str = "Gmail",
    managed_by: str = "composio",
    associated_triggers: list | None = None,
    metadata_config: object | None = None,
):
    """Build a lightweight mock integration config object."""
    config = MagicMock()
    config.id = integration_id
    config.name = name
    config.managed_by = managed_by
    config.associated_triggers = associated_triggers or []
    config.metadata_config = metadata_config
    return config


def make_composio_not_found(body: object, message: str) -> composio_client.NotFoundError:
    """Build the 404 the Composio SDK raises, with its error body and message."""
    request = httpx.Request("POST", "https://backend.composio.dev/api/v3/tools/execute")
    return composio_client.NotFoundError(
        message, response=httpx.Response(404, request=request, json=body), body=body
    )


def make_plan(duration: PlanDuration, amount: int, currency: str = "USD") -> PlanResponse:
    """Build an active Pro plan whose Dodo product id is pdt_<duration>."""
    now = datetime(2026, 10, 14, tzinfo=UTC)
    return PlanResponse(
        id=f"plan_{duration.value}",
        dodo_product_id=f"pdt_{duration.value}",
        name="Pro",
        plan_type=PlanTier.PRO,
        amount=amount,
        currency=currency,
        duration=duration,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def make_pro_plans(monthly: int = 3000, yearly: int = 27000, currency: str = "USD") -> ProPlans:
    """Build the monthly and yearly Pro plans, priced in minor units of one currency."""
    return ProPlans(
        monthly=make_plan(PlanDuration.MONTHLY, monthly, currency),
        yearly=make_plan(PlanDuration.YEARLY, yearly, currency),
    )


def make_dodo_subscription(
    subscription_id: str, customer_id: str, next_billing_date: datetime
) -> Subscription:
    """Build an active monthly Pro subscription as Dodo's API returns it."""
    created = datetime(2026, 10, 14, tzinfo=UTC)
    return Subscription.model_validate(
        {
            "subscription_id": subscription_id,
            "product_id": "pdt_pro_monthly",
            "status": "active",
            "quantity": 1,
            "currency": "USD",
            "recurring_pre_tax_amount": 3000,
            "payment_frequency_count": 1,
            "payment_frequency_interval": "Month",
            "subscription_period_count": 1,
            "subscription_period_interval": "Year",
            "next_billing_date": next_billing_date,
            "previous_billing_date": created,
            "created_at": created,
            "metadata": {},
            "customer": {"customer_id": customer_id, "email": "x@example.com", "name": "X"},
            "billing": {"country": "US"},
            "addons": [],
            "meters": [],
            "cancel_at_next_billing_date": False,
            "on_demand": False,
            "tax_inclusive": False,
            "trial_period_days": 0,
        }
    )


def make_dodo_payment(
    *,
    user_id: str | None,
    email: str,
    amount: int = 1500,
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> DodoPaymentData:
    """Build a succeeded subscription payment webhook body; ids default to fresh random ones."""
    return DodoPaymentData.model_validate(
        {
            "payment_id": f"pay_{uuid4().hex}",
            "subscription_id": subscription_id or f"sub_friend_{uuid4().hex}",
            "business_id": "biz",
            "brand_id": "brand",
            "customer": {
                "customer_id": customer_id or f"cus_{uuid4().hex}",
                "email": email,
                "name": "Friend",
            },
            "billing": {"country": "US"},
            "currency": "USD",
            "total_amount": amount,
            "settlement_amount": amount,
            "settlement_currency": "USD",
            "tax": 0,
            "settlement_tax": 0,
            "status": "succeeded",
            "payment_method": "card",
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": {"user_id": user_id} if user_id else {},
        }
    )
