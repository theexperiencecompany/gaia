"""Subscription tools — read the user's billing state and hand them an upgrade link.

Both tools read the live billing system rather than the agent's context, because
plan and price are the two facts GAIA must never guess about: telling a paying
customer they are on Free, or quoting a price that moved, is the kind of wrong
answer people screenshot.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.log_tags import LogTag
from app.constants.payments import NO_USER_MESSAGE
from app.decorators import with_doc
from app.models.agent_models import agent_configurable
from app.models.payment_models import PlanDuration, SubscriptionDetails
from app.services.payments.payment_service import payment_service
from app.templates.docstrings.subscription_tool_docs import (
    CREATE_UPGRADE_LINK,
    GET_SUBSCRIPTION_DETAILS,
)
from shared.py.wide_events import log


def _format_money(amount_minor: int, currency: str) -> str:
    """Render a minor-unit amount (Dodo's wire format) as ``30.00 USD``."""
    return f"{amount_minor / 100:.2f} {currency.upper()}"


def _format_details(details: SubscriptionDetails) -> str:
    lines = [f"Plan: {details.plan_name or details.plan_type.value.capitalize()}"]

    if not details.is_subscribed:
        lines.append("Subscribed: no — this user is on the free tier.")
        return "\n".join(lines)

    lines.append(
        f"Subscribed: yes (status: {details.status.value if details.status else 'unknown'})"
    )
    if details.amount is not None and details.currency:
        cycle = (
            f" per {details.billing_cycle.value.removesuffix('ly')}"
            if details.billing_cycle
            else ""
        )
        lines.append(f"Price: {_format_money(details.amount, details.currency)}{cycle}")
    if details.next_billing_date:
        renews = "Cancels on" if details.cancel_at_next_billing_date else "Renews on"
        lines.append(f"{renews}: {details.next_billing_date}")
    if details.cancel_at_next_billing_date:
        lines.append(
            "Cancellation is scheduled — Pro access continues until the date above, "
            "then the account returns to Free."
        )

    if details.payments:
        lines.append(f"Recent charges ({len(details.payments)}):")
        lines.extend(
            f"  - {payment.created_at.date()} "
            f"{_format_money(payment.amount, payment.currency)} "
            f"({payment.status or 'unknown'})"
            for payment in details.payments
        )
    else:
        lines.append("Recent charges: none recorded yet.")

    return "\n".join(lines)


@tool
@with_doc(GET_SUBSCRIPTION_DETAILS)
async def get_subscription_details(config: RunnableConfig) -> str:
    user_id = agent_configurable(config).get("user_id")
    if not user_id:
        return NO_USER_MESSAGE

    details = await payment_service.get_subscription_details(user_id)
    log.set(
        tool={"name": "get_subscription_details"},
        payment={
            "operation": "agent_status_read",
            "plan_type": details.plan_type.value,
            "payment_count": len(details.payments),
        },
    )
    return _format_details(details)


@tool
@with_doc(CREATE_UPGRADE_LINK)
async def create_upgrade_link(
    config: RunnableConfig,
    billing_cycle: Annotated[
        PlanDuration, "Billing cycle for the subscription: monthly (default) or yearly"
    ] = PlanDuration.MONTHLY,
) -> str:
    user_id = agent_configurable(config).get("user_id")
    if not user_id:
        return NO_USER_MESSAGE

    log.set(tool={"name": "create_upgrade_link"})

    status = await payment_service.get_user_subscription_status(user_id)
    if status.is_subscribed:
        return (
            "This user is already on GAIA Pro — no checkout needed. "
            "Tell them that instead of sending a payment link."
        )

    pro = await payment_service.create_pro_checkout(user_id, billing_cycle)
    checkout = pro.checkout
    if not checkout.payment_link:
        raise RuntimeError("Dodo returned a checkout session without a payment link")

    # Issued, not attempted: the event only fires once a link actually exists.
    log.set(payment={"operation": "agent_upgrade_link", "billing_cycle": billing_cycle})
    log.audit(
        "upgrade checkout link issued",
        actor=user_id,
        payment={"operation": "agent_upgrade_link"},
    )
    log.info(f"{LogTag.TOOL} Upgrade link created", billing_cycle=billing_cycle)

    period = billing_cycle.value.removesuffix("ly")
    lines = [f"GAIA Pro — {_format_money(pro.plan.amount, pro.plan.currency)} per {period}."]
    if pro.plan.features:
        # Straight from the plan catalogue, so the pitch can never promise
        # something the plan stopped including.
        lines.append("Includes: " + "; ".join(pro.plan.features))
    lines.append(f"Checkout link (already tied to this user's account): {checkout.payment_link}")
    lines.append("Give them the link as-is. It stays valid for about an hour.")
    return "\n".join(lines)


tools = [get_subscription_details, create_upgrade_link]
