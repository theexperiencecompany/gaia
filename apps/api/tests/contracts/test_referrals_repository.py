"""Contract tests for ReferralsRepository: the transitions that make conversion and rewards idempotent."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.db.repositories.referrals import ReferralsRepository
from app.models.payment_models import PlanDuration
from app.models.referral_models import (
    ReferralDocument,
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

    async def test_a_reward_target_is_pinned_once_and_cleared_on_banking(self, repo):
        await repo.attribute(_referral("friend"))
        target = NOW + timedelta(days=30)

        pinned = await repo.set_reward_target_if_unset("friend", target)
        retried = await repo.set_reward_target_if_unset("friend", target + timedelta(days=30))
        assert pinned.reward_target_billing_date == target
        assert retried.reward_target_billing_date == target

        await repo.update(
            "friend",
            ReferralUpdate(
                reward_state=ReferralRewardState.BANKED, reward_target_billing_date=None
            ),
        )
        later = target + timedelta(days=60)
        assert (
            await repo.set_reward_target_if_unset("friend", later)
        ).reward_target_billing_date == later

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
        assert [r.friend_user_id for r in await repo.list_banked("referrer")] == ["c", "b", "a"]
        assert await repo.list_banked("someone-else") == []
