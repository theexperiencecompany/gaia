"""The MCP OAuth state token names the user it was minted for, until it is spent."""

import fakeredis.aioredis
import pytest

from app.services.mcp.mcp_token_store import (
    MCPTokenStore,
    OAuthStateStoreError,
    resolve_oauth_state_owner,
)

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.usefixtures("fake_redis")
class TestOAuthStateOwner:
    async def test_create_stores_the_owner_and_resolve_returns_it(self) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        assert await resolve_oauth_state_owner(state, "resend") == USER_ID

    async def test_a_state_minted_for_another_integration_resolves_to_none(self) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        assert await resolve_oauth_state_owner(state, "dodo") is None

    async def test_unknown_state_resolves_to_none(self) -> None:
        assert await resolve_oauth_state_owner("never-minted", "resend") is None

    async def test_owner_is_gone_once_the_state_is_verified(self) -> None:
        store = MCPTokenStore(USER_ID)
        state = await store.create_oauth_state("resend", "verifier")

        assert await store.verify_oauth_state("resend", state) == (True, "verifier")

        assert await resolve_oauth_state_owner(state, "resend") is None

    async def test_the_state_and_its_owner_expire_together(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        owner_ttl = await fake_redis.ttl(f"mcp_oauth_state:owner:{state}")
        pending_ttl = await fake_redis.ttl(f"mcp_oauth_state:{USER_ID}:resend")

        assert 0 < owner_ttl <= 600
        assert 0 < pending_ttl <= 600


async def test_a_state_whose_owner_cannot_be_stored_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state handed out without its owner record would only ever fail at the callback."""
    writes = iter([True, False])

    async def set_cache(*_args: object, **_kwargs: object) -> bool:
        return next(writes)

    monkeypatch.setattr("app.services.mcp.mcp_token_store.set_cache", set_cache)

    with pytest.raises(OAuthStateStoreError, match="github"):
        await MCPTokenStore("user-1").create_oauth_state("github", "verifier")
