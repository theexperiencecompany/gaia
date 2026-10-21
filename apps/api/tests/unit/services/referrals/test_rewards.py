"""The referrer's free month, decided over mocked repositories, lock and Dodo.

The real-infra tier (tests/integration/real/test_referral_rewards_real.py) proves
the once-only guarantees against real Mongo and Redis; this file pins what each
branch decides and records: who converts, where a month lands, and what is told.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import re
from unittest.mock import AsyncMock, MagicMock, call, patch

from dodopayments import NotFoundError
import httpx
import pytest
import time_machine

from app.constants.notifications import CHANNEL_TYPE_INAPP
from app.constants.referrals import (
    REWARD_APPLIED_BODY,
    REWARD_APPLIED_TITLE,
    REWARD_BANKED_BODY,
    REWARD_LOCK_KEY_TEMPLATE,
    REWARD_LOCK_LEASE_S,
    REWARD_LOCK_MAX_HOLD_S,
    REWARD_LOCK_RENEW_S,
    REWARD_LOCK_UNAVAILABLE,
    REWARD_LOCK_WAIT_S,
    ReferralCopyVariant,
)
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.payment_models import SubscriptionDocument
from app.models.referral_models import (
    ReferralDocument,
    ReferralRewardState,
    ReferralUpdate,
    ReferredFriendStatus,
)
from app.models.user_models import UserDocument
from app.models.webhook_models import DodoSubscriptionData
from app.services.payments.payment_service import payment_service
from app.services.payments.subscription_events import SubscriptionEvent, SubscriptionEventKind
from app.services.referrals.rewards import (
    RewardDelivery,
    apply_banked_months,
    deliver_rewards,
    record_friend_payment,
)
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.referrals import ReferralConverted, ReferralRewardGranted
from tests.factories import make_dodo_payment, make_dodo_subscription
from tests.helpers import local_timezone

REWARDS = "app.services.referrals.rewards"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
PAID_AT = datetime(2026, 10, 14, 11, 0, tzinfo=UTC)
NEXT_BILL = datetime(2026, 11, 14, 9, 30, tzinfo=UTC)
ONE_MONTH_LATER = datetime(2026, 12, 14, 9, 30, tzinfo=UTC)
REFERRER = UserDocument(
    id="64a0000000000000000000a1", first_name="Aryan", email="aryan@example.com"
)
FRIEND = UserDocument(id="64a0000000000000000000f1", first_name="Priya", email="priya@example.com")
SUB_ID = "sub_referrer"


def _referral(**overrides: object) -> ReferralDocument:
    fields: dict[str, object] = {
        "friend_user_id": FRIEND.id,
        "referrer_user_id": REFERRER.id,
        "code": "aryan-k7f2",
        "status": ReferredFriendStatus.PAID,
        "joined_at": PAID_AT,
        "paid_at": PAID_AT,
        "payment_id": "pay_1",
        "reward_state": ReferralRewardState.PENDING,
        "created_at": PAID_AT,
        "updated_at": PAID_AT,
    }
    return ReferralDocument.model_validate({**fields, **overrides})


def _payment(**overrides: object):
    fields: dict[str, object] = {
        "user_id": FRIEND.id,
        "email": FRIEND.email,
        "customer_id": "cus_friend",
    }
    payment = make_dodo_payment(**{**fields, **overrides})
    return payment.model_copy(update={"payment_id": "pay_1"})


def _subscription(
    dodo_subscription_id: str = SUB_ID, dodo_customer_id: str | None = None
) -> SubscriptionDocument:
    return SubscriptionDocument.model_validate(
        {
            "dodo_subscription_id": dodo_subscription_id,
            "dodo_customer_id": dodo_customer_id,
            "user_id": REFERRER.id,
            "product_id": "pdt_pro_monthly",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


@dataclass
class Seams:
    get_by_email: AsyncMock
    list_for_user: AsyncMock
    get_active: AsyncMock
    mark_paid: AsyncMock
    get_referral: AsyncMock
    update: AsyncMock
    list_banked: AsyncMock
    pin_target: AsyncMock
    dodo: MagicMock
    lock: MagicMock
    capture: MagicMock
    notify: AsyncMock
    apply_event: AsyncMock
    log: MagicMock

    def captured(self, kind: type) -> list[tuple[object, ...]]:
        return [
            (c.args[0], c.args[1], c.kwargs["dedupe"])
            for c in self.capture.call_args_list
            if isinstance(c.args[1], kind)
        ]

    def notification(self) -> dict[str, object]:
        (request,) = [c.args[0] for c in self.notify.await_args_list]
        return request.model_dump(exclude={"id", "created_at"})


@asynccontextmanager
async def _lease(*, held: bool) -> AsyncIterator[bool]:
    yield held


@pytest.fixture
def seams() -> Iterator[Seams]:
    users = {REFERRER.id: REFERRER, FRIEND.id: FRIEND}
    dodo = MagicMock()
    dodo.subscriptions.retrieve.side_effect = lambda sid: make_dodo_subscription(
        sid, "cus_referrer", NEXT_BILL
    )
    dodo.subscriptions.update.side_effect = (
        lambda sid, *, next_billing_date: make_dodo_subscription(
            sid, "cus_referrer", next_billing_date
        )
    )
    lock = MagicMock()
    lock.return_value.hold.side_effect = lambda: _lease(held=True)
    with (
        time_machine.travel(NOW, tick=False),
        patch(f"{REWARDS}.user_repository.get", AsyncMock(side_effect=users.get)),
        patch(f"{REWARDS}.user_repository.get_by_email", AsyncMock(return_value=None)) as by_email,
        patch(
            f"{REWARDS}.subscription_repository.list_for_user", AsyncMock(return_value=[])
        ) as list_for_user,
        patch(
            f"{REWARDS}.subscription_repository.get_active_for_user",
            AsyncMock(return_value=_subscription()),
        ) as get_active,
        patch(
            f"{REWARDS}.referral_repository.mark_paid", AsyncMock(return_value=_referral())
        ) as mark_paid,
        patch(f"{REWARDS}.referral_repository.get", AsyncMock(return_value=None)) as get_referral,
        patch(f"{REWARDS}.referral_repository.update", AsyncMock()) as update,
        patch(f"{REWARDS}.referral_repository.list_banked", AsyncMock(return_value=[])) as banked,
        patch(
            f"{REWARDS}.referral_repository.set_reward_target_if_unset",
            AsyncMock(side_effect=lambda _, target: _referral(reward_target_billing_date=target)),
        ) as pin_target,
        patch.object(payment_service, "client", dodo, create=True),
        patch(f"{REWARDS}.DistributedLock", lock),
        patch(f"{REWARDS}.capture") as capture,
        patch(
            f"{REWARDS}.notification_service.create_notification",
            AsyncMock(return_value=MagicMock()),
        ) as notify,
        patch(f"{REWARDS}.apply_subscription_event", AsyncMock()) as apply_event,
        patch(f"{REWARDS}.log") as log,
    ):
        yield Seams(
            by_email,
            list_for_user,
            get_active,
            mark_paid,
            get_referral,
            update,
            banked,
            pin_target,
            dodo,
            lock,
            capture,
            notify,
            apply_event,
            log,
        )


def _expected_notification(title_friend: str, body: str, reward: str) -> dict[str, object]:
    return NotificationRequest(
        user_id=REFERRER.id,
        source=NotificationSourceEnum.REFERRAL_REWARD,
        type=NotificationType.SUCCESS,
        priority=2,
        channels=[ChannelConfig(channel_type=CHANNEL_TYPE_INAPP)],
        content=NotificationContent(
            title=REWARD_APPLIED_TITLE.format(friend=title_friend), body=body
        ),
        metadata={"friend_user_id": FRIEND.id, "reward": reward},
    ).model_dump(exclude={"id", "created_at"})


class TestWhoConverts:
    @pytest.mark.parametrize(
        "payment",
        [_payment(amount=0), _payment().model_copy(update={"subscription_id": None})],
        ids=["free-checkout", "one-off-purchase"],
    )
    async def test_a_free_or_one_off_payment_converts_nobody(self, seams: Seams, payment) -> None:
        await record_friend_payment(payment)

        seams.mark_paid.assert_not_awaited()

    async def test_a_payment_of_one_minor_unit_converts(self, seams: Seams) -> None:
        await record_friend_payment(_payment(amount=1))

        seams.mark_paid.assert_awaited_once()

    async def test_the_payer_named_in_the_checkout_metadata_is_marked_paid(
        self, seams: Seams
    ) -> None:
        await record_friend_payment(_payment())

        seams.mark_paid.assert_awaited_once_with(FRIEND.id, payment_id="pay_1", paid_at=NOW)
        seams.get_by_email.assert_not_awaited()

    async def test_a_payment_without_metadata_is_matched_to_the_payers_account_by_email(
        self, seams: Seams
    ) -> None:
        seams.get_by_email.return_value = FRIEND

        await record_friend_payment(_payment(user_id=None))

        seams.get_by_email.assert_awaited_once_with(FRIEND.email)
        seams.mark_paid.assert_awaited_once_with(FRIEND.id, payment_id="pay_1", paid_at=NOW)

    async def test_a_payer_with_no_account_converts_nobody(self, seams: Seams) -> None:
        await record_friend_payment(_payment(user_id=None))

        seams.mark_paid.assert_not_awaited()

    async def test_someone_never_referred_records_nothing(self, seams: Seams) -> None:
        seams.mark_paid.return_value = None

        await record_friend_payment(_payment())

        seams.get_referral.assert_awaited_once_with(FRIEND.id)
        seams.capture.assert_not_called()
        seams.dodo.subscriptions.update.assert_not_called()

    @pytest.mark.parametrize(
        "stored",
        [
            _referral(payment_id="pay_earlier"),
            _referral(reward_state=ReferralRewardState.APPLIED),
        ],
        ids=["converted-by-another-payment", "reward-already-delivered"],
    )
    async def test_a_friend_already_converted_records_nothing(
        self, seams: Seams, stored: ReferralDocument
    ) -> None:
        seams.mark_paid.return_value = None
        seams.get_referral.return_value = stored

        await record_friend_payment(_payment())

        seams.capture.assert_not_called()
        seams.dodo.subscriptions.update.assert_not_called()

    async def test_a_redelivery_of_the_converting_payment_finishes_an_owed_reward(
        self, seams: Seams
    ) -> None:
        seams.mark_paid.return_value = None
        seams.get_referral.return_value = _referral()

        await record_friend_payment(_payment())

        seams.dodo.subscriptions.update.assert_called_once_with(
            SUB_ID, next_billing_date=ONE_MONTH_LATER
        )


class TestTheMonthMovesTheBill:
    async def test_the_referrers_next_bill_moves_one_month_and_everyone_hears(
        self, seams: Seams
    ) -> None:
        await record_friend_payment(_payment())

        seams.lock.assert_called_once_with(
            REWARD_LOCK_KEY_TEMPLATE.format(user_id=REFERRER.id),
            lease_seconds=REWARD_LOCK_LEASE_S,
            acquire_timeout_seconds=REWARD_LOCK_WAIT_S,
            renew_seconds=REWARD_LOCK_RENEW_S,
            max_hold_seconds=REWARD_LOCK_MAX_HOLD_S,
        )
        seams.get_active.assert_awaited_once_with(REFERRER.id)
        seams.dodo.subscriptions.retrieve.assert_called_once_with(SUB_ID)
        seams.pin_target.assert_awaited_once_with(FRIEND.id, ONE_MONTH_LATER)
        seams.dodo.subscriptions.update.assert_called_once_with(
            SUB_ID, next_billing_date=ONE_MONTH_LATER
        )
        moved = make_dodo_subscription(SUB_ID, "cus_referrer", ONE_MONTH_LATER)
        seams.apply_event.assert_awaited_once_with(
            SubscriptionEvent(
                kind=SubscriptionEventKind.BILLING_DATE_MOVED,
                occurred_at=NOW,
                data=DodoSubscriptionData.model_validate(moved.model_dump(mode="json")),
            )
        )
        seams.update.assert_awaited_once_with(
            FRIEND.id,
            ReferralUpdate(reward_state=ReferralRewardState.APPLIED, reward_applied_at=NOW),
        )
        seams.log.audit.assert_called_once_with(
            "referral free month applied",
            actor=REFERRER.id,
            resource=SUB_ID,
            provider="dodo",
        )
        assert seams.captured(ReferralConverted) == [
            (
                UserId(FRIEND.id),
                ReferralConverted(
                    referrer_id=REFERRER.id, landing_variant=None, self_referral=False
                ),
                Dedupe(key="pay_1", occurred_at=PAID_AT),
            )
        ]
        assert seams.captured(ReferralRewardGranted) == [
            (
                UserId(REFERRER.id),
                ReferralRewardGranted(friend_id=FRIEND.id, delivery="applied", months=1),
                Dedupe(key=FRIEND.id, occurred_at=PAID_AT),
            )
        ]
        seams.log.set_ns.assert_called_once_with("referral", converted=True, self_referral=False)
        assert seams.notification() == _expected_notification(
            "Priya", REWARD_APPLIED_BODY.format(date="Dec 14"), "applied"
        )

    async def test_the_landing_variant_and_a_missing_paid_time_reach_the_conversion_event(
        self, seams: Seams
    ) -> None:
        seams.mark_paid.return_value = _referral(
            landing_variant=ReferralCopyVariant.TIME_BACK, paid_at=None
        )

        await record_friend_payment(_payment())

        ((_, converted, dedupe),) = seams.captured(ReferralConverted)
        assert converted.landing_variant == "time_back"
        assert dedupe == Dedupe(key="pay_1", occurred_at=NOW)
        ((_, _, granted_dedupe),) = seams.captured(ReferralRewardGranted)
        assert granted_dedupe == Dedupe(key=FRIEND.id, occurred_at=NOW)

    async def test_a_retry_lands_on_the_date_pinned_by_the_first_attempt(
        self, seams: Seams
    ) -> None:
        pinned = datetime(2026, 12, 20, tzinfo=UTC)
        seams.pin_target.side_effect = None
        seams.pin_target.return_value = _referral(reward_target_billing_date=pinned)

        await record_friend_payment(_payment())

        seams.dodo.subscriptions.update.assert_called_once_with(SUB_ID, next_billing_date=pinned)

    async def test_a_bill_already_at_the_pinned_date_is_not_moved_again(self, seams: Seams) -> None:
        seams.pin_target.side_effect = None
        seams.pin_target.return_value = _referral(reward_target_billing_date=NEXT_BILL)

        await record_friend_payment(_payment())

        seams.dodo.subscriptions.update.assert_not_called()
        seams.apply_event.assert_not_awaited()
        assert call("referral", billing_date_already_moved=True) in seams.log.set_ns.mock_calls
        assert seams.notification()["content"]["body"] == REWARD_APPLIED_BODY.format(date="Nov 14")

    async def test_a_referral_deleted_mid_delivery_fails_loudly(self, seams: Seams) -> None:
        seams.pin_target.side_effect = None
        seams.pin_target.return_value = None

        with pytest.raises(RuntimeError, match=f"referral {FRIEND.id} vanished mid-delivery"):
            await record_friend_payment(_payment())

        seams.dodo.subscriptions.update.assert_not_called()

    async def test_a_reward_whose_lease_cannot_be_taken_fails_without_touching_the_bill(
        self, seams: Seams
    ) -> None:
        seams.lock.return_value.hold.side_effect = lambda: _lease(held=False)

        with pytest.raises(RuntimeError, match=re.escape(REWARD_LOCK_UNAVAILABLE)):
            await record_friend_payment(_payment())

        seams.dodo.subscriptions.update.assert_not_called()
        seams.update.assert_not_awaited()


class TestSelfReferral:
    async def test_paying_from_the_referrers_own_mailbox_earns_nothing(self, seams: Seams) -> None:
        await record_friend_payment(_payment(email="Aryan+alt@Example.com"))

        self._assert_self_referral(seams)
        seams.list_for_user.assert_not_awaited()

    async def test_paying_as_the_referrers_own_dodo_customer_earns_nothing(
        self, seams: Seams
    ) -> None:
        seams.list_for_user.return_value = [_subscription(), _subscription("")]

        await record_friend_payment(_payment(customer_id="cus_referrer"))

        seams.list_for_user.assert_awaited_once_with(REFERRER.id)
        seams.dodo.subscriptions.retrieve.assert_called_once_with(SUB_ID)
        self._assert_self_referral(seams)

    async def test_a_stored_customer_id_is_compared_without_asking_dodo(self, seams: Seams) -> None:
        seams.list_for_user.return_value = [_subscription(dodo_customer_id="cus_referrer")]

        await record_friend_payment(_payment(customer_id="cus_referrer"))

        seams.dodo.subscriptions.retrieve.assert_not_called()
        self._assert_self_referral(seams)

    async def test_an_old_subscription_dodo_no_longer_has_does_not_fail_the_payment(
        self, seams: Seams
    ) -> None:
        seams.list_for_user.return_value = [_subscription(), _subscription("sub_gone")]
        live = seams.dodo.subscriptions.retrieve.side_effect
        gone = NotFoundError(
            "gone", response=httpx.Response(404, request=httpx.Request("GET", "x")), body=None
        )

        def retrieve(sid: str):
            if sid == "sub_gone":
                raise gone
            return live(sid)

        seams.dodo.subscriptions.retrieve.side_effect = retrieve

        await record_friend_payment(_payment(customer_id="cus_friend"))

        seams.log.set_ns.assert_any_call("referral", converted=True, self_referral=False)
        seams.log.warning.assert_called_once_with(
            "referral self-check skipped a subscription Dodo no longer has",
            subscription_id="sub_gone",
        )

    async def test_a_referrer_without_an_email_is_still_checked_by_dodo_customer(
        self, seams: Seams
    ) -> None:
        no_email = REFERRER.model_copy(update={"email": None})
        seams.list_for_user.return_value = [_subscription()]
        with patch(
            f"{REWARDS}.user_repository.get",
            AsyncMock(side_effect={REFERRER.id: no_email, FRIEND.id: FRIEND}.get),
        ):
            await record_friend_payment(_payment(customer_id="cus_referrer"))

        self._assert_self_referral(seams)

    async def test_a_deleted_referrer_is_not_a_self_referral(self, seams: Seams) -> None:
        with patch(
            f"{REWARDS}.user_repository.get", AsyncMock(side_effect={FRIEND.id: FRIEND}.get)
        ):
            await record_friend_payment(_payment())

        seams.log.set_ns.assert_any_call("referral", converted=True, self_referral=False)

    @staticmethod
    def _assert_self_referral(seams: Seams) -> None:
        seams.update.assert_awaited_once_with(
            FRIEND.id, ReferralUpdate(reward_state=ReferralRewardState.SELF_REFERRAL)
        )
        ((_, converted, _),) = seams.captured(ReferralConverted)
        assert converted.self_referral is True
        seams.log.set_ns.assert_called_once_with("referral", converted=True, self_referral=True)
        assert seams.captured(ReferralRewardGranted) == []
        seams.dodo.subscriptions.update.assert_not_called()
        seams.lock.assert_not_called()


class TestBankedMonths:
    @pytest.mark.parametrize(
        "subscription", [None, _subscription("")], ids=["no-subscription", "no-dodo-id"]
    )
    async def test_a_referrer_without_a_live_subscription_banks_the_month(
        self, seams: Seams, subscription: SubscriptionDocument | None
    ) -> None:
        seams.get_active.return_value = subscription

        await record_friend_payment(_payment())

        ((friend_id, banked),) = [c.args for c in seams.update.await_args_list]
        assert friend_id == FRIEND.id
        # The pinned date is cleared, not left unset: a banked month re-pins when it applies.
        assert banked.model_dump(exclude_unset=True) == {
            "reward_state": ReferralRewardState.BANKED,
            "reward_target_billing_date": None,
        }
        seams.dodo.subscriptions.update.assert_not_called()
        assert [granted for _, granted, _ in seams.captured(ReferralRewardGranted)] == [
            ReferralRewardGranted(friend_id=FRIEND.id, delivery="banked", months=1)
        ]
        assert seams.notification() == _expected_notification("Priya", REWARD_BANKED_BODY, "banked")

    async def test_nothing_banked_applies_nothing_and_takes_no_lock(self, seams: Seams) -> None:
        assert await apply_banked_months(REFERRER.id) == 0

        seams.list_banked.assert_awaited_once_with(REFERRER.id)
        seams.lock.assert_not_called()

    async def test_a_resubscribed_referrer_gets_each_banked_month_without_a_second_grant(
        self, seams: Seams
    ) -> None:
        seams.list_banked.return_value = [_referral(reward_state=ReferralRewardState.BANKED)]

        assert await apply_banked_months(REFERRER.id) == 1

        assert seams.lock.call_args.args == (REWARD_LOCK_KEY_TEMPLATE.format(user_id=REFERRER.id),)
        seams.dodo.subscriptions.update.assert_called_once_with(
            SUB_ID, next_billing_date=ONE_MONTH_LATER
        )
        assert seams.captured(ReferralRewardGranted) == []
        assert seams.notification() == _expected_notification(
            "Priya", REWARD_APPLIED_BODY.format(date="Dec 14"), "applied"
        )

    async def test_each_delivery_reports_where_its_month_landed(self, seams: Seams) -> None:
        seams.get_active.return_value = None

        assert await deliver_rewards(REFERRER.id, [_referral()]) == [
            RewardDelivery(ReferralRewardState.BANKED)
        ]

    async def test_a_month_still_without_a_subscription_stays_banked_untouched(
        self, seams: Seams
    ) -> None:
        seams.list_banked.return_value = [_referral(reward_state=ReferralRewardState.BANKED)]
        seams.get_active.return_value = None

        assert await apply_banked_months(REFERRER.id) == 0

        seams.update.assert_not_awaited()
        seams.notify.assert_not_awaited()


class TestTheReferrerIsTold:
    async def test_a_friend_whose_account_is_gone_is_a_friend(self, seams: Seams) -> None:
        with patch(
            f"{REWARDS}.user_repository.get", AsyncMock(side_effect={REFERRER.id: REFERRER}.get)
        ):
            await record_friend_payment(_payment())

        assert seams.notification()["content"]["title"] == REWARD_APPLIED_TITLE.format(
            friend="A friend"
        )

    async def test_a_notification_that_was_not_created_is_logged(self, seams: Seams) -> None:
        seams.notify.return_value = None

        await record_friend_payment(_payment())

        seams.log.warning.assert_called_once_with(
            "Referral reward notification was not created",
            user_id=REFERRER.id,
            friend_user_id=FRIEND.id,
        )


class TestDatesAreUtc:
    """The notification names the UTC billing date even on a server in another zone."""

    LATE_BILL = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)

    async def test_a_moved_bill_is_named_by_its_utc_date(self, seams: Seams) -> None:
        seams.dodo.subscriptions.retrieve.side_effect = lambda sid: make_dodo_subscription(
            sid, "cus_referrer", self.LATE_BILL
        )

        with local_timezone("Asia/Kolkata"):
            await record_friend_payment(_payment())

        assert seams.notification()["content"]["body"] == REWARD_APPLIED_BODY.format(date="Dec 14")

    async def test_a_bill_already_moved_is_named_by_its_utc_date(self, seams: Seams) -> None:
        seams.dodo.subscriptions.retrieve.side_effect = lambda sid: make_dodo_subscription(
            sid, "cus_referrer", self.LATE_BILL
        )
        seams.pin_target.side_effect = None
        seams.pin_target.return_value = _referral(reward_target_billing_date=self.LATE_BILL)

        with local_timezone("Asia/Kolkata"):
            await record_friend_payment(_payment())

        assert seams.notification()["content"]["body"] == REWARD_APPLIED_BODY.format(date="Nov 14")
