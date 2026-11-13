"""POST /api/v1/bot/cards-delivered through the real BotAuthMiddleware, route and recorder.

Faked: the platform-link lookup, the bot-session lookup, the checkpoint write and
analytics capture. Everything between them runs for real, so what a bot reports
is exactly what lands in the conversation the model reads.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api.v1.endpoints import bot_cards
from app.config.settings import settings
from app.core.bot_auth_middleware import BotAuthMiddleware
from app.core.exception_handlers import register_exception_handlers
from app.db.repositories.bot_sessions import bot_session_repository
from app.models.bot_models import BotSessionDocument
from app.services.bot import card_record
from shared.py.analytics import UserId
from shared.py.analytics.catalog.bots import BotCardShown

BOT_KEY = "test-bot-api-key-for-cards-delivered"
URL = "/api/v1/bot/cards-delivered"
TG_USER = "4242"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
CONVERSATION = "conv-tg-1"
CONNECT_TEXT = "**Reconnect PostHog**\n\n[Reconnect](https://app.example.com/connect/abc)"


def _headers(platform_user_id: str = TG_USER) -> dict[str, str]:
    return {
        "X-Bot-API-Key": BOT_KEY,
        "X-Bot-Platform": "telegram",
        "X-Bot-Platform-User-Id": platform_user_id,
    }


def _report(**overrides: object) -> dict[str, object]:
    return {
        "platform": "telegram",
        "platform_user_id": TG_USER,
        "conversation_id": CONVERSATION,
        "cards": [
            {
                "tool_name": "integration_connection_required",
                "text": CONNECT_TEXT,
                "delivered": True,
            }
        ],
        **overrides,
    }


def _session(platform_user_id: str = TG_USER) -> BotSessionDocument:
    return BotSessionDocument(
        session_key=f"telegram:{platform_user_id}:{platform_user_id}",
        conversation_id=CONVERSATION,
        platform="telegram",
        platform_user_id=platform_user_id,
    )


@dataclass
class _Seams:
    session: AsyncMock
    record: AsyncMock
    capture: MagicMock


@pytest.fixture
def seams() -> Iterator[_Seams]:
    linked = MagicMock(user_id=USER_ID)
    fakes = _Seams(
        session=AsyncMock(return_value=_session()),
        record=AsyncMock(),
        capture=MagicMock(),
    )
    with (
        patch.object(settings, "GAIA_BOT_API_KEY", BOT_KEY),
        patch("app.core.bot_auth_middleware.resolve_bot_user", AsyncMock(return_value=linked)),
        patch.object(bot_cards, "resolve_bot_user", AsyncMock(return_value=linked)),
        patch.object(bot_session_repository, "get_by_conversation_id", fakes.session),
        patch.object(card_record, "record_platform_delivery", fakes.record),
        patch.object(card_record, "capture", fakes.capture),
    ):
        yield fakes


@pytest.fixture
async def client(seams: _Seams) -> AsyncGenerator[AsyncClient, None]:
    del seams  # the fixture's patches must be live for every request
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(BotAuthMiddleware)
    app.include_router(bot_cards.router, prefix="/api/v1/bot")
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:  # NOSONAR
        yield ac


class TestCardsAreRecordedForTheModel:
    async def test_a_shown_card_is_written_into_the_conversation_record(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        response = await client.post(URL, json=_report(), headers=_headers())

        assert response.status_code == 200
        assert response.json() == {"recorded": 1}
        seams.record.assert_awaited_once_with(
            CONVERSATION, f"[Shown to the user on Telegram]: {CONNECT_TEXT}"
        )

    async def test_a_card_the_platform_refused_is_recorded_as_not_shown(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        cards = [
            {
                "tool_name": "integration_connection_required",
                "text": CONNECT_TEXT,
                "delivered": True,
            },
            {"tool_name": "rate_limit_data", "text": "Limit reached", "delivered": False},
        ]
        response = await client.post(URL, json=_report(cards=cards), headers=_headers())

        assert response.json() == {"recorded": 2}
        seams.record.assert_awaited_once_with(
            CONVERSATION,
            f"[Shown to the user on Telegram]: {CONNECT_TEXT}\n\n"
            "[FAILED to show the user on Telegram]: Limit reached",
        )

    async def test_each_card_is_captured_on_the_gaia_user(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        await client.post(URL, json=_report(), headers=_headers())

        distinct_id, event = seams.capture.call_args.args
        assert distinct_id == UserId(USER_ID)
        assert event == BotCardShown(
            platform="telegram", tool_name="integration_connection_required", delivered=True
        )


class TestReportsThatAreRefused:
    async def test_another_users_conversation_is_not_found_and_records_nothing(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        seams.session.return_value = _session(platform_user_id="9999")

        response = await client.post(URL, json=_report(), headers=_headers())

        assert response.status_code == 404
        seams.record.assert_not_awaited()

    async def test_a_non_bot_conversation_is_not_found(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        seams.session.return_value = None

        response = await client.post(URL, json=_report(), headers=_headers())

        assert response.status_code == 404
        seams.record.assert_not_awaited()

    async def test_a_body_naming_another_account_than_the_headers_is_forbidden(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        response = await client.post(URL, json=_report(), headers=_headers("1111"))

        assert response.status_code == 403
        seams.record.assert_not_awaited()

    async def test_without_the_bot_key_nothing_is_recorded(
        self, client: AsyncClient, seams: _Seams
    ) -> None:
        response = await client.post(URL, json=_report(), headers={"X-Bot-Platform": "telegram"})

        assert response.status_code == 401
        seams.record.assert_not_awaited()

    async def test_an_empty_report_is_rejected(self, client: AsyncClient, seams: _Seams) -> None:
        response = await client.post(URL, json=_report(cards=[]), headers=_headers())

        assert response.status_code == 422
        seams.record.assert_not_awaited()
