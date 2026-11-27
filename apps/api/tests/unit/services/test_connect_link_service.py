"""Security-critical tests for the login-free connect-link code.

The code authenticates a logged-out bot user straight into an OAuth connect, so
resolution is the security boundary. These tests probe minting, atomic
single-use consumption, and rejection of unknown/malformed codes.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel, ValidationError
import pytest

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_TTL_MINUTES
from app.db.repositories.users import user_repository
from app.models.user_models import UserDocument
from app.schemas.integrations.responses import ConnectLinkPreviewResponse
import app.services.connect_link_service as svc
from app.services.connect_link_service import (
    ConnectLinkBinding,
    build_connect_link_url,
    preview_connect_code,
    resolve_and_consume_connect_code,
)
from app.services.integrations.integration_resolver import (
    IntegrationResolver,
    ResolvedIntegration,
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

    async def _get(key: str, model: type[BaseModel] | None = None) -> object | None:
        value = store.get(key)
        if value is None or model is None:
            return value
        return model.model_validate(value)

    with (
        patch.object(svc, "set_cache", AsyncMock(side_effect=_set)),
        patch.object(svc, "get_cache", AsyncMock(side_effect=_get)),
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
        fake_store[svc._code_key("partial")] = {"user_id": "u"}
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


_OWNER = "owner-id"


def _resolved(icon_url: str | None) -> ResolvedIntegration:
    return ResolvedIntegration(
        integration_id="dodo",
        name="Dodo Payments",
        description="",
        category="finance",
        managed_by="mcp",
        source="custom",
        requires_auth=True,
        auth_type="oauth",
        mcp_config=None,
        platform_integration=None,
        custom_doc=None,
        icon_url=icon_url,
    )


@contextmanager
def _lookups(resolved: ResolvedIntegration | None, owner: UserDocument | None) -> Iterator[None]:
    """Resolve the integration, and find a user only under the link owner's id."""

    async def _user(user_id: str) -> UserDocument | None:
        return owner if user_id == _OWNER else None

    with (
        patch.object(IntegrationResolver, "resolve", AsyncMock(return_value=resolved)),
        patch.object(user_repository, "get", AsyncMock(side_effect=_user)),
    ):
        yield


class TestConnectLinkPreview:
    async def test_names_the_integration_and_masks_the_owners_email_without_spending(
        self, fake_store: dict[str, object]
    ) -> None:
        code = _code_from_url(await build_connect_link_url(_OWNER, "dodo"))
        owner = UserDocument(email="aryan@heygaia.io", name="Aryan")
        with _lookups(_resolved("https://dodo.example/icon.png"), owner):
            preview = await preview_connect_code(code)

        assert preview == ConnectLinkPreviewResponse(
            integration_id="dodo",
            name="Dodo Payments",
            icon_url="https://dodo.example/icon.png",
            account_email="ar***@heygaia.io",
        )
        assert await resolve_and_consume_connect_code(code) is not None

    async def test_an_owner_with_no_email_previews_without_one(
        self, fake_store: dict[str, object]
    ) -> None:
        code = _code_from_url(await build_connect_link_url(_OWNER, "dodo"))
        with _lookups(_resolved(None), UserDocument(name="Bot user")):
            preview = await preview_connect_code(code)

        assert preview is not None
        assert preview.account_email is None

    async def test_an_integration_that_no_longer_resolves_has_no_preview(
        self, fake_store: dict[str, object]
    ) -> None:
        code = _code_from_url(await build_connect_link_url(_OWNER, "dodo"))
        with _lookups(None, UserDocument(email="a@b.co")):
            assert await preview_connect_code(code) is None

    async def test_a_deleted_owner_has_no_preview(self, fake_store: dict[str, object]) -> None:
        code = _code_from_url(await build_connect_link_url(_OWNER, "dodo"))
        with _lookups(_resolved(None), None):
            assert await preview_connect_code(code) is None

    async def test_an_unknown_code_has_no_preview(self, fake_store: dict[str, object]) -> None:
        assert await preview_connect_code("nope") is None
