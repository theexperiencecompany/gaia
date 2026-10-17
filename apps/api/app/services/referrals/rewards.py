"""The referrer's free month: earned on a referred friend's first successful payment.

Delivered by moving the referrer's Dodo next_billing_date forward a month, or
banked while they have no active subscription and applied when they come back.
Every step is idempotent per friend, so a redelivered webhook or a retried job
never moves a billing date twice:

- the friend's joined -> paid transition is atomic, and claims the reward;
- the billing date a reward moves to is pinned once, then only ever set, never
  added to, and only while Dodo's date is still behind it;
- one referrer's rewards are delivered one at a time, under a Redis lock.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from dodopayments import NotFoundError
import pendulum

from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.constants.referrals import (
    REWARD_APPLIED_BODY,
    REWARD_APPLIED_TITLE,
    REWARD_BANKED_BODY,
    REWARD_DATE_FORMAT,
    REWARD_LOCK_KEY_TEMPLATE,
    REWARD_LOCK_LEASE_S,
    REWARD_LOCK_MAX_HOLD_S,
    REWARD_LOCK_RENEW_S,
    REWARD_LOCK_UNAVAILABLE,
    REWARD_LOCK_WAIT_S,
    REWARD_MONTHS_PER_FRIEND,
)
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.referral_models import ReferralDocument, ReferralRewardState, ReferralUpdate
from app.models.webhook_models import DodoPaymentData, DodoSubscriptionData
from app.services.analytics_service import capture
from app.services.notification_service import notification_service
from app.services.payments.payment_service import payment_service
from app.services.payments.subscription_events import (
    SubscriptionEvent,
    SubscriptionEventKind,
    apply_subscription_event,
)
from app.services.referrals.codes import first_name_of
from app.utils.email_utils import email_identity
from app.utils.redis_lock import DistributedLock
from app.utils.timezone import as_utc
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.referrals import ReferralConverted, ReferralRewardGranted
from shared.py.wide_events import log


@dataclass(frozen=True)
class RewardDelivery:
    """Where a reward ended up: on the billing date it moved to, or banked."""

    state: ReferralRewardState
    next_billing_date: datetime | None = None


async def _payer_user_id(payment: DodoPaymentData) -> str | None:
    if payment.metadata.user_id:
        return payment.metadata.user_id
    user = await user_repository.get_by_email(payment.customer.email)
    return user.id if user else None


async def _legacy_customer_id(dodo_subscription_id: str) -> str | None:
    """Ask Dodo whose a pre-recording subscription is; None when Dodo no longer has it."""
    try:
        remote = await asyncio.to_thread(
            payment_service.client.subscriptions.retrieve, dodo_subscription_id
        )
    except NotFoundError:
        log.warning(
            "referral self-check skipped a subscription Dodo no longer has",
            subscription_id=dodo_subscription_id,
        )
        return None
    return remote.customer.customer_id


async def _referrer_customer_ids(referrer_user_id: str) -> set[str]:
    """Return the Dodo customer ids behind every subscription the referrer ever had."""
    subscriptions = await subscription_repository.list_for_user(referrer_user_id)
    stored = {sub.dodo_customer_id for sub in subscriptions if sub.dodo_customer_id}
    legacy = [
        sub.dodo_subscription_id
        for sub in subscriptions
        if not sub.dodo_customer_id and sub.dodo_subscription_id
    ]
    fetched = await asyncio.gather(*(_legacy_customer_id(sid) for sid in legacy))
    return stored | {customer for customer in fetched if customer}


async def _is_self_referral(referral: ReferralDocument, payment: DodoPaymentData) -> bool:
    """Whether friend and referrer are one person: the same mailbox, or the same Dodo customer.

    Dodo exposes no card fingerprint, so the customer id is the strongest
    payment-side identity there is.
    """
    referrer = await user_repository.get(referral.referrer_user_id)
    if referrer is None:
        return False
    if referrer.email and email_identity(referrer.email) == email_identity(payment.customer.email):
        return True
    return payment.customer.customer_id in await _referrer_customer_ids(referrer.id)


async def record_friend_payment(payment: DodoPaymentData) -> None:
    """Convert a referred friend on their first successful payment and earn their referrer a month."""
    # A one-off purchase or a free checkout is not a friend joining.
    if payment.total_amount <= 0 or not payment.subscription_id:
        return
    friend_user_id = await _payer_user_id(payment)
    if friend_user_id is None:
        return
    referral = await referral_repository.mark_paid(
        friend_user_id, payment_id=payment.payment_id, paid_at=datetime.now(UTC)
    )
    if referral is None:
        # Not referred, already converted, or this very payment converted them
        # and the reward is still owed because the last delivery failed.
        retried = await referral_repository.get(friend_user_id)
        if retried is None or retried.payment_id != payment.payment_id:
            return
        if retried.reward_state is not ReferralRewardState.PENDING:
            return
        referral = retried

    self_referral = await _is_self_referral(referral, payment)
    log.set_ns("referral", converted=True, self_referral=self_referral)
    capture(
        UserId(friend_user_id),
        ReferralConverted(
            referrer_id=referral.referrer_user_id,
            landing_variant=referral.landing_variant.value if referral.landing_variant else None,
            self_referral=self_referral,
        ),
        dedupe=Dedupe(
            key=payment.payment_id, occurred_at=as_utc(referral.paid_at) or datetime.now(UTC)
        ),
    )
    if self_referral:
        await referral_repository.update(
            friend_user_id, ReferralUpdate(reward_state=ReferralRewardState.SELF_REFERRAL)
        )
        return
    await deliver_rewards(referral.referrer_user_id, [referral])


async def apply_banked_months(referrer_user_id: str) -> int:
    """Deliver every month the referrer banked while unsubscribed; returns how many moved the billing date."""
    banked = await referral_repository.list_banked(referrer_user_id)
    if not banked:
        return 0
    deliveries = await deliver_rewards(referrer_user_id, banked)
    return sum(1 for d in deliveries if d.state is ReferralRewardState.APPLIED)


async def deliver_rewards(
    referrer_user_id: str, referrals: list[ReferralDocument]
) -> list[RewardDelivery]:
    """Apply each reward to the referrer's active subscription, or bank it, one referrer at a time."""
    lease = DistributedLock(
        REWARD_LOCK_KEY_TEMPLATE.format(user_id=referrer_user_id),
        lease_seconds=REWARD_LOCK_LEASE_S,
        acquire_timeout_seconds=REWARD_LOCK_WAIT_S,
        renew_seconds=REWARD_LOCK_RENEW_S,
        max_hold_seconds=REWARD_LOCK_MAX_HOLD_S,
    )
    async with lease.hold() as held:
        if not held:
            raise RuntimeError(REWARD_LOCK_UNAVAILABLE)
        return [await _deliver(referral) for referral in referrals]


