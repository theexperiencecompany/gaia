"""The MCP OAuth state token names the user it was minted for, until it is spent."""

import fakeredis.aioredis
import pytest

from app.models.mcp_config import OAuthStateOwner
from app.services.mcp.mcp_token_store import MCPTokenStore, resolve_oauth_state_owner

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"


@pytest.mark.usefixtures("fake_redis")
class TestOAuthStateOwner:
    async def test_create_stores_the_owner_and_resolve_returns_it(self) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        assert await resolve_oauth_state_owner(state) == OAuthStateOwner(
            user_id=USER_ID, integration_id="resend"
        )

    async def test_unknown_state_resolves_to_none(self) -> None:
        assert await resolve_oauth_state_owner("never-minted") is None

    async def test_owner_is_gone_once_the_state_is_verified(self) -> None:
        store = MCPTokenStore(USER_ID)
        state = await store.create_oauth_state("resend", "verifier")

        assert await store.verify_oauth_state("resend", state) == (True, "verifier")

        assert await resolve_oauth_state_owner(state) is None

    async def test_owner_expires_with_the_state(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        state = await MCPTokenStore(USER_ID).create_oauth_state("resend", "verifier")

        ttl = await fake_redis.ttl(f"mcp_oauth_state:owner:{state}")

        assert 0 < ttl <= 600
