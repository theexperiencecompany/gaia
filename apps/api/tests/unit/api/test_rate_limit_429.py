"""Endpoint-level 429 wiring for the tiered rate limiter.

The root conftest mocks ``check_and_increment`` to always succeed, so no test
proves an exceeded limit surfaces as an HTTP 429. Here the REAL limiter runs
against a fake Redis seam (``tiered_limiter.redis``) pre-seeded past the FREE
notes daily limit (30, see app/config/rate_limits.py) — the decision logic
raises its real 429 signal and the real ``POST /api/v1/notes`` route (a write
endpoint behind ``@tiered_rate_limit``) must translate it into a 429 with the
real detail shape.
"""

from datetime import UTC, datetime, timedelta
from types import MethodType
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.api.v1.middleware.tiered_rate_limiter import (
    TieredRateLimiter,
    tiered_limiter,
)
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


async def test_rate_limit_exceeded_returns_429(
    client: AsyncClient,
) -> None:
    """An exhausted FREE window through the real limiter becomes an HTTP 429."""
    reset_time = datetime.now(UTC) + timedelta(hours=2)
    with (
        # The test app's conftest replaces check_and_increment with a
        # succeed-mock; restore the real bound method so the decision logic
        # actually runs, then fake its Redis storage seam.
        patch.object(
            tiered_limiter,
            "check_and_increment",
            MethodType(TieredRateLimiter.check_and_increment, tiered_limiter),
        ),
        patch.object(tiered_limiter, "redis", AsyncMock()) as fake_redis,
        patch(
            "app.api.v1.middleware.tiered_rate_limiter.get_reset_time",
            return_value=reset_time,
        ),
        patch(
            "app.api.v1.endpoints.notes.create_note_service",
            new_callable=AsyncMock,
        ) as create,
    ):
        # notes FREE = 30/day: usage 30 exhausts the window, so the real
        # decision loop raises RateLimitExceededException.
        fake_redis.get = AsyncMock(return_value="30")
        response = await client.post(NOTES_BASE, json=_NOTE_BODY)

    assert response.status_code == 429
    detail = response.json()["detail"]
    assert detail["error"] == "rate_limit_exceeded"
    assert detail["feature"] == "notes"
    assert detail["message"] == "Rate limit exceeded for notes"
    assert detail["reset_time"] == reset_time.isoformat()

    # The limiter read the pre-seeded usage for the authenticated FREE user
    # (the root conftest's subscription patch), and the handler never ran —
    # the 429 comes from the real decision logic, not from a raised mock.
    assert fake_redis.get.await_count >= 1
    create.assert_not_awaited()


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
