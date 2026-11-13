"""Security-critical tests for the login-free connect-link code.

The code authenticates a logged-out bot user straight into an OAuth connect, so
resolution is the security boundary. These tests probe minting, atomic
single-use consumption, and rejection of unknown/malformed codes.
"""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, ValidationError
import pytest

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_TTL_MINUTES
import app.services.connect_link_service as svc
from app.services.connect_link_service import (
    ConnectLinkBinding,
    build_connect_link_url,
    resolve_and_consume_connect_code,
)
from tests.helpers import captured_wide_event


@pytest.fixture
def fake_store() -> Generator[dict[str, object], None, None]:
    """In-memory stand-in for the Redis single-use store: set_cache writes, get_and_delete_cache reads-and-deletes."""
    store: dict[str, object] = {}

    async def _set(
        key: str, value: object, ttl: int | None = None, model: object | None = None
    ) -> bool:
        store[key] = value
        return True

    async def _getdel(key: str, model: type[BaseModel] | None = None) -> object | None:
        # Like the real GETDEL: a value that fails its model reads as nothing.
        value = store.pop(key, None)
        if value is None or model is None:
            return value
        try:
            return model.model_validate(value)
        except ValidationError:
            return None

    with (
        patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
        patch.object(svc, "get_and_delete_cache", AsyncMock(side_effect=_getdel)),
    ):
        yield store


def _code_from_url(url: str | None) -> str:
    assert url is not None
    return url.rsplit("/", 1)[1]


class TestConnectLinkCode:
    async def test_mint_then_resolve_returns_user_and_integration(
        self, fake_store: dict[str, object]
    ) -> None:
        url = await build_connect_link_url("user1", "notion")
        assert url is not None
        assert url.startswith(f"{settings.FRONTEND_URL.rstrip('/')}/connect/")
        code = _code_from_url(url)
        assert await resolve_and_consume_connect_code(code) == ConnectLinkBinding(
            user_id="user1", integration_id="notion", account_id=None
        )

    async def test_a_link_lives_for_its_ttl_and_its_redemption_names_who_and_what(self) -> None:
        stored: dict[str, object] = {}

        async def _set(key: str, value: object, ttl: int, model: object) -> bool:
            stored.update(value=value, ttl=ttl)
            return True

        with (
            patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
            patch.object(
                svc, "get_and_delete_cache", AsyncMock(side_effect=lambda *_: stored["value"])
            ),
        ):
            code = _code_from_url(await build_connect_link_url("user1", "gmail"))
            async with captured_wide_event() as event:
                await resolve_and_consume_connect_code(code)

        assert stored["ttl"] == CONNECT_LINK_TTL_MINUTES * 60 == 3600
        assert event["auth"] == {"user_id": "user1", "provider": "gmail"}

    async def test_a_reconnect_link_carries_the_account_to_sign_back_in(
        self, fake_store: dict[str, object]
    ) -> None:
        code = _code_from_url(await build_connect_link_url("user1", "gmail", "ca_work"))
        assert await resolve_and_consume_connect_code(code) == ConnectLinkBinding(
            user_id="user1", integration_id="gmail", account_id="ca_work"
        )

    async def test_single_use_second_resolve_is_none(self, fake_store: dict[str, object]) -> None:
        """Second open of the same link must fail — the heart of single-use."""
        code = _code_from_url(await build_connect_link_url("user1", "notion"))
        first = await resolve_and_consume_connect_code(code)
        second = await resolve_and_consume_connect_code(code)
        assert first == ConnectLinkBinding(
            user_id="user1", integration_id="notion", account_id=None
        )
        assert second is None

    async def test_unknown_code_rejected(self, fake_store: dict[str, object]) -> None:
        assert await resolve_and_consume_connect_code("does-not-exist") is None

    async def test_malformed_binding_rejected(self, fake_store: dict[str, object]) -> None:
        """A stored value missing integration_id must not resolve to a partial."""
        await svc.set_cache(svc._code_key("partial"), {"user_id": "u"})
        assert await resolve_and_consume_connect_code("partial") is None

    async def test_two_mints_have_distinct_codes(self, fake_store: dict[str, object]) -> None:
        a = _code_from_url(await build_connect_link_url("u", "notion"))
        b = _code_from_url(await build_connect_link_url("u", "notion"))
        assert a != b

    async def test_code_has_high_entropy_length(self, fake_store: dict[str, object]) -> None:
        # token_urlsafe(12) → 16 url-safe chars / 96 bits of entropy.
        code = _code_from_url(await build_connect_link_url("u", "notion"))
        assert len(code) >= 16

    async def test_failed_store_returns_none(self) -> None:
        """A failed write (Redis unavailable) means no link minted; callers degrade to a generic connect prompt."""
        with patch.object(svc, "set_cache", AsyncMock(return_value=False)):
            assert await build_connect_link_url("user1", "notion") is None
