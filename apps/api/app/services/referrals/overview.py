"""What the referral page shows its owner, and what an invite landing page and paywall show a friend."""

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from app.config.feature_flags import REFERRAL_COPY_FLAG, REFERRAL_LAYOUT_FLAG
from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import (
    SUBSCRIPTION_REQUIRED_FIX,
    SUBSCRIPTION_REQUIRED_MESSAGE,
    SUBSCRIPTION_REQUIRED_WHY,
    WORKFLOW_CREDITS_PER_MONTH,
    ReferralCopyVariant,
    ReferralSource,
)
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.models.payment_models import SubscriptionDocument
from app.models.referral_models import ReferralDocument, ReferralRewardState, ReferredFriendStanding
from app.schemas.referrals import (
    ReferralFriendGift,
    ReferralGiftResponse,
    ReferralMeResponse,
    ReferralResolveResponse,
    ReferralWorkflowMeter,
    ReferredFriend,
)
from app.services.analytics_service import capture
from app.services.feature_flags import get_variant
from app.services.payments.payment_service import payment_service
from app.services.referrals.attribution import ReferralAttribution, first_touch_cookie
from app.services.referrals.availability import referrals_enabled, require_referrals
from app.services.referrals.codes import ensure_code, first_name_of, load_user, share_link
from app.services.referrals.gift import pending_gift_referral
from app.services.referrals.offer import build_offer
from app.utils.errors import AppError
from app.utils.timezone import as_utc
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralLandingResolved

_EARNED_STATES = frozenset(
    {ReferralRewardState.PENDING, ReferralRewardState.APPLIED, ReferralRewardState.BANKED}
)


def _friend_entry(referral: ReferralDocument, first_name: str | None) -> ReferredFriend:
    """List a friend; one whose first payment was refunded or disputed shows as refunded, with no payment date."""
    if referral.refunded:
        standing, paid_at = ReferredFriendStanding.REFUNDED, None
    else:
        standing, paid_at = ReferredFriendStanding(referral.status.value), referral.paid_at
    return ReferredFriend(
        first_name=first_name, status=standing, joined_at=referral.joined_at, paid_at=paid_at
    )


def _workflow_meter(
    referrals: list[ReferralDocument], community_workflows: int
) -> ReferralWorkflowMeter:
    """Count paying workflow visitors toward the creator's next month; their names are never shown."""
    states = Counter(r.reward_state for r in referrals if r.source is ReferralSource.WORKFLOW)
    months = states[ReferralRewardState.APPLIED] + states[ReferralRewardState.BANKED]
    counted = months + states[ReferralRewardState.METERED]
    return ReferralWorkflowMeter(
        subscribed=max(0, counted - months * WORKFLOW_CREDITS_PER_MONTH),
        per_month=WORKFLOW_CREDITS_PER_MONTH,
        months_earned=months,
        published=community_workflows,
    )


async def require_referrer(user_id: str) -> SubscriptionDocument:
    """Return the user's active subscription; 403 while referrals are off or without one, since only subscribers have a link."""
    await require_referrals(user_id)
    subscription = await subscription_repository.get_active_for_user(user_id)
    if subscription is None:
        raise AppError(
            message=SUBSCRIPTION_REQUIRED_MESSAGE,
            why=SUBSCRIPTION_REQUIRED_WHY,
            fix=SUBSCRIPTION_REQUIRED_FIX,
            status_code=403,
            code=REFERRAL_SUBSCRIPTION_REQUIRED,
        )
    return subscription


