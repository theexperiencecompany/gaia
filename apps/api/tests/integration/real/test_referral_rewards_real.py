"""A referred friend's first payment earns the referrer one free month, exactly once, against real Mongo + Redis.

Dodo is the seam: an in-memory fake that keeps each subscription's billing date,
so every assertion is on the date Dodo would hold. Analytics and the in-app
notification are patched; the referral, subscription and user rows are real.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from dodopayments.types import Subscription
import pytest

from app.constants.referrals import REWARD_LOCK_KEY_TEMPLATE
from app.db.repositories.referrals import referral_repository
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.models.payment_models import SubscriptionDocument, SubscriptionStatus, SubscriptionUpdate
from app.models.referral_models import ReferralDocument, ReferralRewardState, ReferredFriendStatus
from app.models.user_models import UserDocument
from app.models.webhook_models import DodoPaymentData
from app.services.payments.payment_service import payment_service
from app.services.referrals.rewards import apply_banked_months, record_friend_payment
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralConverted, ReferralRewardGranted
from tests.factories import make_dodo_payment, make_dodo_subscription

pytestmark = pytest.mark.service

NEXT_BILL = datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
ONE_MONTH_LATER = datetime(2026, 12, 14, 9, 30, tzinfo=UTC)
TWO_MONTHS_LATER = datetime(2027, 1, 14, 9, 30, tzinfo=UTC)
# How long a delivery is given to (wrongly) get past a lock someone else holds.
LOCK_PROBE_S = 1.0


@dataclass
class FakeDodo:
    """Dodo's subscriptions API over a dict: retrieve reads it, update moves a billing date."""

    store: dict[str, Subscription] = field(default_factory=dict)
    updates: list[tuple[str, datetime]] = field(default_factory=list)
    failures_left: int = 0

    @property
    def subscriptions(self) -> "FakeDodo":
        return self

    def retrieve(self, subscription_id: str) -> Subscription:
        return self.store[subscription_id]

    def update(self, subscription_id: str, *, next_billing_date: datetime) -> Subscription:
        if self.failures_left:
            self.failures_left -= 1
            raise ConnectionError("dodo unreachable")
        moved = self.store[subscription_id].model_copy(
            update={"next_billing_date": next_billing_date}
        )
        self.store[subscription_id] = moved
        self.updates.append((subscription_id, next_billing_date))
        return moved


@dataclass
class Seams:
    dodo: FakeDodo
    capture: MagicMock
    notify: AsyncMock


@pytest.fixture
def seams(mongo_db: Any, real_redis: Any) -> Iterator[Seams]:
    dodo = FakeDodo()
    with (
        patch.object(payment_service, "client", dodo, create=True),
        patch("app.services.referrals.rewards.capture") as capture,
        patch(
            "app.services.referrals.rewards.notification_service.create_notification",
            AsyncMock(return_value=MagicMock()),
        ) as notify,
        patch("app.services.payments.subscription_events.invalidate_plan_cache", AsyncMock()),
    ):
        yield Seams(dodo, capture, notify)


