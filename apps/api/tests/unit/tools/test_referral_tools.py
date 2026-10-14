"""Unit tests for app.agents.tools.referral_tools: what the model reads about sharing GAIA.

The outputs are matched exactly on purpose: they are the tools' contract with
the model, and the price and link in them must be the live ones.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.referral_tools import (
    get_referral_link,
    get_referral_status,
    send_referral_invite,
    suggest_invitees,
)
from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import ReferralCopyVariant, ReferralLayoutVariant
from app.models.referral_models import (
    ReferralInviteStatus,
    ReferralInviteSurface,
    ReferralSuggestionReason,
    ReferredFriendStatus,
)
from app.schemas.referrals import (
    ReferralInviteRequest,
    ReferralInviteResponse,
    ReferralInviteResult,
    ReferralMeResponse,
    ReferralOffer,
    ReferralSuggestion,
    ReferralSuggestionsResponse,
    ReferredFriend,
)
from app.utils.errors import AppError
from shared.py.wide_events import log

MODULE = "app.agents.tools.referral_tools"
USER_ID = "507f1f77bcf86cd799439011"
NOW = datetime(2026, 10, 14, tzinfo=UTC)
LINK = "https://heygaia.io/invite/aryan-k7f2"
SHARE_TEXT = (
    "I've been using GAIA and it's honestly made my days lighter. "
    f"Here's GAIA for $15/month for your first 2 months 💛 {LINK}"
)
OFFER = ReferralOffer(
    currency="USD",
    monthly_regular_minor=3000,
    monthly_intro_minor=1500,
    intro_cycles=2,
    yearly_regular_minor=27000,
    yearly_discount_minor=3000,
)


@pytest.fixture(autouse=True)
def _clean_wide_event() -> None:
    log.reset()


@pytest.fixture
def tool_log() -> Iterator[MagicMock]:
    with patch(f"{MODULE}.log") as mock_log:
        yield mock_log


def _cfg(source: str = "web") -> dict[str, dict[str, str]]:
    return {"configurable": {"user_id": USER_ID, "conversation_source": source}}


def _overview(**overrides: object) -> ReferralMeResponse:
    fields: dict[str, object] = {
        "code": "aryan-k7f2",
        "share_link": LINK,
        "offer": OFFER,
        "months_earned": 0,
        "months_applied": 0,
        "months_banked": 0,
        "next_billing_date": None,
        "friends": [],
        "copy_variant": ReferralCopyVariant.GIFT,
        "layout_variant": ReferralLayoutVariant.TICKET,
    }
    fields.update(overrides)
    return ReferralMeResponse.model_validate(fields)


def _overview_returning(overview: ReferralMeResponse) -> AsyncMock:
    return AsyncMock(return_value=overview)


NOT_SUBSCRIBED = AsyncMock(
    side_effect=AppError(
        message="Subscribe to GAIA to get your invite link",
        status_code=403,
        code=REFERRAL_SUBSCRIPTION_REQUIRED,
    )
)
NO_LINK_TEXT = (
    "This user has no active subscription, so they have no invite link yet. "
    "Sharing GAIA opens up once they subscribe; say so plainly, without pushing an upgrade."
)


class TestGetReferralLink:
    async def test_the_link_comes_with_the_live_gift_and_a_message_to_share(
        self, tool_log: MagicMock
    ) -> None:
        overview = _overview_returning(_overview())
        with patch(f"{MODULE}.get_referral_overview", overview):
            result = await get_referral_link.coroutine(config=_cfg())

        overview.assert_awaited_once_with(USER_ID)
        tool_log.set.assert_called_once_with(
            tool={"name": "get_referral_link"}, referral={"operation": "agent_link"}
        )

        assert result == (
            f"Invite link: {LINK}\n"
            "Friends get GAIA for $15/month for their first 2 months, then $30/month. "
            "On a yearly plan they save $30 on their first year.\n"
            "The user gets a free month every time a friend pays.\n"
            "Message to share (hand it over exactly as written):\n"
            f"{SHARE_TEXT}"
        )

    async def test_a_user_without_a_subscription_has_no_link(self, tool_log: MagicMock) -> None:
        with patch(f"{MODULE}.get_referral_overview", NOT_SUBSCRIBED):
            assert await get_referral_link.coroutine(config=_cfg()) == NO_LINK_TEXT

        tool_log.set_ns.assert_called_once_with("referral", has_link=False)

    async def test_any_other_failure_is_not_mistaken_for_no_subscription(self) -> None:
        broken = AsyncMock(side_effect=AppError(message="User not found", status_code=404))
        with (
            patch(f"{MODULE}.get_referral_overview", broken),
            pytest.raises(AppError, match="User not found"),
        ):
            await get_referral_link.coroutine(config=_cfg())


class TestGetReferralStatus:
    async def test_months_friends_and_the_next_bill(self, tool_log: MagicMock) -> None:
        overview = _overview(
            months_earned=3,
            months_applied=2,
            months_banked=1,
            next_billing_date=datetime(2026, 12, 14, tzinfo=UTC),
            friends=[
                ReferredFriend(
                    first_name="Priya", status=ReferredFriendStatus.PAID, joined_at=NOW, paid_at=NOW
                ),
                ReferredFriend(first_name=None, status=ReferredFriendStatus.JOINED, joined_at=NOW),
            ],
        )
        reader = _overview_returning(overview)
        with patch(f"{MODULE}.get_referral_overview", reader):
            result = await get_referral_status.coroutine(config=_cfg())

        reader.assert_awaited_once_with(USER_ID)
        tool_log.set.assert_called_once_with(
            tool={"name": "get_referral_status"}, referral={"operation": "agent_status"}
        )
        tool_log.set_ns.assert_called_once_with("referral", friends=2, months_earned=3)
        assert result == (
            "Free months earned: 3 (2 already added to the billing date, "
            "1 saved for when they subscribe again)\n"
            "Next bill: 2026-12-14\n"
            "Friends who joined (2):\n"
            "  - Priya: paid, earned a free month\n"
            "  - (no name): joined, has not paid yet"
        )

    async def test_nobody_yet(self) -> None:
        with patch(f"{MODULE}.get_referral_overview", _overview_returning(_overview())):
            result = await get_referral_status.coroutine(config=_cfg())

        assert result == (
            "Free months earned: 0 (0 already added to the billing date, "
            "0 saved for when they subscribe again)\n"
            "Next bill: none scheduled\n"
            "Friends who joined: none yet"
        )

    async def test_a_user_without_a_subscription_is_told_so(self) -> None:
        with patch(f"{MODULE}.get_referral_overview", NOT_SUBSCRIBED):
            assert await get_referral_status.coroutine(config=_cfg()) == NO_LINK_TEXT


class TestSuggestInvitees:
    async def test_each_suggestion_carries_its_reason(self, tool_log: MagicMock) -> None:
        response = ReferralSuggestionsResponse(
            suggestions=[
                ReferralSuggestion(
                    name="Priya Shah",
                    email="priya@example.com",
                    reason=ReferralSuggestionReason.MET,
                    count=6,
                ),
                ReferralSuggestion(
                    email="bob@example.com", reason=ReferralSuggestionReason.EMAILED, count=9
                ),
            ]
        )
        compute = AsyncMock(return_value=response)
        with patch(f"{MODULE}.compute_suggestions", compute):
            result = await suggest_invitees.coroutine(config=_cfg())

        compute.assert_awaited_once_with(USER_ID)
        tool_log.set.assert_called_once_with(
            tool={"name": "suggest_invitees"}, referral={"operation": "agent_suggestions"}
        )
        assert result == (
            "People to invite (2), from the last 90 days:\n"
            "  - Priya Shah <priya@example.com>: met 6 times\n"
            "  - bob@example.com: emailed 9 times"
        )

    async def test_none_found(self) -> None:
        empty = ReferralSuggestionsResponse(suggestions=[])
        with patch(f"{MODULE}.compute_suggestions", AsyncMock(return_value=empty)):
            result = await suggest_invitees.coroutine(config=_cfg())

        assert result == (
            "No one to suggest right now. Suggestions come from the people the user "
            "meets in Google Calendar and emails in Gmail, when those are connected."
        )


class TestSendReferralInvite:
    async def test_on_the_web_each_address_reports_its_own_outcome(
        self, tool_log: MagicMock
    ) -> None:
        sent = AsyncMock(
            return_value=ReferralInviteResponse(
                results=[
                    ReferralInviteResult(
                        email="priya@example.com", status=ReferralInviteStatus.SENT
                    ),
                    ReferralInviteResult(
                        email="bob@example.com", status=ReferralInviteStatus.ALREADY_INVITED
                    ),
                    ReferralInviteResult(email="nope", status=ReferralInviteStatus.INVALID),
                    ReferralInviteResult(
                        email="out@example.com", status=ReferralInviteStatus.UNSUBSCRIBED
                    ),
                    ReferralInviteResult(
                        email="me@example.com", status=ReferralInviteStatus.OWN_ADDRESS
                    ),
                ]
            )
        )
        emails = [
            "priya@example.com",
            "bob@example.com",
            "nope",
            "out@example.com",
            "me@example.com",
        ]
        with patch(f"{MODULE}.send_invites", sent):
            result = await send_referral_invite.coroutine(config=_cfg(), emails=emails)

        sent.assert_awaited_once_with(
            USER_ID, ReferralInviteRequest(emails=emails, surface=ReferralInviteSurface.AGENT)
        )
        tool_log.set.assert_called_once_with(
            tool={"name": "send_referral_invite"},
            referral={"operation": "agent_invite", "requested": 5, "forward_only": False},
        )
        assert result == (
            "priya@example.com: sent\n"
            "bob@example.com: already invited by this user, not sent again\n"
            "nope: not a valid email address, not sent\n"
            "out@example.com: opted out of GAIA invites, not sent\n"
            "me@example.com: the user's own address, not sent"
        )

    async def test_a_refused_batch_says_why(self) -> None:
        ceiling = AsyncMock(
            side_effect=AppError(
                message="You've sent a lot of invites today",
                fix="Try again tomorrow",
                status_code=429,
            )
        )
        with patch(f"{MODULE}.send_invites", ceiling):
            result = await send_referral_invite.coroutine(
                config=_cfg(), emails=["priya@example.com"]
            )

        assert result == "Nothing was sent: You've sent a lot of invites today. Try again tomorrow"

    @pytest.mark.parametrize("source", ["whatsapp", "imessage", "telegram"])
    async def test_on_a_chat_platform_it_hands_back_a_message_to_forward(
        self, source: str, tool_log: MagicMock
    ) -> None:
        send = AsyncMock()
        reader = _overview_returning(_overview())
        with (
            patch(f"{MODULE}.send_invites", send),
            patch(f"{MODULE}.get_referral_overview", reader),
        ):
            result = await send_referral_invite.coroutine(
                config=_cfg(source), emails=["priya@example.com"], friend_name="Priya"
            )

        send.assert_not_awaited()
        reader.assert_awaited_once_with(USER_ID)
        tool_log.set.assert_called_once_with(
            tool={"name": "send_referral_invite"},
            referral={"operation": "agent_invite", "requested": 1, "forward_only": True},
        )
        assert result == (
            "Nothing was emailed: on a chat platform the user forwards the invite themselves. "
            "Relay this exactly:\n"
            "Here's a message to forward to Priya. They get GAIA for $15/month for their "
            "first 2 months, and you get a free month when they join:\n\n"
            f"{SHARE_TEXT}"
        )
