"""Endpoint-level 429 wiring for the tiered rate limiter.

The root conftest mocks ``check_and_increment`` to always succeed, so no test
proves an exceeded limit surfaces as an HTTP 429. The decision logic itself is
unit-tested with the real limiter in
tests/unit/decorators/test_rate_limiter_tiers.py; here the storage seam is
mocked to raise the limiter's real 429 signal and the real ``POST
/api/v1/notes`` route (a write endpoint behind ``@tiered_rate_limit``) must
translate it into a 429 with the real detail shape.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.models.payment_models import PlanType

NOTES_BASE = "/api/v1/notes"

_NOTE_BODY = {"content": "<p>Test note</p>", "plaintext": "Test note"}

_NOTE_RESPONSE = {
    "id": "note-001",
    "content": "<p>Test note</p>",
    "plaintext": "Test note",
    "auto_created": False,
    "user_id": "507f1f77bcf86cd799439033",
    "title": None,
    "description": None,
}


@pytest.mark.unit
async def test_rate_limit_exceeded_returns_429(
    client: AsyncClient,
    fake_user: dict,
) -> None:
    """A limit-exceeded signal from the limiter becomes an HTTP 429."""
    reset_time = datetime.now(UTC) + timedelta(hours=2)
    with (
        patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
            side_effect=RateLimitExceededException("notes", reset_time=reset_time),
        ) as check,
        patch(
            "app.api.v1.endpoints.notes.create_note_service",
            new_callable=AsyncMock,
        ) as create,
    ):
        response = await client.post(NOTES_BASE, json=_NOTE_BODY)

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error"] == "rate_limit_exceeded"
    assert detail["feature"] == "notes"
    assert detail["message"] == "Rate limit exceeded for notes"
    assert detail["reset_time"] == reset_time.isoformat()

    # The limiter was billed for the authenticated user on the FREE tier (the
    # root conftest's subscription patch), and the handler never ran — the 429
    # comes from the limiter, not from the endpoint.
    check.assert_awaited_once()
    assert check.call_args.kwargs["user_id"] == fake_user["user_id"]
    assert check.call_args.kwargs["user_plan"] == PlanType.FREE
    create.assert_not_awaited()


@pytest.mark.unit
async def test_pro_user_reaches_limiter_on_pro_plan(
    client: AsyncClient,
    pro_user: dict,
) -> None:
    """Opting into a paying context routes the PRO tier into the limiter."""
    with (
        patch(
            "app.decorators.rate_limiting.payment_service.get_user_subscription_status",
            new_callable=AsyncMock,
            return_value=pro_user["subscription"],
        ),
        patch(
            "app.decorators.rate_limiting.tiered_limiter.check_and_increment",
            new_callable=AsyncMock,
        ) as check,
        patch(
            "app.api.v1.endpoints.notes.create_note_service",
            new_callable=AsyncMock,
            return_value=_NOTE_RESPONSE,
        ) as create,
    ):
        response = await client.post(NOTES_BASE, json=_NOTE_BODY)

    assert response.status_code == 201
    check.assert_awaited_once()
    assert check.call_args.kwargs["user_plan"] == PlanType.PRO
    create.assert_awaited_once()
