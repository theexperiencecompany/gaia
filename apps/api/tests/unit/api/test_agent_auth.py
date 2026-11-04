"""Unit tests for app.api.v1.middleware.agent_auth — the agent JWT round trip."""

from datetime import UTC, datetime, timedelta
import time

import pytest

from app.api.v1.middleware import agent_auth
from app.api.v1.middleware.agent_auth import (
    AGENT_SECRET,
    AgentTokenInfo,
    create_agent_token,
    verify_agent_token,
)
from app.constants.auth import JWT_ALGORITHM
from app.constants.device_bridge import DEVICE_TOKEN_AUDIENCE
from tests.helpers import (
    JOSE_AGENT_DEVICE_SECRET,
    JOSE_MINTED_AGENT_TOKEN,
    forge_jwt,
    hostile_jwts,
    read_jwt,
)


def _encode(claims: dict[str, object]) -> str:
    return forge_jwt(claims, AGENT_SECRET, alg=JWT_ALGORITHM)


def _valid_claims() -> dict[str, object]:
    return {"sub": "u-1", "role": "agent", "exp": int(time.time()) + 600}


class TestVerifyAgentToken:
    def test_a_minted_token_verifies_to_its_user(self) -> None:
        assert verify_agent_token(create_agent_token("u-1")) == AgentTokenInfo(
            user_id="u-1", impersonated=True
        )

    def test_a_token_minted_by_python_jose_still_verifies(self, monkeypatch) -> None:
        monkeypatch.setattr(agent_auth, "AGENT_SECRET", JOSE_AGENT_DEVICE_SECRET)
        assert verify_agent_token(JOSE_MINTED_AGENT_TOKEN) == AgentTokenInfo(user_id="u-jose")

    @pytest.mark.parametrize("kind", sorted(hostile_jwts({}, "s")))
    def test_a_hostile_token_is_rejected(self, kind: str) -> None:
        assert verify_agent_token(hostile_jwts(_valid_claims(), AGENT_SECRET)[kind]) is None

    def test_a_token_for_another_role_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"sub": "u-1", "role": "user"})) is None

    def test_a_token_without_a_subject_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"role": "agent"})) is None

    def test_a_token_without_a_role_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"sub": "u-1"})) is None

    def test_a_non_string_subject_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"sub": 7, "role": "agent"})) is None

    def test_a_token_carrying_an_audience_is_rejected(self) -> None:
        """A device token shares AGENT_SECRET; its aud claim keeps it from passing as an agent."""
        device_like = {**_valid_claims(), "aud": DEVICE_TOKEN_AUDIENCE}
        assert verify_agent_token(_encode(device_like)) is None

    def test_a_forged_or_garbage_token_is_rejected(self) -> None:
        forged = forge_jwt({"sub": "u-1", "role": "agent"}, "not-the-secret", alg=JWT_ALGORITHM)
        assert verify_agent_token(forged) is None
        assert verify_agent_token("not-a-jwt") is None

    def test_a_token_signed_with_another_algorithm_is_rejected(self) -> None:
        other_alg = forge_jwt({"sub": "u-1", "role": "agent"}, AGENT_SECRET, alg="HS512")
        assert verify_agent_token(other_alg) is None

    def test_an_expired_token_is_rejected(self) -> None:
        expired = int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())
        assert verify_agent_token(_encode({"sub": "u-1", "role": "agent", "exp": expired})) is None


class TestCreateAgentToken:
    def test_the_token_carries_subject_role_and_an_expiry_window(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        header, claims = read_jwt(create_agent_token("u-9", expires_minutes=7))
        assert header == {"alg": JWT_ALGORITHM, "typ": "JWT"}
        assert claims["sub"] == "u-9"
        assert claims["role"] == "agent"
        assert claims["exp"] - claims["iat"] == 7 * 60
        assert claims["iat"] >= int(before.timestamp())
