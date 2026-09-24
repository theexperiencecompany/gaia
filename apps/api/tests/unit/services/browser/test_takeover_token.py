"""Tests for the browser live-view takeover token — round-trip, tamper, expiry."""

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
import pytest

from app.config.settings import settings
from app.constants.auth import JWT_ALGORITHM
from app.services.browser import takeover_token as tt

_SECRET = "x" * 40


@pytest.fixture(autouse=True)
def _takeover_secret(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", _SECRET, raising=False)


async def test_round_trip_returns_session_and_user():
    token = tt.create_takeover_token("sess-1", "user-1")
    claims = tt.verify_takeover_token(token)
    assert claims["session_id"] == "sess-1"
    assert claims["user_id"] == "user-1"
    assert "exp" in claims


async def test_ttl_is_positive_for_fresh_token():
    token = tt.create_takeover_token("sess-1", "user-1")
    claims = tt.verify_takeover_token(token)
    ttl = tt.takeover_token_ttl_seconds(claims)
    assert 0 < ttl <= tt._TAKEOVER_TOKEN_EXPIRY_MINUTES * 60


async def test_tampered_token_fails():
    token = tt.create_takeover_token("sess-1", "user-1")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(JWTError):
        tt.verify_takeover_token(tampered)


async def test_token_signed_with_other_secret_fails(monkeypatch):
    token = tt.create_takeover_token("sess-1", "user-1")
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "y" * 40, raising=False)
    with pytest.raises(JWTError):
        tt.verify_takeover_token(token)


async def test_expired_token_fails(monkeypatch):
    monkeypatch.setattr(tt, "_TAKEOVER_TOKEN_EXPIRY_MINUTES", -1)
    token = tt.create_takeover_token("sess-1", "user-1")
    with pytest.raises(JWTError):
        tt.verify_takeover_token(token)


async def test_wrong_role_rejected():
    # A validly-signed token whose role is not browser_takeover must be refused.
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "bot",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Invalid token role"):
        tt.verify_takeover_token(forged)


def test_missing_secret_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", None, raising=False)
    with pytest.raises(ValueError, match="BROWSER_TAKEOVER_TOKEN_SECRET is required"):
        tt.create_takeover_token("sess-1", "user-1")


def test_short_secret_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "short", raising=False)
    with pytest.raises(ValueError, match="at least 32 characters"):
        tt.create_takeover_token("sess-1", "user-1")


def test_secret_exactly_at_minimum_length_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "z" * 32, raising=False)
    # Must not raise: 32 is the inclusive minimum, not an exclusive boundary.
    token = tt.create_takeover_token("sess-1", "user-1")
    assert tt.verify_takeover_token(token)["session_id"] == "sess-1"


def test_secret_one_below_minimum_length_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "z" * 31, raising=False)
    with pytest.raises(ValueError, match="at least 32 characters"):
        tt.create_takeover_token("sess-1", "user-1")


def test_create_takeover_token_claims_have_exact_shape():
    token = tt.create_takeover_token("sess-1", "user-1")
    payload = jwt.decode(token, _SECRET, algorithms=[JWT_ALGORITHM])
    assert payload["sub"] == "user-1"
    assert payload["session_id"] == "sess-1"
    assert payload["role"] == "browser_takeover"
    assert "iat" in payload
    assert "exp" in payload


def test_create_takeover_token_expiry_matches_configured_minutes():
    token = tt.create_takeover_token("sess-1", "user-1")
    payload = jwt.decode(token, _SECRET, algorithms=[JWT_ALGORITHM])
    expected_seconds = tt._TAKEOVER_TOKEN_EXPIRY_MINUTES * 60
    assert payload["exp"] - payload["iat"] == pytest.approx(expected_seconds, abs=2)


def test_verify_rejects_missing_session_id():
    forged = jwt.encode(
        {
            "sub": "user-1",
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Takeover token missing session_id, subject, or expiry"):
        tt.verify_takeover_token(forged)


def test_verify_rejects_missing_user_id():
    forged = jwt.encode(
        {
            "session_id": "sess-1",
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Takeover token missing session_id, subject, or expiry"):
        tt.verify_takeover_token(forged)


def test_verify_rejects_missing_exp():
    # jose does not itself require "exp" to be present, so a token missing it
    # reaches our own isinstance(exp, (int, float)) check.
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "browser_takeover",
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError) as exc:
        tt.verify_takeover_token(forged)
    assert str(exc.value) == "Takeover token missing session_id, subject, or expiry"


def test_verify_missing_role_key_is_rejected():
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Invalid token role"):
        tt.verify_takeover_token(forged)


def test_verify_returns_exact_claims_values():
    token = tt.create_takeover_token("sess-42", "user-99")
    claims = tt.verify_takeover_token(token)
    assert claims == {
        "session_id": "sess-42",
        "user_id": "user-99",
        "exp": claims["exp"],
    }
    assert set(claims.keys()) == {"session_id", "user_id", "exp"}


def test_ttl_seconds_negative_once_past_expiry():
    past_claims: tt.TakeoverTokenClaims = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "exp": (datetime.now(UTC) - timedelta(seconds=1000)).timestamp(),
    }
    ttl = tt.takeover_token_ttl_seconds(past_claims)
    assert ttl == pytest.approx(-1000, abs=2)


def test_a_token_is_signed_with_the_configured_algorithm_not_the_library_default(monkeypatch):
    monkeypatch.setattr(tt, "JWT_ALGORITHM", "HS512")

    token = tt.create_takeover_token("sess-1", "user-1")

    assert jwt.get_unverified_header(token)["alg"] == "HS512"
    assert tt.verify_takeover_token(token)["session_id"] == "sess-1"


def test_a_token_signed_with_the_right_secret_under_another_algorithm_is_rejected():
    # The allow-list is what stops a token minted under any HMAC variant the
    # secret can sign from passing: only the configured algorithm verifies.
    other_alg = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm="HS512",
    )

    with pytest.raises(JWTError, match="^Takeover token verification failed: "):
        tt.verify_takeover_token(other_alg)


def test_a_bad_signature_is_reported_as_a_takeover_verification_failure():
    token = tt.create_takeover_token("sess-1", "user-1")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")

    with pytest.raises(JWTError, match="^Takeover token verification failed: "):
        tt.verify_takeover_token(tampered)


def test_a_claim_of_the_wrong_type_is_rejected_as_a_missing_claim():
    # Strict validation: a numeric session_id is not a session id, even if it
    # would coerce to one.
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": 42,
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(JWTError) as exc:
        tt.verify_takeover_token(forged)
    assert str(exc.value) == "Takeover token missing session_id, subject, or expiry"


def test_a_wrong_role_is_rejected_with_exactly_the_role_error():
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "bot",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )

    with pytest.raises(JWTError) as exc:
        tt.verify_takeover_token(forged)
    assert str(exc.value) == "Invalid token role"


def test_a_missing_secret_tells_the_operator_how_to_generate_one(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "", raising=False)

    with pytest.raises(ValueError) as exc:
        tt.create_takeover_token("sess-1", "user-1")
    assert str(exc.value) == (
        "BROWSER_TAKEOVER_TOKEN_SECRET is required for browser takeover token signing. "
        "Generate with: openssl rand -hex 32"
    )