async def _user(first_name: str) -> UserDocument:
    return await user_repository.create(
        UserDocument(
            name=f"{first_name} Test",
            first_name=first_name,
            email=f"{first_name.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        )
    )


async def _active_subscription(dodo: FakeDodo, user: UserDocument, customer_id: str) -> str:
    sub_id = f"sub_{uuid.uuid4().hex}"
    dodo.store[sub_id] = make_dodo_subscription(sub_id, customer_id, NEXT_BILL)
    now = datetime.now(UTC)
    await subscription_repository.create(
        SubscriptionDocument.model_validate(
            {
                "dodo_subscription_id": sub_id,
                "user_id": user.id,
                "product_id": "pdt_pro_monthly",
                "status": SubscriptionStatus.ACTIVE.value,
                "next_billing_date": NEXT_BILL.isoformat(),
                "created_at": now,
                "updated_at": now,
            }
        )
    )
    return sub_id


async def _refer(referrer: UserDocument, friend: UserDocument) -> None:
    now = datetime.now(UTC)
    await referral_repository.attribute(
        ReferralDocument(
            friend_user_id=friend.id,
            referrer_user_id=referrer.id,
            code="aryan-k7f2",
            joined_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _payment(
    friend: UserDocument, *, amount: int = 1500, customer_id: str | None = None
) -> DodoPaymentData:
    return make_dodo_payment(
        user_id=friend.id, email=friend.email, amount=amount, customer_id=customer_id
    )


def _granted(capture: MagicMock) -> list[ReferralRewardGranted]:
    return [
        c.args[1] for c in capture.call_args_list if isinstance(c.args[1], ReferralRewardGranted)
    ]


class TestFirstPaymentEarnsAMonth:
    async def test_the_referrers_next_bill_moves_one_month_and_is_recorded(
        self, seams: Seams
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await _refer(referrer, friend)
        payment = _payment(friend)

        await record_friend_payment(payment)

        assert seams.dodo.updates == [(sub_id, ONE_MONTH_LATER)]
        referral = await referral_repository.get(friend.id)
        assert referral.status is ReferredFriendStatus.PAID
        assert referral.reward_state is ReferralRewardState.APPLIED
        local = await subscription_repository.get_by_dodo_id(sub_id)
        assert datetime.fromisoformat(local.next_billing_date) == ONE_MONTH_LATER
        assert _granted(seams.capture) == [
            ReferralRewardGranted(friend_id=friend.id, delivery="applied", months=1)
        ]
        converted = next(
            c for c in seams.capture.call_args_list if isinstance(c.args[1], ReferralConverted)
        )
        assert converted.args[0] == UserId(friend.id)
        assert converted.args[1].self_referral is False
        assert "Priya" in seams.notify.call_args.args[0].content.title

    async def test_a_redelivered_payment_moves_the_date_once(self, seams: Seams) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await _refer(referrer, friend)
        payment = _payment(friend)

        await record_friend_payment(payment)
        await record_friend_payment(payment)
        await record_friend_payment(_payment(friend))

        assert seams.dodo.updates == [(sub_id, ONE_MONTH_LATER)]
        assert len(_granted(seams.capture)) == 1

    async def test_a_failed_dodo_call_is_finished_by_the_retry_on_the_pinned_date(
        self, seams: Seams
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await _refer(referrer, friend)
        payment = _payment(friend)
        seams.dodo.failures_left = 1

        with pytest.raises(ConnectionError):
            await record_friend_payment(payment)
        assert (
            await referral_repository.get(friend.id)
        ).reward_state is ReferralRewardState.PENDING

        await record_friend_payment(payment)

        assert seams.dodo.updates == [(sub_id, ONE_MONTH_LATER)]
        assert (
            await referral_repository.get(friend.id)
        ).reward_state is ReferralRewardState.APPLIED

    async def test_two_friends_paying_at_once_earn_two_months(self, seams: Seams) -> None:
        referrer = await _user("Aryan")
        friends = [await _user("Priya"), await _user("Sam")]
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        for friend in friends:
            await _refer(referrer, friend)

        await asyncio.gather(*(record_friend_payment(_payment(f)) for f in friends))

        assert seams.dodo.store[sub_id].next_billing_date == TWO_MONTHS_LATER
        assert len(seams.dodo.updates) == 2

    async def test_a_reward_waits_while_another_holds_the_referrers_lock(
        self, seams: Seams, real_redis: Any
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await _refer(referrer, friend)
        held = real_redis.lock(REWARD_LOCK_KEY_TEMPLATE.format(user_id=referrer.id), timeout=30)
        await held.acquire()

        delivery = asyncio.create_task(record_friend_payment(_payment(friend)))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(delivery), timeout=LOCK_PROBE_S)
        assert seams.dodo.updates == []

        await held.release()
        await delivery
        assert seams.dodo.updates == [(sub_id, ONE_MONTH_LATER)]


class TestNothingEarned:
    async def test_paying_as_the_referrers_own_dodo_customer_earns_nothing(
        self, seams: Seams
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Alt")
        await _active_subscription(seams.dodo, referrer, "cus_same_person")
        await _refer(referrer, friend)

        await record_friend_payment(_payment(friend, customer_id="cus_same_person"))

        assert seams.dodo.updates == []
        assert (
            await referral_repository.get(friend.id)
        ).reward_state is ReferralRewardState.SELF_REFERRAL
        assert _granted(seams.capture) == []

    async def test_a_free_checkout_is_not_a_paying_friend(self, seams: Seams) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await _refer(referrer, friend)

        await record_friend_payment(_payment(friend, amount=0))

        assert (await referral_repository.get(friend.id)).status is ReferredFriendStatus.JOINED

    async def test_a_payment_from_someone_never_referred_changes_nothing(
        self, seams: Seams
    ) -> None:
        stranger = await _user("Stranger")

        await record_friend_payment(_payment(stranger))

        assert seams.dodo.updates == [] and seams.capture.call_count == 0
        assert await referral_repository.get(stranger.id) is None


class TestBankedMonths:
    async def test_a_lapsed_referrer_banks_the_month_and_gets_it_on_resubscribe(
        self, seams: Seams
    ) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        await _refer(referrer, friend)

        await record_friend_payment(_payment(friend))

        assert seams.dodo.updates == []
        assert (await referral_repository.get(friend.id)).reward_state is ReferralRewardState.BANKED
        assert _granted(seams.capture) == [
            ReferralRewardGranted(friend_id=friend.id, delivery="banked", months=1)
        ]

        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        assert await apply_banked_months(referrer.id) == 1
        assert await apply_banked_months(referrer.id) == 0

        assert seams.dodo.updates == [(sub_id, ONE_MONTH_LATER)]
        assert (
            await referral_repository.get(friend.id)
        ).reward_state is ReferralRewardState.APPLIED
        assert len(_granted(seams.capture)) == 1

    async def test_a_cancelled_subscription_banks_rather_than_moves(self, seams: Seams) -> None:
        referrer, friend = await _user("Aryan"), await _user("Priya")
        sub_id = await _active_subscription(seams.dodo, referrer, "cus_referrer")
        await subscription_repository.apply_update_by_dodo_id(
            sub_id,
            SubscriptionUpdate(status=SubscriptionStatus.EXPIRED.value),
            if_not_newer_than=datetime.now(UTC),
        )
        await _refer(referrer, friend)

        await record_friend_payment(_payment(friend))

        assert seams.dodo.updates == []
        assert (await referral_repository.get(friend.id)).reward_state is ReferralRewardState.BANKED