async def get_referral_overview(user_id: str) -> ReferralMeResponse:
    """Return the caller's link, gift, earned months and friends; 403 while referrals are off or without a subscription."""
    subscription = await require_referrer(user_id)
    user = await load_user(user_id)
    (
        code,
        plans,
        referrals,
        copy_variant,
        layout_variant,
        community_workflows,
    ) = await asyncio.gather(
        ensure_code(user),
        payment_service.get_pro_plans(),
        referral_repository.list_for_referrer(user.id),
        get_variant(REFERRAL_COPY_FLAG, user.id),
        get_variant(REFERRAL_LAYOUT_FLAG, user.id),
        workflow_repository.count_community_by_creator(user.id),
    )
    invited = [r for r in referrals if r.source is ReferralSource.INVITE_LINK]
    friends = {
        friend.id: friend
        for friend in await user_repository.find_by_ids([r.friend_user_id for r in invited])
    }
    rewards = Counter(
        r.reward_state for r in referrals if r.reward_state in _EARNED_STATES and not r.refunded
    )
    return ReferralMeResponse(
        code=code,
        share_link=share_link(code),
        offer=build_offer(plans),
        months_earned=sum(rewards.values()),
        months_applied=rewards[ReferralRewardState.APPLIED],
        months_banked=rewards[ReferralRewardState.BANKED],
        next_billing_date=as_utc(datetime.fromisoformat(subscription.next_billing_date))
        if subscription.next_billing_date
        else None,
        friends=[
            _friend_entry(
                r,
                first_name_of(friends[r.friend_user_id]) if r.friend_user_id in friends else None,
            )
            for r in invited
        ],
        workflow_meter=_workflow_meter(referrals, community_workflows),
        copy_variant=copy_variant,
        layout_variant=layout_variant,
    )


@dataclass(frozen=True)
class InviteLanding:
    """An invite link's landing: what the page shows, and the first-touch cookie to set, if any."""

    resolved: ReferralResolveResponse
    cookie: str | None


async def _resolve_code(code: str) -> tuple[ReferralResolveResponse, str | None]:
    """Return what the landing shows and the code's owner; an unknown code, or referrals off, is valid=false."""
    owner_code, plans = await asyncio.gather(
        referral_code_repository.get_by_code(code), payment_service.get_pro_plans()
    )
    offer = build_offer(plans)
    owner = await user_repository.get(owner_code.user_id) if owner_code else None
    if owner is None:
        return ReferralResolveResponse(valid=False, offer=offer), None
    if not await referrals_enabled(owner.id):
        return ReferralResolveResponse(valid=False, offer=offer), owner.id
    return (
        ReferralResolveResponse(
            valid=True,
            referrer_first_name=first_name_of(owner),
            referrer_picture=owner.picture or None,
            offer=offer,
        ),
        owner.id,
    )


async def land_on_invite(
    code: str, landing_variant: ReferralCopyVariant | None, existing_cookie: str | None
) -> InviteLanding:
    """Resolve an invite link for its landing page and record the landing on the link's owner.

    An unknown code is never recorded: it has no owner, and the visitor has no account yet.
    """
    resolved, referrer_id = await _resolve_code(code)
    cookie = first_touch_cookie(
        existing_cookie,
        ReferralAttribution(code=code, landing_variant=landing_variant),
        valid=resolved.valid,
    )
    if referrer_id is not None:
        capture(
            UserId(referrer_id),
            ReferralLandingResolved(
                outcome="valid" if resolved.valid else "disabled",
                landing_variant=landing_variant.value if landing_variant else None,
                cookie_set=cookie is not None,
            ),
        )
    return InviteLanding(resolved=resolved, cookie=cookie)


async def friend_gift(user_id: str) -> ReferralGiftResponse:
    """Return the gift the caller's checkout will apply, for the paywall to price; None when they are owed none."""
    referral = await pending_gift_referral(user_id)
    if referral is None:
        return ReferralGiftResponse(gift=None)
    referrer, plans = await asyncio.gather(
        user_repository.get(referral.referrer_user_id), payment_service.get_pro_plans()
    )
    billing_cycles = await payment_service.pro_checkout_gift_cycles(plans)
    if not billing_cycles:
        return ReferralGiftResponse(gift=None)
    return ReferralGiftResponse(
        gift=ReferralFriendGift(
            referrer_first_name=first_name_of(referrer) if referrer else None,
            referrer_picture=(referrer.picture or None) if referrer else None,
            offer=build_offer(plans),
            billing_cycles=billing_cycles,
        )
    )
