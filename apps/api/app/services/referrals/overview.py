"""What the referral page shows its owner, and what an invite landing page shows a friend."""

import asyncio
from collections import Counter
from datetime import datetime

from app.config.feature_flags import REFERRAL_COPY_FLAG, REFERRAL_LAYOUT_FLAG
from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import (
    SUBSCRIPTION_REQUIRED_FIX,
    SUBSCRIPTION_REQUIRED_MESSAGE,
    SUBSCRIPTION_REQUIRED_WHY,
)
from app.db.repositories.referral_codes import referral_code_repository
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import SubscriptionDocument
from app.models.referral_models import ReferralRewardState
from app.schemas.referrals import ReferralMeResponse, ReferralResolveResponse, ReferredFriend
from app.services.feature_flags import get_variant
from app.services.payments.payment_service import payment_service
from app.services.referrals.codes import ensure_code, first_name_of, load_user, share_link
from app.services.referrals.offer import build_offer
from app.utils.errors import AppError
from app.utils.timezone import as_utc

_EARNED_STATES = frozenset(
    {ReferralRewardState.PENDING, ReferralRewardState.APPLIED, ReferralRewardState.BANKED}
)


async def require_referrer_subscription(user_id: str) -> SubscriptionDocument:
    """Return the user's active subscription; 403 REFERRAL_SUBSCRIPTION_REQUIRED without one, since only subscribers have a link."""
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
    """Return the caller's link, gift, earned months and friends; 403 without an active subscription."""
    user = await load_user(user_id)
    subscription = await require_referrer_subscription(user.id)
    code, plans, referrals, copy_variant, layout_variant = await asyncio.gather(
        ensure_code(user),
        payment_service.get_pro_plans(),
        referral_repository.list_for_referrer(user.id),
        get_variant(REFERRAL_COPY_FLAG, user.id),
        get_variant(REFERRAL_LAYOUT_FLAG, user.id),
    )
    friends = {
        friend.id: friend
        for friend in await user_repository.find_by_ids([r.friend_user_id for r in referrals])
    }
    rewards = Counter(r.reward_state for r in referrals if r.reward_state in _EARNED_STATES)
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
            ReferredFriend(
                first_name=first_name_of(friends[r.friend_user_id])
                if r.friend_user_id in friends
                else None,
                status=r.status,
                joined_at=r.joined_at,
                paid_at=r.paid_at,
            )
            for r in referrals
        ],
        copy_variant=copy_variant,
        layout_variant=layout_variant,
    )


async def resolve_referral_code(code: str) -> ReferralResolveResponse:
    """Return who sent this link and the gift it carries; an unknown code is valid=false, not a 404."""
    owner_code, plans = await asyncio.gather(
        referral_code_repository.get_by_code(code), payment_service.get_pro_plans()
    )
    offer = build_offer(plans)
    owner = await user_repository.get(owner_code.user_id) if owner_code else None
    if owner is None:
        return ReferralResolveResponse(valid=False, offer=offer)
    return ReferralResolveResponse(
        valid=True,
        referrer_first_name=first_name_of(owner),
        referrer_picture=owner.picture or None,
        offer=offer,
    )
