"""Tests for the one-tap platform-linking code.

The code links a bot account to a GAIA user with no login, so minting, the
single-use guarantee, and the exact shape of the deep links (which the adapters
parse back) are the boundaries worth probing.
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.auth import PLATFORM_LINK_CODE_BYTES
from app.constants.cache import PLATFORM_LINK_CODE_TTL
import app.services.platform_link_code_service as svc
from app.services.platform_link_code_service import (
    build_handoff_links,
    build_handoff_text,
    consume_platform_link_code,
    mint_platform_link_code,
)
from app.utils.errors import AppError

FIRST_MESSAGE = "Hi! I'm a founder. I could use help with my inbox and my todos. Who are you?"


@pytest.fixture
def fake_store() -> Generator[dict[str, object], None, None]:
    """In-memory stand-in for the Redis single-use store."""
    store: dict[str, object] = {}

    async def _set(key: str, value: object, ttl: int | None = None) -> bool:
        store[key] = (value, ttl)
        return True

    async def _getdel(key: str, model: type | None = None) -> object | None:
        entry = store.pop(key, None)
        if entry is None:
            return None
        value, _ttl = entry
        return model.model_validate(value) if model else value

    with (
        patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
        patch.object(svc, "get_and_delete_cache", AsyncMock(side_effect=_getdel)),
    ):
        yield store


class TestMintAndConsume:
    async def test_mint_then_consume_returns_the_binding(
        self, fake_store: dict[str, object]
    ) -> None:
        code = await mint_platform_link_code("user1", FIRST_MESSAGE)
        payload = await consume_platform_link_code(code)
        assert payload is not None
        assert payload.user_id == "user1"
        assert payload.first_message == FIRST_MESSAGE

    async def test_single_use_second_consume_is_none(self, fake_store: dict[str, object]) -> None:
        code = await mint_platform_link_code("user1", FIRST_MESSAGE)
        assert await consume_platform_link_code(code) is not None
        assert await consume_platform_link_code(code) is None

    async def test_unknown_code_is_none(self, fake_store: dict[str, object]) -> None:
        assert await consume_platform_link_code("not-a-real-code") is None

    async def test_two_mints_have_distinct_codes(self, fake_store: dict[str, object]) -> None:
        assert await mint_platform_link_code("u", FIRST_MESSAGE) != await mint_platform_link_code(
            "u", FIRST_MESSAGE
        )

    async def test_code_is_stored_with_the_thirty_minute_ttl(
        self, fake_store: dict[str, object]
    ) -> None:
        code = await mint_platform_link_code("user1", FIRST_MESSAGE)
        _value, ttl = fake_store[f"platform_link_code:{code}"]  # type: ignore[misc]
        assert ttl == PLATFORM_LINK_CODE_TTL == 1_800

    async def test_code_length_matches_the_adapters_regex(
        self, fake_store: dict[str, object]
    ) -> None:
        """22 urlsafe chars — the exact width the bots' #code pattern accepts."""
        code = await mint_platform_link_code("user1", FIRST_MESSAGE)
        assert PLATFORM_LINK_CODE_BYTES == 16
        assert len(code) == 22

    async def test_unstorable_code_fails_loud(self) -> None:
        """A code Redis never accepted would 'expire' the instant the user arrives."""
        with patch.object(svc, "set_cache", AsyncMock(return_value=False)):
            with pytest.raises(AppError) as excinfo:
                await mint_platform_link_code("user1", FIRST_MESSAGE)
        assert excinfo.value.status_code == 503


class TestHandoffLinks:
    def test_handoff_text_appends_the_code(self) -> None:
        assert build_handoff_text("Hi there!", "abc123") == "Hi there! #abc123"

    def test_telegram_link_carries_the_code_as_a_start_payload(self) -> None:
        with patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", "heygaia_bot"):
            links = build_handoff_links("CODE123", FIRST_MESSAGE)
        assert links["telegram"] == "https://t.me/heygaia_bot?start=CODE123"

    def test_whatsapp_link_urlencodes_the_handoff_text(self) -> None:
        with patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", "15551234567"):
            links = build_handoff_links("CODE123", "Hi! I'm a founder. Who are you?")
        assert links["whatsapp"] == (
            "https://wa.me/15551234567?text="
            "Hi%21%20I%27m%20a%20founder.%20Who%20are%20you%3F%20%23CODE123"
        )

    def test_imessage_has_no_link_its_number_is_per_user(self) -> None:
        with (
            patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", "heygaia_bot"),
            patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", "15551234567"),
        ):
            links = build_handoff_links("CODE123", FIRST_MESSAGE)
        assert set(links) == {"telegram", "whatsapp"}

    def test_unconfigured_platform_is_omitted_not_broken(self) -> None:
        with (
            patch.object(svc.settings, "TELEGRAM_BOT_USERNAME", None),
            patch.object(svc.settings, "WHATSAPP_PHONE_NUMBER", None),
        ):
            assert build_handoff_links("CODE123", FIRST_MESSAGE) == {}
