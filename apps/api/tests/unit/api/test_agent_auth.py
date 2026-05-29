"""Unit tests for app.api.v1.middleware.agent_auth — agent-impersonation JWTs.

This is a P0 security boundary: these two functions mint and verify the bearer
tokens that let the agent / bot / voice services impersonate a user on
``/chat-stream``. A bug here is an authentication bypass, so the gate is 100% kill.

UNIT: app/api/v1/middleware/agent_auth.py :: create_agent_token
EXPECTED:
  Given a user_id (and optional expiry minutes), mint an HS256 JWT signed with the
  module's AGENT_SECRET carrying claims sub=user_id, role="agent", a future exp, and
  an iat. The default lifetime is AGENT_TOKEN_EXPIRY_MINUTES (20) minutes.
MECHANISM:
  expire = datetime.now(UTC) + timedelta(minutes=expires_minutes)
  payload = {"sub": user_id, "role": "agent", "exp": expire, "iat": datetime.now(UTC)}
  return jwt.encode(payload, AGENT_SECRET, algorithm=JWT_ALGORITHM)  # HS256

UNIT: app/api/v1/middleware/agent_auth.py :: verify_agent_token
EXPECTED:
  Given a token string, decode + verify it with AGENT_SECRET/HS256. If the signature,
  expiry, or format is invalid -> return None. If valid but role != "agent" -> return
  None. If valid AND role == "agent" -> return {"user_id": <sub claim>, "impersonated": True}.
MECHANISM:
  try: payload = jwt.decode(token, AGENT_SECRET, algorithms=[JWT_ALGORITHM])
       if payload.get("role") != "agent": return None
       return {"user_id": payload.get("sub"), "impersonated": True}
  except JWTError: return None

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - create->verify round-trip: a freshly minted token verifies and yields the exact user_id  [no bypass regression]
  - the minted token actually carries sub=user_id, role="agent", and an exp ~20 min ahead [claim contract]
  - default expiry is exactly AGENT_TOKEN_EXPIRY_MINUTES (exp - iat == 1200s); custom expiry honored
  - exp is in the FUTURE (now + delta, not now - delta) — a past-dated token is rejected by verify
  - tampered payload (modified body, original signature) -> None  [signature integrity]
  - token signed with a DIFFERENT secret -> None  [secret isolation]
  - expired token -> None (ExpiredSignatureError is a JWTError subclass and is swallowed)
  - structurally malformed / garbage token -> None
  - valid HS256 token whose role != "agent" -> None  [privilege gate]
  - valid HS256 token with NO role claim -> None  [missing-claim gate]
  - the returned dict has exactly key "user_id" carrying the "sub" claim, and "impersonated" is True
  - a valid agent token with no "sub" claim -> user_id is None (extraction reads "sub", nothing else)
  - the algorithm is HS256 (a token signed with a different alg / "none" is rejected)

EQUIVALENT MUTANTS (allowed survivors, justified): none expected. The module-level
``AGENT_SECRET`` is the I/O boundary (a secret loaded from settings at import); tests
patch the module's own ``AGENT_SECRET`` binding to a known value, never the functions
under test.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from jose import jwt
import pytest

from app.api.v1.middleware.agent_auth import create_agent_token, verify_agent_token
from app.constants.auth import AGENT_TOKEN_EXPIRY_MINUTES, JWT_ALGORITHM

# ---------------------------------------------------------------------------
# Boundary: the signing secret. Production loads it once at import from
# settings.AGENT_SECRET into the module-level AGENT_SECRET binding. In the unit
# environment that value is None, so every test patches the module's own binding
# to a known secret — this is the single I/O boundary, never the functions.
# ---------------------------------------------------------------------------

_PATCH_SECRET = "app.api.v1.middleware.agent_auth.AGENT_SECRET"
_TEST_SECRET = "agent-impersonation-signing-secret-0123"  # pragma: allowlist secret
_OTHER_SECRET = "a-completely-different-attacker-secret-9"  # pragma: allowlist secret
_USER_ID = "user_64abc123def4567890abcdef"


def _encode(payload: dict, secret: str = _TEST_SECRET, algorithm: str = JWT_ALGORITHM) -> str:
    """Mint a JWT directly via jose at the I/O boundary (no prod logic involved)."""
    return jwt.encode(payload, secret, algorithm=algorithm)


def _future_iat_exp(minutes: int = 30) -> dict:
    now = datetime.now(UTC)
    return {"iat": now, "exp": now + timedelta(minutes=minutes)}


@pytest.mark.unit
class TestCreateAgentToken:
    """create_agent_token — minting the impersonation JWT."""

    def test_minted_token_carries_exact_claims(self) -> None:
        """sub == user_id, role == 'agent', exp/iat present and signed with AGENT_SECRET."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)

        # Decode at the boundary with the same secret/alg to read the real claims.
        decoded = jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])
        assert decoded["sub"] == _USER_ID
        assert decoded["role"] == "agent"
        assert "exp" in decoded
        assert "iat" in decoded

    def test_default_lifetime_is_agent_token_expiry_minutes(self) -> None:
        """With no expires_minutes, exp - iat equals AGENT_TOKEN_EXPIRY_MINUTES (20 min)."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)

        decoded = jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])
        assert decoded["exp"] - decoded["iat"] == AGENT_TOKEN_EXPIRY_MINUTES * 60

    def test_custom_expiry_is_honored(self) -> None:
        """A custom expires_minutes is reflected in the exp - iat delta, not the default."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID, expires_minutes=5)

        decoded = jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])
        assert decoded["exp"] - decoded["iat"] == 5 * 60

    def test_exp_is_in_the_future_not_the_past(self) -> None:
        """exp is now + delta (future), not now - delta — a past exp would be born-expired."""
        before = int(datetime.now(UTC).timestamp())
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)

        decoded = jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])
        assert decoded["exp"] > before
        assert decoded["exp"] > decoded["iat"]

    def test_minted_token_is_signed_with_agent_secret(self) -> None:
        """The token verifies under AGENT_SECRET and is rejected under any other secret."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)

        # Correct secret decodes; a different secret raises (signature isolation).
        assert jwt.decode(token, _TEST_SECRET, algorithms=[JWT_ALGORITHM])["sub"] == _USER_ID
        with pytest.raises(Exception):  # noqa: B017  jose raises JWTError on bad signature
            jwt.decode(token, _OTHER_SECRET, algorithms=[JWT_ALGORITHM])


@pytest.mark.unit
class TestVerifyAgentToken:
    """verify_agent_token — the authentication gate."""

    def test_round_trip_returns_impersonation_payload(self) -> None:
        """A freshly minted token verifies and yields the exact user_id + impersonated flag."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)
            result = verify_agent_token(token)

        assert result == {"user_id": _USER_ID, "impersonated": True}

    def test_returned_payload_shape_is_exact(self) -> None:
        """The returned dict has exactly user_id (from sub) and impersonated=True — nothing else."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = _encode({"sub": "sub_xyz", "role": "agent", **_future_iat_exp()})
            result = verify_agent_token(token)

        assert result is not None
        assert set(result.keys()) == {"user_id", "impersonated"}
        assert result["user_id"] == "sub_xyz"
        assert result["impersonated"] is True

    def test_user_id_extracted_from_sub_claim_only(self) -> None:
        """user_id comes from the 'sub' claim; an unrelated claim does not leak into it."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = _encode(
                {"sub": "the-real-sub", "user_id": "decoy", "role": "agent", **_future_iat_exp()}
            )
            result = verify_agent_token(token)

        assert result is not None
        assert result["user_id"] == "the-real-sub"

    def test_valid_agent_token_without_sub_yields_none_user_id(self) -> None:
        """A valid agent token with no 'sub' claim -> user_id is None (extraction reads 'sub')."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = _encode({"role": "agent", **_future_iat_exp()})
            result = verify_agent_token(token)

        assert result == {"user_id": None, "impersonated": True}

    def test_tampered_payload_rejected(self) -> None:
        """A token whose body was altered but signature kept (tampering) -> None."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = create_agent_token(_USER_ID)
            header_b64, payload_b64, signature_b64 = token.split(".")
            # Swap in a forged payload while keeping the original signature.
            forged_payload = _encode(
                {"sub": "attacker", "role": "agent", **_future_iat_exp()}
            ).split(".")[1]
            tampered = f"{header_b64}.{forged_payload}.{signature_b64}"
            result = verify_agent_token(tampered)

        assert result is None

    def test_token_signed_with_different_secret_rejected(self) -> None:
        """A well-formed agent token signed with the wrong secret -> None (secret isolation)."""
        token = _encode(
            {"sub": _USER_ID, "role": "agent", **_future_iat_exp()}, secret=_OTHER_SECRET
        )
        with patch(_PATCH_SECRET, _TEST_SECRET):
            result = verify_agent_token(token)

        assert result is None

    def test_expired_token_rejected(self) -> None:
        """An otherwise-valid agent token whose exp is in the past -> None."""
        now = datetime.now(UTC)
        token = _encode(
            {
                "sub": _USER_ID,
                "role": "agent",
                "iat": now - timedelta(minutes=40),
                "exp": now - timedelta(minutes=20),
            }
        )
        with patch(_PATCH_SECRET, _TEST_SECRET):
            result = verify_agent_token(token)

        assert result is None

    def test_malformed_token_rejected(self) -> None:
        """A structurally invalid (non-JWT) string -> None, not an unhandled exception."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            assert verify_agent_token("not-a-jwt") is None
            assert verify_agent_token("a.b.c") is None
            assert verify_agent_token("") is None

    def test_wrong_role_rejected(self) -> None:
        """A valid HS256 token whose role is not 'agent' -> None (privilege gate)."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = _encode({"sub": _USER_ID, "role": "user", **_future_iat_exp()})
            result = verify_agent_token(token)

        assert result is None

    def test_missing_role_claim_rejected(self) -> None:
        """A valid HS256 token with no role claim at all -> None (missing-claim gate)."""
        with patch(_PATCH_SECRET, _TEST_SECRET):
            token = _encode({"sub": _USER_ID, **_future_iat_exp()})
            result = verify_agent_token(token)

        assert result is None

    def test_token_with_different_algorithm_rejected(self) -> None:
        """A token whose alg is not the configured HS256 -> None (algorithm pinning)."""
        # HS384 is a valid HMAC alg but not the one this module accepts.
        token = _encode({"sub": _USER_ID, "role": "agent", **_future_iat_exp()}, algorithm="HS384")
        with patch(_PATCH_SECRET, _TEST_SECRET):
            result = verify_agent_token(token)

        assert result is None
