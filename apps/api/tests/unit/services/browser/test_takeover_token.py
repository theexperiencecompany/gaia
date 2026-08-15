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
    assert claims == {"session_id": "sess-1", "user_id": "user-1"}


async def test_ttl_is_positive_for_fresh_token():
    token = tt.create_takeover_token("sess-1", "user-1")
    ttl = tt.takeover_token_ttl_seconds(token)
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
    with pytest.raises(JWTError):
        tt.verify_takeover_token(forged)


def test_missing_secret_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", None, raising=False)
    with pytest.raises(ValueError, match="BROWSER_TAKEOVER_TOKEN_SECRET is required"):
        tt.create_takeover_token("sess-1", "user-1")


def test_short_secret_raises(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "short", raising=False)
    with pytest.raises(ValueError, match="at least 32 characters"):
        tt.create_takeover_token("sess-1", "user-1")
