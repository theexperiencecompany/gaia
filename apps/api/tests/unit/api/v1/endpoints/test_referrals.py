"""The /referrals routes: the first-touch cookie, the subscribe-first 403 and the public opt-out page."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER
from tests.factories import make_pro_plans

from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import (
    REFERRAL_COOKIE_NAME,
    ReferralCopyVariant,
    ReferralLayoutVariant,
)
from app.models.referral_models import ReferredFriendStatus
from app.schemas.referrals import ReferralMeResponse, ReferralResolveResponse, ReferredFriend
from app.services.referrals.offer import build_offer
from app.utils.notification.unsubscribe import UNSUBSCRIBE_INVALID_HTML

URL = "/api/v1/referrals"
ENDPOINT = "app.api.v1.endpoints.referrals"
NOW = datetime(2026, 10, 14, tzinfo=UTC)
OFFER = build_offer(make_pro_plans())


@pytest.fixture
def route_log() -> Iterator[MagicMock]:
    with patch(f"{ENDPOINT}.log") as mock_log:
        yield mock_log


def _resolved(valid: bool) -> AsyncMock:
    return AsyncMock(
        return_value=ReferralResolveResponse(
            valid=valid, referrer_first_name="Aryan" if valid else None, offer=OFFER
        )
    )


def _ref_cookie(response) -> list[str]:
    return [
        c for c in response.headers.get_list("set-cookie") if c.startswith(REFERRAL_COOKIE_NAME)
    ]


class TestResolve:
    async def test_a_valid_link_sets_the_30_day_first_touch_cookie(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        resolve = _resolved(True)
        with patch(f"{ENDPOINT}.resolve_referral_code", resolve):
            response = await unauthed_client.get(
                f"{URL}/resolve/aryan-k7f2", params={"landing_variant": "time_back"}
            )

        assert response.status_code == 200
        assert response.json()["referrer_first_name"] == "Aryan"
        assert response.json()["offer"]["monthly_intro_minor"] == 1500
        resolve.assert_awaited_once_with("aryan-k7f2")
        (cookie,) = _ref_cookie(response)
        assert cookie.startswith(f"{REFERRAL_COOKIE_NAME}=aryan-k7f2.time_back;")
        assert "Max-Age=2592000" in cookie and "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" not in cookie
        route_log.set.assert_called_once_with(
            referral={"operation": "resolve", "landing_variant": ReferralCopyVariant.TIME_BACK}
        )
        route_log.set_ns.assert_called_once_with("referral", valid=True, cookie_set=True)

    async def test_in_production_the_cookie_is_https_only(
        self, unauthed_client: AsyncClient
    ) -> None:
        with (
            patch(f"{ENDPOINT}.resolve_referral_code", _resolved(True)),
            patch(f"{ENDPOINT}.settings.ENV", "production"),
        ):
            response = await unauthed_client.get(f"{URL}/resolve/aryan-k7f2")

        (cookie,) = _ref_cookie(response)
        assert "Secure" in cookie

    async def test_a_second_link_never_replaces_the_first(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        with patch(f"{ENDPOINT}.resolve_referral_code", _resolved(True)):
            response = await unauthed_client.get(
                f"{URL}/resolve/priya-ab23",
                headers={"cookie": f"{REFERRAL_COOKIE_NAME}=aryan-k7f2"},
            )

        assert response.status_code == 200
        assert _ref_cookie(response) == []
        route_log.set_ns.assert_called_once_with("referral", valid=True, cookie_set=False)

    async def test_an_unknown_code_is_invalid_and_sets_nothing(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        with patch(f"{ENDPOINT}.resolve_referral_code", _resolved(False)):
            response = await unauthed_client.get(f"{URL}/resolve/nobody-zzzz")

        assert response.json()["valid"] is False
        assert _ref_cookie(response) == []
        route_log.set_ns.assert_called_once_with("referral", valid=False, cookie_set=False)


class TestMe:
    async def test_the_page_gets_the_callers_overview_and_records_its_size(
        self, client: AsyncClient, route_log: MagicMock
    ) -> None:
        friend = ReferredFriend(
            first_name="Priya", status=ReferredFriendStatus.PAID, joined_at=NOW, paid_at=NOW
        )
        overview = ReferralMeResponse(
            code="aryan-k7f2",
            share_link="http://localhost:3000/invite/aryan-k7f2",
            offer=OFFER,
            months_earned=3,
            months_applied=2,
            months_banked=1,
            friends=[friend, friend],
            copy_variant=ReferralCopyVariant.GIFT,
            layout_variant=ReferralLayoutVariant.TICKET,
        )
        with patch(
            f"{ENDPOINT}.get_referral_overview", AsyncMock(return_value=overview)
        ) as get_overview:
            response = await client.get(f"{URL}/me")

        assert response.status_code == 200
        assert response.json()["code"] == "aryan-k7f2"
        get_overview.assert_awaited_once_with(FAKE_USER.user_id)
        route_log.set.assert_called_once_with(
            user={"id": FAKE_USER.user_id}, referral={"operation": "me"}
        )
        route_log.set_ns.assert_called_once_with("referral", friends=2, months_earned=3)

    async def test_without_a_subscription_the_page_gets_a_coded_403(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                "app.services.referrals.overview.subscription_repository.get_active_for_user",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.services.referrals.overview.load_user",
                AsyncMock(return_value=AsyncMock(id="u")),
            ),
        ):
            response = await client.get(f"{URL}/me")

        assert response.status_code == 403
        assert response.json()["code"] == REFERRAL_SUBSCRIPTION_REQUIRED


class TestUnsubscribe:
    async def test_the_link_opens_a_confirm_page_that_posts(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        with patch(f"{ENDPOINT}.invite_unsubscribe_subject", return_value="friend@example.com"):
            response = await unauthed_client.get(f"{URL}/unsubscribe/tok")

        assert response.status_code == 200
        assert "method='post' action='/api/v1/referrals/unsubscribe/tok'" in response.text
        route_log.set.assert_called_once_with(referral={"operation": "unsubscribe_confirmation"})

    async def test_confirming_opts_the_address_out(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        with patch(
            f"{ENDPOINT}.unsubscribe_invite_recipient", AsyncMock(return_value=True)
        ) as unsubscribe:
            response = await unauthed_client.post(f"{URL}/unsubscribe/tok")

        assert response.status_code == 200
        unsubscribe.assert_awaited_once_with("tok")
        route_log.set.assert_called_once_with(referral={"operation": "unsubscribe"})
        route_log.set_ns.assert_called_once_with("referral", unsubscribed=True)

    async def test_a_bad_token_is_refused_on_both_verbs(
        self, unauthed_client: AsyncClient, route_log: MagicMock
    ) -> None:
        with patch(f"{ENDPOINT}.unsubscribe_invite_recipient", AsyncMock(return_value=False)):
            posted = await unauthed_client.post(f"{URL}/unsubscribe/forged")
        page = await unauthed_client.get(f"{URL}/unsubscribe/forged")

        assert (posted.status_code, page.status_code) == (400, 400)
        assert page.text == UNSUBSCRIBE_INVALID_HTML
        route_log.set_ns.assert_not_called()
