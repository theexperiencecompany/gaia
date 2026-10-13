"""Unit tests for the nurture step context builders (app/services/nurture/context_builders.py).

Each builder adapts a nurture step's copy to what the user has already set
up, merging its keys over the engine's base context. The cta_label overrides
are the critical branches — a step that asks the user to connect an
integration they already have is dead copy.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.models.payment_models import PlanDuration, PlanResponse, PlanTier
from app.models.user_models import UserDocument
from app.services.nurture.context_builders import (
    CONTEXT_BUILDERS,
    google_connection_status,
    referral_gift_prices,
)
from app.services.referrals.offer import ProPlans

NOW = datetime(2026, 10, 14, tzinfo=UTC)


def _user(user_id: str = "u-1", **overrides) -> UserDocument:
    return UserDocument(id=user_id, email="u@example.com", **overrides)


def _statuses(gmail: bool, calendar: bool) -> dict[str, bool]:
    return {GMAIL_INTEGRATION_ID: gmail, GOOGLE_CALENDAR_INTEGRATION_ID: calendar}


class TestGoogleConnectionStatus:
    @patch(
        "app.services.nurture.context_builders.check_multiple_integrations_status",
        new_callable=AsyncMock,
    )
    async def test_both_connected_returns_flags_without_cta_override(self, mock_check) -> None:
        mock_check.return_value = _statuses(gmail=True, calendar=True)
        assert await google_connection_status(_user()) == {
            "gmail_connected": True,
            "calendar_connected": True,
        }

    @patch(
        "app.services.nurture.context_builders.check_multiple_integrations_status",
        new_callable=AsyncMock,
    )
    async def test_neither_connected_returns_flags_without_cta_override(self, mock_check) -> None:
        mock_check.return_value = _statuses(gmail=False, calendar=False)
        assert await google_connection_status(_user()) == {
            "gmail_connected": False,
            "calendar_connected": False,
        }

    @patch(
        "app.services.nurture.context_builders.check_multiple_integrations_status",
        new_callable=AsyncMock,
    )
    async def test_calendar_missing_asks_to_connect_calendar(self, mock_check) -> None:
        mock_check.return_value = _statuses(gmail=True, calendar=False)
        assert await google_connection_status(_user()) == {
            "gmail_connected": True,
            "calendar_connected": False,
            "cta_label": "Connect Google Calendar",
        }

    @patch(
        "app.services.nurture.context_builders.check_multiple_integrations_status",
        new_callable=AsyncMock,
    )
    async def test_gmail_missing_asks_to_connect_gmail(self, mock_check) -> None:
        mock_check.return_value = _statuses(gmail=False, calendar=True)
        assert await google_connection_status(_user()) == {
            "gmail_connected": False,
            "calendar_connected": True,
            "cta_label": "Connect Gmail",
        }

    @patch(
        "app.services.nurture.context_builders.check_multiple_integrations_status",
        new_callable=AsyncMock,
    )
    async def test_checks_both_google_integrations_for_user(self, mock_check) -> None:
        mock_check.return_value = _statuses(gmail=True, calendar=True)
        await google_connection_status(_user("u-9"))
        mock_check.assert_awaited_once_with(
            [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], "u-9"
        )


def test_context_builders_map_exposes_every_builder() -> None:
    assert set(CONTEXT_BUILDERS) == {"google_connection_status", "referral_gift_prices"}
    for builder in CONTEXT_BUILDERS.values():
        assert callable(builder)


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


async def test_the_share_email_quotes_the_live_gift_price() -> None:
    plans = ProPlans(
        monthly=_plan(PlanDuration.MONTHLY, 3000), yearly=_plan(PlanDuration.YEARLY, 27000)
    )
    with patch(
        "app.services.nurture.context_builders.payment_service.get_pro_plans",
        AsyncMock(return_value=plans),
    ):
        assert await referral_gift_prices(_user()) == {
            "price_line": "$15/month for their first 2 months",
            "regular_price_line": "$30/month",
        }
