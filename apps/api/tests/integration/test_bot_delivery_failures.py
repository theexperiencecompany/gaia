"""POST /api/v1/bot/delivery-failures through the real BotAuthMiddleware and route.

Only the ARQ enqueue is faked: a request is authorised by the bot key alone,
validated against the report schema, and queued with its reporter stamped.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.endpoints import bot_delivery_failures
from app.config.settings import settings
from app.core.bot_auth_middleware import BotAuthMiddleware
from app.core.exception_handlers import register_exception_handlers
from app.schemas.delivery_failures import DeliveryFailure

BOT_KEY = "test-bot-api-key-for-delivery-failures"
URL = "/api/v1/bot/delivery-failures"
REPORT = {
    "platform": "whatsapp",
    "kind": "platform_rejected",
    "reason": "platform_error",
    "error_code": "130497",
    "error_message": "Business account is restricted from messaging users in this country.",
    "destination_id": "5511900000001",
    "country": "BR",
    "platform_message_id": "wamid.X",
    "occurred_at": "2026-10-22T15:53:37Z",
}


def _bot_headers(platform: str = "whatsapp", key: str = BOT_KEY) -> dict[str, str]:
    return {"X-Bot-API-Key": key, "X-Bot-Platform": platform}


@pytest.fixture
def queued() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
async def client(queued: AsyncMock) -> AsyncGenerator[AsyncClient, None]:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(BotAuthMiddleware)
    app.include_router(bot_delivery_failures.router, prefix="/api/v1/bot")
    with (
        patch.object(settings, "GAIA_BOT_API_KEY", BOT_KEY),
        patch.object(bot_delivery_failures, "queue_delivery_failure", queued),
    ):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
            yield ac


class TestReportDeliveryFailure:
    async def test_a_bot_report_is_queued_with_its_reporter(
        self, client: AsyncClient, queued: AsyncMock
    ) -> None:
        response = await client.post(URL, json=REPORT, headers=_bot_headers())

        assert response.status_code == 202
        assert response.json() == {"status": "queued"}
        (failure,) = queued.await_args.args
        assert isinstance(failure, DeliveryFailure)
        assert failure.reporter == "whatsapp-bot"
        assert failure.error_code == "130497"
        assert failure.country == "BR"
        assert failure.user_id is None

    async def test_a_wrong_bot_key_is_refused_and_nothing_queued(
        self, client: AsyncClient, queued: AsyncMock
    ) -> None:
        response = await client.post(URL, json=REPORT, headers=_bot_headers(key="nope"))

        assert response.status_code == 401
        queued.assert_not_awaited()

    async def test_a_bot_cannot_report_for_another_platform(
        self, client: AsyncClient, queued: AsyncMock
    ) -> None:
        response = await client.post(URL, json=REPORT, headers=_bot_headers(platform="telegram"))

        assert response.status_code == 403
        queued.assert_not_awaited()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("platform", "web"),
            ("kind", "lost_in_space"),
            ("reason", "Not A Code"),
            ("country", "Brazil"),
            ("error_message", "x" * 501),
        ],
    )
    async def test_a_malformed_report_is_rejected(
        self, client: AsyncClient, queued: AsyncMock, field: str, value: str
    ) -> None:
        response = await client.post(URL, json=REPORT | {field: value}, headers=_bot_headers())

        assert response.status_code == 422
        queued.assert_not_awaited()

    async def test_a_report_that_cannot_be_queued_is_an_error_not_a_lie(
        self, client: AsyncClient, queued: AsyncMock
    ) -> None:
        queued.side_effect = ConnectionError("redis down")

        response = await client.post(URL, json=REPORT, headers=_bot_headers())

        assert response.status_code == 500