async def _deliver(referral: ReferralDocument) -> RewardDelivery:
    newly_earned = referral.reward_state is ReferralRewardState.PENDING
    subscription = await subscription_repository.get_active_for_user(referral.referrer_user_id)
    if subscription is None or not subscription.dodo_subscription_id:
        if newly_earned:
            await referral_repository.update(
                referral.friend_user_id,
                ReferralUpdate(
                    reward_state=ReferralRewardState.BANKED, reward_target_billing_date=None
                ),
            )
            await _announce(referral, RewardDelivery(ReferralRewardState.BANKED))
        return RewardDelivery(ReferralRewardState.BANKED)

    moved_to = await _move_billing_date(referral, subscription.dodo_subscription_id)
    await referral_repository.update(
        referral.friend_user_id,
        ReferralUpdate(
            reward_state=ReferralRewardState.APPLIED, reward_applied_at=datetime.now(UTC)
        ),
    )
    delivery = RewardDelivery(ReferralRewardState.APPLIED, moved_to)
    if newly_earned:
        await _announce(referral, delivery)
    else:
        await _notify(referral, delivery)
    return delivery


async def _move_billing_date(referral: ReferralDocument, dodo_subscription_id: str) -> datetime:
    """Push the referrer's next charge a month out, to a date pinned on the referral so a retry lands on it again."""
    client = payment_service.client
    live = await asyncio.to_thread(client.subscriptions.retrieve, dodo_subscription_id)
    current = live.next_billing_date.astimezone(UTC)
    pinned = await referral_repository.set_reward_target_if_unset(
        referral.friend_user_id, pendulum.instance(current).add(months=REWARD_MONTHS_PER_FRIEND)
    )
    target = as_utc(pinned.reward_target_billing_date if pinned else None)
    if target is None:
        raise RuntimeError(f"referral {referral.friend_user_id} vanished mid-delivery")
    if current >= target:
        log.set_ns("referral", billing_date_already_moved=True)
        return current

    updated = await asyncio.to_thread(
        client.subscriptions.update, dodo_subscription_id, next_billing_date=target
    )
    await apply_subscription_event(
        SubscriptionEvent(
            kind=SubscriptionEventKind.BILLING_DATE_MOVED,
            occurred_at=datetime.now(UTC),
            data=DodoSubscriptionData.model_validate(updated.model_dump(mode="json")),
        )
    )
    log.audit(
        "referral free month applied",
        actor=referral.referrer_user_id,
        resource=dodo_subscription_id,
        provider="dodo",
    )
    return updated.next_billing_date.astimezone(UTC)


async def _announce(referral: ReferralDocument, delivery: RewardDelivery) -> None:
    """Record and tell the referrer about a month they just earned."""
    capture(
        UserId(referral.referrer_user_id),
        ReferralRewardGranted(
            friend_id=referral.friend_user_id,
            delivery=delivery.state.value,
            months=REWARD_MONTHS_PER_FRIEND,
        ),
        dedupe=Dedupe(
            key=referral.friend_user_id, occurred_at=as_utc(referral.paid_at) or datetime.now(UTC)
        ),
    )
    await _notify(referral, delivery)


async def _notify(referral: ReferralDocument, delivery: RewardDelivery) -> None:
    friend = await user_repository.get(referral.friend_user_id)
    friend_name = (first_name_of(friend) if friend else None) or "A friend"
    body = (
        REWARD_APPLIED_BODY.format(date=delivery.next_billing_date.strftime(REWARD_DATE_FORMAT))
        if delivery.next_billing_date
        else REWARD_BANKED_BODY
    )
    record = await notification_service.create_notification(
        NotificationRequest(
            user_id=referral.referrer_user_id,
            source=NotificationSourceEnum.REFERRAL_REWARD,
            type=NotificationType.SUCCESS,
            priority=2,
            channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
            content=NotificationContent(
                title=REWARD_APPLIED_TITLE.format(friend=friend_name), body=body
            ),
            metadata={"friend_user_id": referral.friend_user_id, "reward": delivery.state.value},
        )
    )
    if record is None:
        log.warning(
            "Referral reward notification was not created",
            user_id=referral.referrer_user_id,
            friend_user_id=referral.friend_user_id,
        )
