"""Contract tests for ReferralsRepository: the transitions that make conversion and rewards idempotent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.referrals import ReferralsRepository
from app.models.payment_models import PlanDuration
from app.models.referral_models import (
    ReferralDocument,
    ReferralRevokeReason,
    ReferralRewardState,
    ReferralUpdate,
    ReferredFriendStatus,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(raw_collection) -> ReferralsRepository:
    await raw_collection.create_index("friend_user_id", unique=True)
    return ReferralsRepository()


def _referral(
    friend: str, referrer: str = "referrer", joined_at: datetime = NOW
) -> ReferralDocument:
    return ReferralDocument(
        friend_user_id=friend,
        referrer_user_id=referrer,
        code="aryan-k7f2",
        joined_at=joined_at,
        created_at=joined_at,
        updated_at=joined_at,
    )


class TestReferralsRepository:
    async def test_a_friend_is_attributed_once_and_the_first_referrer_keeps_them(self, repo):
        assert await repo.attribute(_referral("friend", "first")) is not None
        assert await repo.attribute(_referral("friend", "second")) is None
        stored = await repo.get("friend")
        assert stored is not None and stored.referrer_user_id == "first"
        assert stored.status is ReferredFriendStatus.JOINED

    async def test_mark_paid_converts_a_joined_friend_exactly_once(self, repo):
        await repo.attribute(_referral("friend"))

        racing = await asyncio.gather(
            *(repo.mark_paid("friend", payment_id=f"pay_{i}", paid_at=NOW) for i in range(4))
        )

        winners = [r for r in racing if r is not None]
        assert len(winners) == 1
        assert winners[0].status is ReferredFriendStatus.PAID
        assert winners[0].reward_state is ReferralRewardState.PENDING
        assert winners[0].payment_id in {f"pay_{i}" for i in range(4)}
        assert winners[0].paid_at.replace(tzinfo=UTC) == NOW
        assert (await repo.get("friend")).payment_id == winners[0].payment_id

    async def test_mark_paid_ignores_someone_never_referred(self, repo):
        assert await repo.mark_paid("stranger", payment_id="pay", paid_at=NOW) is None

    async def test_the_first_gift_code_per_cycle_wins_and_others_read_it_back(self, repo):
        await repo.attribute(_referral("friend"))

        first = await repo.set_gift_code("friend", PlanDuration.MONTHLY, "CODE1")
        second = await repo.set_gift_code("friend", PlanDuration.MONTHLY, "CODE2")
        yearly = await repo.set_gift_code("friend", PlanDuration.YEARLY, "CODE3")

        assert first.gift_codes == {PlanDuration.MONTHLY: "CODE1"}
        assert second.gift_codes[PlanDuration.MONTHLY] == "CODE1"
        assert yearly.gift_codes == {PlanDuration.MONTHLY: "CODE1", PlanDuration.YEARLY: "CODE3"}
        assert await repo.set_gift_code("stranger", PlanDuration.MONTHLY, "X") is None

    async def test_a_refused_gift_code_is_swapped_once_and_a_racing_swap_reads_the_winner(
        self, repo
    ):
        await repo.attribute(_referral("friend"))
        await repo.set_gift_code("friend", PlanDuration.MONTHLY, "OLD")

        first = await repo.replace_gift_code(
            "friend", PlanDuration.MONTHLY, refused="OLD", fresh="NEW1"
        )
        racing = await repo.replace_gift_code(
            "friend", PlanDuration.MONTHLY, refused="OLD", fresh="NEW2"
        )

        assert first.gift_codes[PlanDuration.MONTHLY] == "NEW1"
        assert racing.gift_codes[PlanDuration.MONTHLY] == "NEW1"

    async def test_a_reward_target_is_pinned_once_per_subscription_and_cleared_on_banking(
        self, repo
    ):
        await repo.attribute(_referral("friend"))
        target = NOW + timedelta(days=30)

        pinned = await repo.pin_reward_target("friend", subscription_id="sub_1", target=target)
        retried = await repo.pin_reward_target(
            "friend", subscription_id="sub_1", target=target + timedelta(days=30)
        )
        assert (pinned.reward_target_billing_date, pinned.reward_subscription_id) == (
            target,
            "sub_1",
        )
        assert retried.reward_target_billing_date == target

        resubscribed = await repo.pin_reward_target(
            "friend", subscription_id="sub_2", target=target + timedelta(days=45)
        )
        assert resubscribed.reward_target_billing_date == target + timedelta(days=45)

        await repo.update(
            "friend",
            ReferralUpdate(
                reward_state=ReferralRewardState.BANKED,
                reward_subscription_id=None,
                reward_target_billing_date=None,
            ),
        )
        later = target + timedelta(days=60)
        assert (
            await repo.pin_reward_target("friend", subscription_id="sub_2", target=later)
        ).reward_target_billing_date == later

    async def test_a_revocation_is_recorded_once_and_only_for_a_first_payment(self, repo):
        await repo.attribute(_referral("friend"))
        await repo.mark_paid("friend", payment_id="pay_first", paid_at=NOW)

        asked = await repo.request_revocation(
            "pay_first", reason=ReferralRevokeReason.REFUND, at=NOW
        )
        again = await repo.request_revocation(
            "pay_first", reason=ReferralRevokeReason.DISPUTE, at=NOW + timedelta(days=1)
        )

        assert asked is not None and asked.revoke_reason is ReferralRevokeReason.REFUND
        assert asked.revocation_owed
        assert again is None
        assert (
            await repo.request_revocation("pay_renewal", reason=ReferralRevokeReason.REFUND, at=NOW)
            is None
        )
        assert (await repo.get_by_payment_id("pay_first")).friend_user_id == "friend"

    async def test_a_self_referral_has_no_month_to_revoke(self, repo):
        await repo.attribute(_referral("friend"))
        await repo.mark_paid("friend", payment_id="pay_first", paid_at=NOW)
        await repo.update("friend", ReferralUpdate(reward_state=ReferralRewardState.SELF_REFERRAL))

        assert (
            await repo.request_revocation("pay_first", reason=ReferralRevokeReason.REFUND, at=NOW)
            is None
        )

    async def test_a_revoke_target_is_pinned_once(self, repo):
        await repo.attribute(_referral("friend"))
        target = NOW + timedelta(days=10)

        await repo.pin_revoke_target("friend", target)
        retried = await repo.pin_revoke_target("friend", target - timedelta(days=30))

        assert retried.revoke_target_billing_date == target

    async def test_listings_are_scoped_to_the_referrer_and_ordered(self, repo):
        joined = {"a": NOW - timedelta(days=1), "b": NOW - timedelta(days=2), "c": NOW}
        paid = {"a": NOW, "b": NOW - timedelta(hours=1), "c": NOW - timedelta(hours=2)}
        for friend in ("a", "b", "c"):
            await repo.attribute(_referral(friend, joined_at=joined[friend]))
        await repo.attribute(_referral("other", referrer="someone-else"))
        for friend in ("a", "b", "c"):
            await repo.mark_paid(friend, payment_id=f"pay_{friend}", paid_at=paid[friend])
            await repo.update(friend, ReferralUpdate(reward_state=ReferralRewardState.BANKED))

        assert [r.friend_user_id for r in await repo.list_for_referrer("referrer")] == [
            "c",
            "a",
            "b",
        ]
        assert [r.friend_user_id for r in await repo.list_owed("referrer")] == ["c", "b", "a"]
        assert await repo.list_owed("someone-else") == []

    async def test_owed_rewards_are_pending_banked_or_asked_back_and_never_final(self, repo):
        states = {
            "pending": ReferralRewardState.PENDING,
            "banked": ReferralRewardState.BANKED,
            "applied": ReferralRewardState.APPLIED,
            "refunded": ReferralRewardState.APPLIED,
            "revoked": ReferralRewardState.APPLIED,
            "self": ReferralRewardState.SELF_REFERRAL,
        }
        for offset, (friend, state) in enumerate(states.items()):
            await repo.attribute(_referral(friend))
            await repo.mark_paid(
                friend, payment_id=f"pay_{friend}", paid_at=NOW + timedelta(minutes=offset)
            )
            await repo.update(friend, ReferralUpdate(reward_state=state))
        for friend in ("refunded", "revoked"):
            await repo.request_revocation(
                f"pay_{friend}", reason=ReferralRevokeReason.REFUND, at=NOW
            )
        await repo.update("revoked", ReferralUpdate(reward_state=ReferralRewardState.REVOKED))

        assert [r.friend_user_id for r in await repo.list_owed("referrer")] == [
            "pending",
            "banked",
            "refunded",
        ]

    async def test_the_sweep_finds_each_referrer_with_a_month_pending_past_the_cutoff(self, repo):
        for friend, referrer, minutes in (("a", "r1", 30), ("b", "r1", 20), ("c", "r2", 1)):
            await repo.attribute(_referral(friend, referrer=referrer))
            await repo.mark_paid(
                friend, payment_id=f"pay_{friend}", paid_at=NOW - timedelta(minutes=minutes)
            )
        await repo.attribute(_referral("d", referrer="r3"))
        await repo.mark_paid("d", payment_id="pay_d", paid_at=NOW - timedelta(hours=1))
        await repo.update("d", ReferralUpdate(reward_state=ReferralRewardState.APPLIED))

        assert await repo.list_referrers_unsettled(NOW - timedelta(minutes=15), limit=10) == ["r1"]
