"""The /referrals routes: the first-touch cookie, the subscribe-first 403, the opt-out page and the chat-card nudge."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.constants.error_codes import REFERRAL_SUBSCRIPTION_REQUIRED
from app.constants.referrals import REFERRAL_COOKIE_NAME, ReferralNudge
from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.models.referral_models import ReferralNudgeStateDocument
from app.schemas.referrals import ReferralResolveResponse
from app.services.referrals.offer import ProPlans, build_offer

URL = "/api/v1/referrals"
ENDPOINT = "app.api.v1.endpoints.referrals"
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _plan(duration: PlanDuration, amount: int) -> PlanResponse:
    return PlanResponse(
        id=duration.value,
        dodo_product_id=f"pdt_{duration.value}",
        name="Pro",
        plan_type=PlanTier.PRO,
        amount=amount,
        currency="USD",
        duration=duration,
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


OFFER = build_offer(
    ProPlans(monthly=_plan(PlanDuration.MONTHLY, 3000), yearly=_plan(PlanDuration.YEARLY, 27000))
)


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
        self, unauthed_client: AsyncClient
    ) -> None:
        with patch(f"{ENDPOINT}.resolve_referral_code", _resolved(True)):
            response = await unauthed_client.get(
                f"{URL}/resolve/aryan-k7f2", params={"landing_variant": "time_back"}
            )

        assert response.status_code == 200
        assert response.json()["referrer_first_name"] == "Aryan"
        assert response.json()["offer"]["monthly_intro_minor"] == 1500
        (cookie,) = _ref_cookie(response)
        assert cookie.startswith(f"{REFERRAL_COOKIE_NAME}=aryan-k7f2.time_back;")
        assert "Max-Age=2592000" in cookie and "HttpOnly" in cookie

    async def test_a_second_link_never_replaces_the_first(
        self, unauthed_client: AsyncClient
    ) -> None:
        with patch(f"{ENDPOINT}.resolve_referral_code", _resolved(True)):
            response = await unauthed_client.get(
                f"{URL}/resolve/priya-ab23",
                headers={"cookie": f"{REFERRAL_COOKIE_NAME}=aryan-k7f2"},
            )

        assert response.status_code == 200
        assert _ref_cookie(response) == []

    async def test_an_unknown_code_is_invalid_and_sets_nothing(
        self, unauthed_client: AsyncClient
    ) -> None:
        with patch(f"{ENDPOINT}.resolve_referral_code", _resolved(False)):
            response = await unauthed_client.get(f"{URL}/resolve/nobody-zzzz")

        assert response.json()["valid"] is False
        assert _ref_cookie(response) == []


class TestMe:
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
        self, unauthed_client: AsyncClient
    ) -> None:
        with patch(f"{ENDPOINT}.invite_unsubscribe_subject", return_value="friend@example.com"):
            response = await unauthed_client.get(f"{URL}/unsubscribe/tok")

        assert response.status_code == 200
        assert "method='post' action='/api/v1/referrals/unsubscribe/tok'" in response.text

    async def test_a_bad_token_is_refused_on_both_verbs(self, unauthed_client: AsyncClient) -> None:
        with patch(f"{ENDPOINT}.unsubscribe_invite_recipient", AsyncMock(return_value=False)):
            posted = await unauthed_client.post(f"{URL}/unsubscribe/forged")
        page = await unauthed_client.get(f"{URL}/unsubscribe/forged")

        assert (posted.status_code, page.status_code) == (400, 400)


NUDGES = "app.services.referrals.nudges"


class TestChatCardNudge:
    async def test_the_card_shows_when_the_weeks_slot_is_free(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{NUDGES}.subscription_repository.get_active_for_user",
                AsyncMock(return_value=object()),
            ),
            patch(f"{NUDGES}.referral_nudge_repository") as repo,
            patch(f"{NUDGES}.capture"),
        ):
            repo.get = AsyncMock(return_value=None)
            repo.claim = AsyncMock(return_value=ReferralNudgeStateDocument(user_id="u"))
            response = await client.post(f"{URL}/nudges/chat-card")

        assert response.status_code == 200
        assert response.json() == {"show": True}
        assert repo.claim.call_args.args[1] is ReferralNudge.CHAT_CARD

    async def test_the_card_stays_hidden_once_this_weeks_nudge_went_out(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                f"{NUDGES}.subscription_repository.get_active_for_user",
                AsyncMock(return_value=object()),
            ),
            patch(f"{NUDGES}.referral_nudge_repository") as repo,
            patch(f"{NUDGES}.capture") as capture,
        ):
            repo.get = AsyncMock(return_value=None)
            repo.claim = AsyncMock(return_value=None)
            response = await client.post(f"{URL}/nudges/chat-card")

        assert response.json() == {"show": False}
        capture.assert_not_called()

    async def test_dismissing_the_card_reports_whether_it_paused_nudges(
        self, client: AsyncClient
    ) -> None:
        state = ReferralNudgeStateDocument(
            user_id="u", paused_until=datetime.now(UTC) + timedelta(days=30)
        )
        with (
            patch(f"{NUDGES}.referral_nudge_repository") as repo,
            patch(f"{NUDGES}.capture"),
        ):
            repo.record_dismissal = AsyncMock(return_value=state)
            response = await client.post(f"{URL}/nudges/chat-card/dismissal")

        assert response.status_code == 200
        assert response.json() == {"paused": True}
