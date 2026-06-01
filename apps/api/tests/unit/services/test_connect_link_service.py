"""Security-critical tests for the login-free connect-link token.

This token authenticates a logged-out bot user straight into an OAuth connect,
so the verifier is the security boundary. These tests adversarially probe it:
forgery, wrong-role reuse, expiry, tampering, and replay.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from jose import jwt
import pytest

from app.config.settings import settings
from app.constants.auth import CONNECT_LINK_ROLE, JWT_ALGORITHM
import app.services.connect_link_service as svc
from app.services.connect_link_service import (
    build_connect_link_url,
    create_connect_link_token,
    verify_and_consume_connect_link_token,
)


@pytest.fixture(autouse=True)
def _patch_signing_secret():
    """AGENT_SECRET is optional (None) in the dev/test settings; pin a stable
    test secret so sign+verify round-trip deterministically."""
    with patch.object(settings, "AGENT_SECRET", "unit-test-secret-0123456789-abcdefghij"):
        yield


def _make_redis(set_returns: list) -> MagicMock:
    """Redis stand-in whose `client.set(... nx=True)` yields the given results
    in order — True = first use (key claimed), None = already used (NX failed)."""
    client = MagicMock()
    client.set = AsyncMock(side_effect=set_returns)
    redis = MagicMock()
    redis.client = client
    return redis


def _signed(payload: dict, secret: str | None = None) -> str:
    return jwt.encode(payload, secret or settings.AGENT_SECRET, algorithm=JWT_ALGORITHM)


@pytest.mark.unit
class TestConnectLinkToken:
    async def test_round_trip_returns_user_and_integration(self) -> None:
        token = create_connect_link_token("user1", "notion")
        with patch.object(svc, "redis_cache", _make_redis([True])):
            assert await verify_and_consume_connect_link_token(token) == ("user1", "notion")

    async def test_single_use_replay_is_rejected(self) -> None:
        """Second open of the same link must fail — the heart of single-use."""
        token = create_connect_link_token("user1", "notion")
        redis = _make_redis([True, None])  # first claims the jti; replay loses NX
        with patch.object(svc, "redis_cache", redis):
            first = await verify_and_consume_connect_link_token(token)
            second = await verify_and_consume_connect_link_token(token)
        assert first == ("user1", "notion")
        assert second is None

    async def test_wrong_role_rejected_even_with_valid_signature(self) -> None:
        """A token signed with OUR secret but a different role (e.g. an agent
        token) must NOT be accepted as a connect link — role is the boundary."""
        token = _signed(
            {
                "sub": "user1",
                "integration_id": "notion",
                "role": "agent",
                "jti": "x",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            }
        )
        # No redis patch: must be rejected before the single-use SET.
        assert await verify_and_consume_connect_link_token(token) is None

    async def test_expired_token_rejected(self) -> None:
        token = _signed(
            {
                "sub": "user1",
                "integration_id": "notion",
                "role": CONNECT_LINK_ROLE,
                "jti": "x",
                "exp": datetime.now(UTC) - timedelta(seconds=5),
            }
        )
        assert await verify_and_consume_connect_link_token(token) is None

    async def test_tampered_token_rejected(self) -> None:
        token = create_connect_link_token("user1", "notion")
        tampered = token[:-2] + ("zz" if not token.endswith("zz") else "yy")
        assert await verify_and_consume_connect_link_token(tampered) is None

    async def test_foreign_secret_rejected(self) -> None:
        """Forged with a different signing key → invalid signature → rejected."""
        token = _signed(
            {
                "sub": "attacker",
                "integration_id": "notion",
                "role": CONNECT_LINK_ROLE,
                "jti": "x",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            secret="not-our-secret-key-at-all-0123456789abcdef",
        )
        assert await verify_and_consume_connect_link_token(token) is None

    async def test_missing_claims_rejected(self) -> None:
        token = _signed({"role": CONNECT_LINK_ROLE, "exp": datetime.now(UTC) + timedelta(hours=1)})
        assert await verify_and_consume_connect_link_token(token) is None

    def test_build_url_embeds_verifiable_token(self) -> None:
        url = build_connect_link_url("user1", "notion")
        assert "/api/v1/integrations/connect-link?t=" in url
        token = url.split("t=", 1)[1]
        payload = jwt.decode(token, settings.AGENT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "user1"
        assert payload["integration_id"] == "notion"
        assert payload["role"] == CONNECT_LINK_ROLE

    def test_two_links_have_distinct_jti(self) -> None:
        """Distinct jti per mint so single-use is per-link, not per-(user,integration)."""
        a = jwt.decode(
            create_connect_link_token("u", "notion"),
            settings.AGENT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        b = jwt.decode(
            create_connect_link_token("u", "notion"),
            settings.AGENT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        assert a["jti"] != b["jti"]
