"""Single-use codes for the local session-import CLI."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.constants.browser import BROWSER_IMPORT_TOKEN_KEY_PREFIX, BROWSER_IMPORT_TOKEN_TTL_SECONDS
from app.services.browser import import_token as mod

pytestmark = pytest.mark.unit


async def test_a_code_authorises_its_user_once_within_the_import_window(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    token = await mod.mint_import_token("user-1")

    ttl = await fake_redis.ttl(f"{BROWSER_IMPORT_TOKEN_KEY_PREFIX}{token}")
    assert BROWSER_IMPORT_TOKEN_TTL_SECONDS - 10 < ttl <= BROWSER_IMPORT_TOKEN_TTL_SECONDS
    assert await mod.consume_import_token(token) == "user-1"
    # A leaked code cannot overwrite the user's logins a second time.
    assert await mod.consume_import_token(token) is None
    assert await mod.consume_import_token("never-minted") is None
