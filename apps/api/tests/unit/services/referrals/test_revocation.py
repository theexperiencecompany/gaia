"""Taking a month back on a refund or dispute, decided over mocked repositories and Dodo."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import time_machine

from app.models.referral_models import (
    ReferralDocument,
    ReferralRevokeReason,
    ReferralRewardState,
    ReferralUpdate,
    ReferredFriendStatus,
)
from app.services.payments.payment_service import payment_service
from app.services.referrals.revocation import reclaim_reward, request_reward_revocation
from shared.py.analytics import Dedupe, UserId
from shared.py.analytics.catalog.referrals import ReferralRewardRevoked
from tests.factories import make_dodo_subscription
from tests.helpers import captured_wide_event

REVOCATION = "app.services.referrals.revocation"
BILLING_DATE = "app.services.referrals.billing_date"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
REFUNDED_AT = datetime(2026, 11, 20, 11, 0, tzinfo=UTC)
REFERRER_ID = "64a0000000000000000000a1"
FRIEND_ID = "64a0000000000000000000f1"
SUB_ID = "sub_referrer"
# The friend's month moved the bill from Dec 14 to Jan 14.
ORIGINAL_BILL = datetime(2026, 12, 14, 9, 30, tzinfo=UTC)
MOVED_BILL = datetime(2027, 1, 14, 9, 30, tzinfo=UTC)


def _referral(**overrides: object) -> ReferralDocument:
    fields: dict[str, object] = {
        "friend_user_id": FRIEND_ID,
        "referrer_user_id": REFERRER_ID,
        "code": "aryan-k7f2",
        "status": ReferredFriendStatus.PAID,
        "joined_at": REFUNDED_AT,
        "paid_at": REFUNDED_AT,
        "payment_id": "pay_1",
        "reward_state": ReferralRewardState.APPLIED,
        "reward_subscription_id": SUB_ID,
        "reward_target_billing_date": MOVED_BILL,
        "revoke_reason": ReferralRevokeReason.REFUND,
        "revoked_at": REFUNDED_AT,
        "created_at": REFUNDED_AT,
        "updated_at": REFUNDED_AT,
    }
    return ReferralDocument.model_validate({**fields, **overrides})


@dataclass
class Seams:
    request: AsyncMock
    by_payment: AsyncMock
    pin: AsyncMock
    update: AsyncMock
    queue: AsyncMock
    dodo: MagicMock
    capture: MagicMock

    def revoked(self) -> ReferralRewardRevoked:
        (captured,) = self.capture.call_args_list
        distinct_id, event = captured.args
        assert distinct_id == UserId(REFERRER_ID)
        assert captured.kwargs["dedupe"] == Dedupe(key=FRIEND_ID, occurred_at=REFUNDED_AT)
        return event

    def live_bill(self, date: datetime) -> None:
        self.dodo.subscriptions.retrieve.side_effect = lambda sid: make_dodo_subscription(
            sid, "cus_referrer", date
        )


@pytest.fixture
def seams() -> Iterator[Seams]:
    dodo = MagicMock()
    dodo.subscriptions.update.side_effect = (
        lambda sid, *, next_billing_date: make_dodo_subscription(
            sid, "cus_referrer", next_billing_date
        )
    )
    with (
        time_machine.travel(NOW, tick=False),
        patch(f"{REVOCATION}.referral_repository.request_revocation", AsyncMock()) as request,
        patch(
            f"{REVOCATION}.referral_repository.get_by_payment_id", AsyncMock(return_value=None)
        ) as by_payment,
        patch(
            f"{REVOCATION}.referral_repository.pin_revoke_target",
            AsyncMock(side_effect=lambda _, target: _referral(revoke_target_billing_date=target)),
        ) as pin,
        patch(f"{REVOCATION}.referral_repository.update", AsyncMock()) as update,
        patch(f"{REVOCATION}.queue_settlement", AsyncMock()) as queue,
        patch.object(payment_service, "client", dodo, create=True),
        patch(f"{BILLING_DATE}.apply_subscription_event", AsyncMock()),
        patch(f"{REVOCATION}.capture") as capture,
    ):
        seams = Seams(request, by_payment, pin, update, queue, dodo, capture)
        seams.live_bill(MOVED_BILL)
        yield seams


class TestTheRequest:
    async def test_a_refunded_first_payment_records_the_request_and_queues_the_referrer(
        self, seams: Seams
    ) -> None:
        seams.request.return_value = _referral()

        async with captured_wide_event() as event:
            await request_reward_revocation("pay_1", ReferralRevokeReason.REFUND)

        seams.request.assert_awaited_once_with("pay_1", reason=ReferralRevokeReason.REFUND, at=NOW)
        seams.queue.assert_awaited_once_with(REFERRER_ID, friend_user_id=FRIEND_ID)
        assert event["referral"] == {"revoke": "refund", "referrer_id": REFERRER_ID}

    async def test_a_redelivered_refund_queues_a_revocation_not_yet_settled_again(
        self, seams: Seams
    ) -> None:
        seams.request.return_value = None
        seams.by_payment.return_value = _referral()

        await request_reward_revocation("pay_1", ReferralRevokeReason.REFUND)

        seams.by_payment.assert_awaited_once_with("pay_1")
        seams.queue.assert_awaited_once_with(REFERRER_ID, friend_user_id=FRIEND_ID)

    @pytest.mark.parametrize(
        "stored",
        [None, _referral(reward_state=ReferralRewardState.REVOKED)],
        ids=["payment-converted-nobody", "already-revoked"],
    )
    async def test_nothing_to_take_back_queues_nothing(
        self, seams: Seams, stored: ReferralDocument | None
    ) -> None:
        seams.request.return_value = None
        seams.by_payment.return_value = stored

        async with captured_wide_event() as event:
            await request_reward_revocation("pay_1", ReferralRevokeReason.DISPUTE)

        seams.queue.assert_not_awaited()
        assert event["referral"] == {"revoke": "nothing_to_revoke"}


class TestTheMonthComesBack:
    async def test_an_applied_month_not_yet_begun_moves_the_bill_back_a_month(
        self, seams: Seams
    ) -> None:
        async with captured_wide_event() as event:
            await reclaim_reward(_referral(), SUB_ID)

        seams.pin.assert_awaited_once_with(FRIEND_ID, ORIGINAL_BILL)
        seams.dodo.subscriptions.update.assert_called_once_with(
            SUB_ID, next_billing_date=ORIGINAL_BILL
        )
        seams.update.assert_awaited_once_with(
            FRIEND_ID, ReferralUpdate(reward_state=ReferralRewardState.REVOKED)
        )
        assert seams.revoked() == ReferralRewardRevoked(
            friend_id=FRIEND_ID, reason="refund", prior_state="applied", reclaimed=True
        )
        assert event["referral"] == {"revoked": "refund", "month_reclaimed": True}
        assert event["audit"] == [
            {
                "msg": "referral free month taken back",
                "actor": REFERRER_ID,
                "resource": SUB_ID,
                "provider": "dodo",
            }
        ]

    async def test_a_retry_after_the_bill_moved_back_does_not_move_it_again(
        self, seams: Seams
    ) -> None:
        seams.live_bill(ORIGINAL_BILL)
        seams.pin.side_effect = None
        seams.pin.return_value = _referral(revoke_target_billing_date=ORIGINAL_BILL)

        async with captured_wide_event() as event:
            await reclaim_reward(_referral(), SUB_ID)

        seams.dodo.subscriptions.update.assert_not_called()
        assert seams.revoked().reclaimed is True
        assert event["referral"] == {
            "billing_date_already_moved_back": True,
            "revoked": "refund",
            "month_reclaimed": True,
        }

    @pytest.mark.parametrize(
        "now",
        [ORIGINAL_BILL, datetime(2026, 12, 20, tzinfo=UTC)],
        ids=["the-instant-it-begins", "days-into-it"],
    )
    async def test_a_month_already_under_way_stays_with_the_referrer(
        self, seams: Seams, now: datetime
    ) -> None:
        # The Dec 14 bill it would move back to is no longer ahead: the free month has begun.
        with time_machine.travel(now, tick=False):
            await reclaim_reward(_referral(), SUB_ID)

        seams.dodo.subscriptions.update.assert_not_called()
        assert seams.revoked().reclaimed is False

    async def test_a_month_on_a_subscription_since_ended_is_not_taken_from_the_new_one(
        self, seams: Seams
    ) -> None:
        await reclaim_reward(_referral(), "sub_new")

        seams.dodo.subscriptions.retrieve.assert_not_called()
        assert seams.revoked().reclaimed is False

    async def test_a_banked_month_is_dropped_without_asking_dodo(self, seams: Seams) -> None:
        await reclaim_reward(
            _referral(reward_state=ReferralRewardState.BANKED, reward_subscription_id=None), None
        )

        seams.dodo.subscriptions.retrieve.assert_not_called()
        assert seams.revoked() == ReferralRewardRevoked(
            friend_id=FRIEND_ID, reason="refund", prior_state="banked", reclaimed=True
        )

    async def test_a_pending_month_whose_move_never_landed_is_dropped(self, seams: Seams) -> None:
        seams.live_bill(ORIGINAL_BILL)

        await reclaim_reward(_referral(reward_state=ReferralRewardState.PENDING), SUB_ID)

        seams.pin.assert_not_awaited()
        seams.dodo.subscriptions.update.assert_not_called()
        assert seams.revoked() == ReferralRewardRevoked(
            friend_id=FRIEND_ID, reason="refund", prior_state="pending", reclaimed=True
        )

    async def test_a_pending_month_whose_move_landed_before_its_job_died_is_moved_back(
        self, seams: Seams
    ) -> None:
        await reclaim_reward(_referral(reward_state=ReferralRewardState.PENDING), SUB_ID)

        seams.dodo.subscriptions.update.assert_called_once_with(
            SUB_ID, next_billing_date=ORIGINAL_BILL
        )

    async def test_a_referral_deleted_mid_revocation_fails_loudly(self, seams: Seams) -> None:
        seams.pin.side_effect = None
        seams.pin.return_value = None

        with pytest.raises(RuntimeError, match=f"referral {FRIEND_ID} vanished mid-revocation"):
            await reclaim_reward(_referral(), SUB_ID)

        seams.dodo.subscriptions.update.assert_not_called()
        seams.update.assert_not_awaited()

    async def test_a_referral_with_no_revocation_fails_loudly(self, seams: Seams) -> None:
        with pytest.raises(RuntimeError, match="has no revocation to settle"):
            await reclaim_reward(_referral(revoke_reason=None), SUB_ID)

        seams.update.assert_not_awaited()
