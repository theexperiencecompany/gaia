"""Referral tools: the user's invite link and gift, how sharing is going, who to invite, and email invites.

Every price and link is read from the referral services, which price the gift
from the live Pro catalogue, so the agent never quotes a number it guessed.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import (
    FORWARD_RECIPIENT_FALLBACK,
    FORWARDABLE_INVITE_TEMPLATE,
    SEND_REFERRAL_INVITE_TOOL,
    SHARE_TEXT_TEMPLATE,
)
from app.decorators import with_doc
from app.models.agent_models import agent_configurable, get_user_id, runs_on_bot
from app.models.referral_models import (
    ReferralInviteStatus,
    ReferralInviteSurface,
    ReferredFriendStatus,
)
from app.schemas.referrals import ReferralInviteRequest, ReferralMeResponse
from app.services.referrals.invites import friend_price_line, price_lines, send_invites
from app.services.referrals.overview import get_referral_overview
from app.services.referrals.suggestions import suggest_invitees as compute_suggestions
from app.templates.docstrings.referral_tool_docs import (
    GET_REFERRAL_LINK,
    GET_REFERRAL_STATUS,
    SEND_REFERRAL_INVITE,
    SUGGEST_INVITEES,
)
from app.utils.errors import AppError
from app.utils.money import format_price
from shared.py.wide_events import log

NO_LINK_MESSAGE = (
    "This user has no active subscription, so they have no invite link yet. "
    "Sharing GAIA opens up once they subscribe; say so plainly, without pushing an upgrade."
)

_INVITE_OUTCOMES: dict[ReferralInviteStatus, str] = {
    ReferralInviteStatus.SENT: "sent",
    ReferralInviteStatus.ALREADY_INVITED: "already invited by this user, not sent again",
    ReferralInviteStatus.INVALID: "not a valid email address, not sent",
    ReferralInviteStatus.UNSUBSCRIBED: "opted out of GAIA invites, not sent",
    ReferralInviteStatus.OWN_ADDRESS: "the user's own address, not sent",
}

_FRIEND_STATUSES: dict[ReferredFriendStatus, str] = {
    ReferredFriendStatus.PAID: "paid, earned a free month",
    ReferredFriendStatus.JOINED: "joined, has not paid yet",
}


async def _overview_or_none(user_id: str) -> ReferralMeResponse | None:
    """Return the user's referral overview, or None when they have no subscription and so no link."""
    try:
        return await get_referral_overview(user_id)
    except AppError as e:
        if e.code != REFERRAL_SUBSCRIPTION_REQUIRED:
            raise
        log.set_ns("referral", has_link=False)
        return None


def _share_text(overview: ReferralMeResponse) -> str:
    intro, _ = price_lines(overview.offer)
    return SHARE_TEXT_TEMPLATE.format(price_line=intro, link=overview.share_link)


@tool
@with_doc(GET_REFERRAL_LINK)
async def get_referral_link(config: RunnableConfig) -> str:
    user_id = get_user_id(config)
    log.set(tool={"name": "get_referral_link"}, referral={"operation": "agent_link"})
    overview = await _overview_or_none(user_id)
    if overview is None:
        return NO_LINK_MESSAGE
    offer = overview.offer
    _, regular = price_lines(offer)
    yearly_saving = format_price(offer.yearly_discount_minor, offer.currency)
    return (
        f"Invite link: {overview.share_link}\n"
        f"Friends get GAIA for {friend_price_line(offer)}, then {regular}. "
        f"On a yearly plan they save {yearly_saving} on their first year.\n"
        "The user gets a free month every time a friend pays.\n"
        "Message to share (hand it over exactly as written):\n"
        f"{_share_text(overview)}"
    )


@tool
@with_doc(GET_REFERRAL_STATUS)
async def get_referral_status(config: RunnableConfig) -> str:
    user_id = get_user_id(config)
    log.set(tool={"name": "get_referral_status"}, referral={"operation": "agent_status"})
    overview = await _overview_or_none(user_id)
    if overview is None:
        return NO_LINK_MESSAGE
    lines = [
        f"Free months earned: {overview.months_earned} "
        f"({overview.months_applied} already added to the billing date, "
        f"{overview.months_banked} saved for when they subscribe again)",
        "Next bill: "
        + (
            overview.next_billing_date.date().isoformat()
            if overview.next_billing_date
            else "none scheduled"
        ),
    ]
    if not overview.friends:
        lines.append("Friends who joined: none yet")
    else:
        lines.append(f"Friends who joined ({len(overview.friends)}):")
        lines.extend(
            f"  - {friend.first_name or '(no name)'}: {_FRIEND_STATUSES[friend.status]}"
            for friend in overview.friends
        )
    log.set_ns("referral", friends=len(overview.friends), months_earned=overview.months_earned)
    return "\n".join(lines)


@tool
@with_doc(SUGGEST_INVITEES)
async def suggest_invitees(config: RunnableConfig) -> str:
    user_id = get_user_id(config)
    log.set(tool={"name": "suggest_invitees"}, referral={"operation": "agent_suggestions"})
    suggestions = (await compute_suggestions(user_id)).suggestions
    if not suggestions:
        return (
            "No one to suggest right now. Suggestions come from the people the user "
            "meets in Google Calendar and emails in Gmail, when those are connected."
        )
    lines = [f"People to invite ({len(suggestions)}), from the last 90 days:"]
    lines.extend(
        f"  - {f'{s.name} <{s.email}>' if s.name else s.email}: {s.reason.value} {s.count} times"
        for s in suggestions
    )
    return "\n".join(lines)


@tool(SEND_REFERRAL_INVITE_TOOL)
@with_doc(SEND_REFERRAL_INVITE)
async def send_referral_invite(
    config: RunnableConfig,
    emails: Annotated[list[str], "The friends' email addresses"],
    friend_name: Annotated[
        str | None, "The friend's first name, for the message to forward on a chat platform"
    ] = None,
) -> str:
    user_id = get_user_id(config)
    on_bot = runs_on_bot(agent_configurable(config))
    log.set(
        tool={"name": SEND_REFERRAL_INVITE_TOOL},
        referral={"operation": "agent_invite", "requested": len(emails), "forward_only": on_bot},
    )
    if on_bot:
        overview = await _overview_or_none(user_id)
        if overview is None:
            return NO_LINK_MESSAGE
        forwardable = FORWARDABLE_INVITE_TEMPLATE.format(
            recipient=friend_name or FORWARD_RECIPIENT_FALLBACK,
            price_line=friend_price_line(overview.offer),
            share_text=_share_text(overview),
        )
        return (
            "Nothing was emailed: on a chat platform the user forwards the invite themselves. "
            f"Relay this exactly:\n{forwardable}"
        )
    try:
        response = await send_invites(
            user_id, ReferralInviteRequest(emails=emails, surface=ReferralInviteSurface.AGENT)
        )
    except AppError as e:
        return " ".join(part for part in (f"Nothing was sent: {e.message}.", e.fix) if part)
    return "\n".join(
        f"{result.email}: {_INVITE_OUTCOMES[result.status]}" for result in response.results
    )


tools = [get_referral_link, get_referral_status, suggest_invitees, send_referral_invite]
