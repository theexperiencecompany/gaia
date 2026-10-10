"""Unit tests for app.api.v1.middleware.agent_auth — the agent JWT round trip."""

from datetime import UTC, datetime, timedelta

from jose import jwt

from app.api.v1.middleware.agent_auth import (
    AGENT_SECRET,
    AgentTokenInfo,
    create_agent_token,
    verify_agent_token,
)
from app.constants.auth import JWT_ALGORITHM


def _encode(claims: dict[str, object]) -> str:
    return jwt.encode(claims, AGENT_SECRET, algorithm=JWT_ALGORITHM)


class TestVerifyAgentToken:
    def test_a_minted_token_verifies_to_its_user(self) -> None:
        assert verify_agent_token(create_agent_token("u-1")) == AgentTokenInfo(
            user_id="u-1", impersonated=True
        )

    def test_a_token_for_another_role_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"sub": "u-1", "role": "user"})) is None

    def test_a_token_without_a_subject_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"role": "agent"})) is None

    def test_a_token_without_a_role_is_rejected(self) -> None:
        assert verify_agent_token(_encode({"sub": "u-1"})) is None

    def test_a_forged_or_garbage_token_is_rejected(self) -> None:
        forged = jwt.encode({"sub": "u-1", "role": "agent"}, "not-the-secret", JWT_ALGORITHM)
        assert verify_agent_token(forged) is None
        assert verify_agent_token("not-a-jwt") is None

    def test_a_token_signed_with_another_algorithm_is_rejected(self) -> None:
        other_alg = jwt.encode({"sub": "u-1", "role": "agent"}, AGENT_SECRET, algorithm="HS512")
        assert verify_agent_token(other_alg) is None

    def test_an_expired_token_is_rejected(self) -> None:
        expired = datetime.now(UTC) - timedelta(minutes=1)
        assert verify_agent_token(_encode({"sub": "u-1", "role": "agent", "exp": expired})) is None


class TestCreateAgentToken:
    def test_the_token_carries_subject_role_and_an_expiry_window(self) -> None:
        before = datetime.now(UTC).replace(microsecond=0)
        claims = jwt.decode(
            create_agent_token("u-9", expires_minutes=7), AGENT_SECRET, [JWT_ALGORITHM]
        )
        assert claims["sub"] == "u-9"
        assert claims["role"] == "agent"
        assert claims["exp"] - claims["iat"] == 7 * 60
        assert claims["iat"] >= int(before.timestamp())
