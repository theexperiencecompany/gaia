"""Contract tests for ReferralNudgesRepository: one claim per window, once-only nudges, dismissals that pause."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.constants.referrals import ReferralNudge
from app.db.repositories.referral_nudges import ReferralNudgesRepository

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
WEEK_AGO = NOW - timedelta(days=7)
PAUSE = timedelta(days=30)


@pytest.fixture
async def repo(raw_collection) -> ReferralNudgesRepository:
    await raw_collection.create_index("user_id", unique=True)
    return ReferralNudgesRepository()


async def _claim(
    repo: ReferralNudgesRepository,
    nudge: ReferralNudge = ReferralNudge.CHAT_CARD,
    *,
    at: datetime = NOW,
    once: bool = False,
    user: str = "u1",
) -> bool:
    claimed = await repo.claim(user, nudge, at, window_start=at - timedelta(days=7), once=once)
    return claimed is not None


class TestClaim:
    async def test_a_user_gets_one_claim_per_window_and_another_after_it(self, repo):
        assert await _claim(repo)
        assert not await _claim(repo, ReferralNudge.WEEK_ONE_DM, at=NOW + timedelta(days=6))
        assert await _claim(repo, at=NOW + timedelta(days=7, seconds=1))

    async def test_claims_are_per_user(self, repo):
        assert await _claim(repo, user="u1")
        assert await _claim(repo, user="u2")

    async def test_a_once_only_nudge_never_repeats_even_after_the_window(self, repo):
        assert await _claim(repo, ReferralNudge.WEEK_ONE_DM, once=True)
        later = NOW + timedelta(days=60)
        assert not await _claim(repo, ReferralNudge.WEEK_ONE_DM, at=later, once=True)
        assert await _claim(repo, ReferralNudge.CHAT_CARD, at=later, once=True)

    async def test_a_claim_stamps_the_nudge_and_the_window(self, repo):
        await _claim(repo, ReferralNudge.WEEK_ONE_DM)
        state = await repo.get("u1")
        assert state is not None
        assert state.last_nudged_at == NOW
        assert state.sent_at == {ReferralNudge.WEEK_ONE_DM: NOW}


class TestRelease:
    async def test_a_released_claim_gives_the_window_and_the_once_only_slot_back(self, repo):
        await _claim(repo, ReferralNudge.CHAT_CARD, at=WEEK_AGO - timedelta(days=1))
        before = await repo.get("u1")
        await _claim(repo, ReferralNudge.WEEK_ONE_DM, once=True)

        await repo.release("u1", ReferralNudge.WEEK_ONE_DM, NOW, prior=before)

        state = await repo.get("u1")
        assert state is not None
        assert state.last_nudged_at == WEEK_AGO - timedelta(days=1)
        assert ReferralNudge.WEEK_ONE_DM not in state.sent_at
        assert await _claim(repo, ReferralNudge.WEEK_ONE_DM, once=True)

    async def test_a_released_repeat_restores_the_nudges_previous_stamp(self, repo):
        earlier = NOW - timedelta(days=10)
        await _claim(repo, ReferralNudge.CHAT_CARD, at=earlier)
        before = await repo.get("u1")
        await _claim(repo, ReferralNudge.CHAT_CARD)

        await repo.release("u1", ReferralNudge.CHAT_CARD, NOW, prior=before)

        state = await repo.get("u1")
        assert state is not None
        assert state.last_nudged_at == earlier
        assert state.sent_at == {ReferralNudge.CHAT_CARD: earlier}

    async def test_releasing_a_first_ever_claim_leaves_no_window(self, repo):
        await _claim(repo)
        await repo.release("u1", ReferralNudge.CHAT_CARD, NOW, prior=None)
        state = await repo.get("u1")
        assert state is not None
        assert state.last_nudged_at is None
        assert state.sent_at == {}


class TestStamp:
    async def test_a_stamp_ignores_the_window_but_starts_a_new_one(self, repo):
        await _claim(repo)
        await repo.stamp("u1", ReferralNudge.REWARD_EMAIL, NOW + timedelta(days=1))
        state = await repo.get("u1")
        assert state is not None
        assert state.last_nudged_at == NOW + timedelta(days=1)
        assert state.sent_at[ReferralNudge.REWARD_EMAIL] == NOW + timedelta(days=1)
        assert not await _claim(repo, at=NOW + timedelta(days=7, hours=1))

    async def test_a_stamp_creates_the_state_of_a_user_never_nudged(self, repo):
        await repo.stamp("u1", ReferralNudge.REWARD_DM, NOW)
        state = await repo.get("u1")
        assert state is not None
        assert state.sent_at == {ReferralNudge.REWARD_DM: NOW}


class TestDismiss:
    async def test_the_second_dismissal_pauses_every_claim_for_the_pause(self, repo):
        first = await repo.record_dismissal("u1", NOW, dismissals_to_pause=2, pause=PAUSE)
        assert first.paused_until is None
        second = await repo.record_dismissal("u1", NOW, dismissals_to_pause=2, pause=PAUSE)
        assert second.paused_until == NOW + PAUSE
        assert second.dismissals == 0

        assert not await _claim(repo, at=NOW + PAUSE - timedelta(seconds=1))
        assert await _claim(repo, at=NOW + PAUSE)

    async def test_a_pause_restarts_the_count(self, repo):
        for _ in range(2):
            await repo.record_dismissal("u1", NOW, dismissals_to_pause=2, pause=PAUSE)
        third = await repo.record_dismissal("u1", NOW + PAUSE, dismissals_to_pause=2, pause=PAUSE)
        assert third.dismissals == 1
        assert third.paused_until == NOW + PAUSE


def test_a_state_that_vanished_mid_update_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="^referral nudge state for u1 vanished mid-update$"):
        ReferralNudgesRepository._require(None, "u1")
