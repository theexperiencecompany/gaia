"""The one referral-nudge budget: pitches claim a weekly slot, reward notes never wait, dismissals pause."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.referrals import NUDGE_CAP_WINDOW, NUDGE_PAUSE, ReferralNudge
from app.models.referral_models import ReferralNudgeStateDocument
from app.services.referrals.nudges import dismiss_nudge, record_announcement, send_pitch
from shared.py.analytics import UserId
from shared.py.analytics.catalog.referrals import ReferralNudgeDismissed, ReferralNudgeSent

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NOW = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
MODULE = "app.services.referrals.nudges"


@dataclass
class Seams:
    repo: MagicMock
    subscribed: AsyncMock
    capture: MagicMock
    deliver: AsyncMock


@pytest.fixture
def seams() -> Iterator[Seams]:
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.claim = AsyncMock(return_value=ReferralNudgeStateDocument(user_id=USER_ID))
    repo.release = AsyncMock()
    repo.stamp = AsyncMock()
    with (
        patch(f"{MODULE}.referral_nudge_repository", repo),
        patch(
            f"{MODULE}.subscription_repository.get_active_for_user",
            AsyncMock(return_value=object()),
        ) as subscribed,
        patch(f"{MODULE}.capture") as capture,
        patch(f"{MODULE}.datetime") as clock,
    ):
        clock.now.return_value = NOW
        yield Seams(repo, subscribed, capture, AsyncMock(return_value=True))


class TestSendPitch:
    async def test_a_delivered_pitch_takes_the_week_and_is_counted(self, seams: Seams) -> None:
        assert await send_pitch(USER_ID, ReferralNudge.CHAT_CARD, seams.deliver) is True

        seams.repo.claim.assert_awaited_once_with(
            USER_ID, ReferralNudge.CHAT_CARD, NOW, window_start=NOW - NUDGE_CAP_WINDOW, once=False
        )
        seams.deliver.assert_awaited_once()
        seams.capture.assert_called_once_with(
            UserId(USER_ID), ReferralNudgeSent(nudge=ReferralNudge.CHAT_CARD.value)
        )

    async def test_a_once_only_pitch_claims_as_once_only(self, seams: Seams) -> None:
        await send_pitch(USER_ID, ReferralNudge.WEEK_ONE_DM, seams.deliver)
        assert seams.repo.claim.call_args.kwargs["once"] is True

    async def test_a_refused_claim_sends_nothing(self, seams: Seams) -> None:
        seams.repo.claim.return_value = None

        assert await send_pitch(USER_ID, ReferralNudge.CHAT_CARD, seams.deliver) is False
        seams.deliver.assert_not_awaited()
        seams.capture.assert_not_called()

    async def test_a_user_without_a_subscription_is_never_pitched(self, seams: Seams) -> None:
        seams.subscribed.return_value = None

        assert await send_pitch(USER_ID, ReferralNudge.NURTURE_EMAIL, seams.deliver) is False
        seams.repo.claim.assert_not_awaited()
        seams.deliver.assert_not_awaited()

    async def test_a_pitch_that_did_not_go_out_gives_the_week_back(self, seams: Seams) -> None:
        prior = ReferralNudgeStateDocument(user_id=USER_ID, last_nudged_at=NOW - timedelta(days=9))
        seams.repo.get.return_value = prior
        seams.deliver.return_value = False

        assert await send_pitch(USER_ID, ReferralNudge.WEEK_ONE_DM, seams.deliver) is False
        seams.repo.release.assert_awaited_once_with(
            USER_ID, ReferralNudge.WEEK_ONE_DM, NOW, prior=prior
        )
        seams.capture.assert_not_called()

    async def test_a_failed_delivery_gives_the_week_back_and_raises(self, seams: Seams) -> None:
        seams.deliver.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            await send_pitch(USER_ID, ReferralNudge.NURTURE_EMAIL, seams.deliver)
        seams.repo.release.assert_awaited_once()
        seams.capture.assert_not_called()

    async def test_a_reward_note_is_not_a_pitch(self, seams: Seams) -> None:
        with pytest.raises(ValueError, match="reward_email"):
            await send_pitch(USER_ID, ReferralNudge.REWARD_EMAIL, seams.deliver)
        seams.deliver.assert_not_awaited()


class TestRecordAnnouncement:
    async def test_a_reward_note_starts_the_week_and_is_counted(self, seams: Seams) -> None:
        await record_announcement(USER_ID, ReferralNudge.REWARD_DM)

        seams.repo.stamp.assert_awaited_once_with(USER_ID, ReferralNudge.REWARD_DM, NOW)
        seams.capture.assert_called_once_with(
            UserId(USER_ID), ReferralNudgeSent(nudge=ReferralNudge.REWARD_DM.value)
        )

    async def test_a_pitch_cannot_skip_the_cap(self, seams: Seams) -> None:
        with pytest.raises(ValueError, match="chat_card"):
            await record_announcement(USER_ID, ReferralNudge.CHAT_CARD)
        seams.repo.stamp.assert_not_awaited()


class TestDismissNudge:
    @pytest.mark.parametrize(("paused_until", "paused"), [(None, False), (NOW + NUDGE_PAUSE, True)])
    async def test_the_dismissal_that_pauses_says_so(
        self, seams: Seams, paused_until: datetime | None, paused: bool
    ) -> None:
        seams.repo.record_dismissal = AsyncMock(
            return_value=ReferralNudgeStateDocument(user_id=USER_ID, paused_until=paused_until)
        )

        assert await dismiss_nudge(USER_ID, ReferralNudge.CHAT_CARD) is paused
        seams.capture.assert_called_once_with(
            UserId(USER_ID),
            ReferralNudgeDismissed(nudge=ReferralNudge.CHAT_CARD.value, paused=paused),
        )

    async def test_an_old_pause_is_not_this_dismissals_pause(self, seams: Seams) -> None:
        seams.repo.record_dismissal = AsyncMock(
            return_value=ReferralNudgeStateDocument(
                user_id=USER_ID, dismissals=1, paused_until=NOW - timedelta(days=1)
            )
        )
        assert await dismiss_nudge(USER_ID, ReferralNudge.CHAT_CARD) is False
