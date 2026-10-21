"""Contract tests for ReferralInvitesRepository: a sender invites a friend once, and the day is countable."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.repositories.referral_invites import ReferralInvitesRepository
from app.models.referral_models import (
    ReferralInviteChannel,
    ReferralInviteDocument,
    ReferralInviteSurface,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
async def repo(raw_collection) -> ReferralInvitesRepository:
    await raw_collection.create_index([("sender_user_id", 1), ("recipient_email", 1)], unique=True)
    return ReferralInvitesRepository()


def _invite(sender: str, to: str, sent_at: datetime = NOW) -> ReferralInviteDocument:
    return ReferralInviteDocument(
        sender_user_id=sender,
        recipient_email=to,
        surface=ReferralInviteSurface.PAGE,
        channel=ReferralInviteChannel.GAIA,
        sent_at=sent_at,
    )


class TestReferralInvitesRepository:
    async def test_the_same_pair_is_claimed_once_but_other_senders_may_invite(self, repo):
        assert await repo.claim(_invite("a", "friend@x.com")) is not None
        assert await repo.claim(_invite("a", "friend@x.com")) is None
        assert await repo.claim(_invite("b", "friend@x.com")) is not None
        assert await repo.claim(_invite("b", "other@x.com")) is not None
        assert await repo.invited_by("a") == {"friend@x.com"}

    async def test_a_released_claim_can_be_retried(self, repo):
        claim = await repo.claim(_invite("a", "friend@x.com"))
        await repo.release(claim.id)
        assert await repo.claim(_invite("a", "friend@x.com")) is not None
