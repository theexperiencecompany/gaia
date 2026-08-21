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


def test_missing_secret_message_includes_generation_hint(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "", raising=False)
    with pytest.raises(ValueError, match=r"openssl rand -hex 32"):
        tt.create_takeover_token("sess-1", "user-1")


def test_short_secret_message_reports_exact_current_length(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", "y" * 17, raising=False)
    with pytest.raises(ValueError, match=r"\(current: 17\)"):
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


def test_create_takeover_token_uses_configured_algorithm():
    token = tt.create_takeover_token("sess-1", "user-1")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == JWT_ALGORITHM


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


def test_verify_rejects_non_string_session_id():
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": 12345,
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


def test_verify_wraps_jose_rejection_of_non_string_subject():
    # jose itself validates the registered "sub" claim's type during decode, so a
    # non-string subject never reaches our own isinstance check — it surfaces as a
    # wrapped JWTError instead. Still must propagate, not succeed silently.
    forged = jwt.encode(
        {
            "sub": 999,
            "session_id": "sess-1",
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Takeover token verification failed:"):
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
    with pytest.raises(JWTError, match="Takeover token missing session_id, subject, or expiry"):
        tt.verify_takeover_token(forged)


def test_verify_wraps_jose_rejection_of_non_numeric_exp():
    # jose validates the registered "exp" claim's type during decode, so a
    # non-numeric exp never reaches our own isinstance check either.
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "browser_takeover",
            "exp": "not-a-number",
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError, match="Takeover token verification failed:"):
        tt.verify_takeover_token(forged)


def test_verify_accepts_integer_exp_and_returns_float():
    exp_int = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    forged = jwt.encode(
        {
            "sub": "user-1",
            "session_id": "sess-1",
            "role": "browser_takeover",
            "exp": exp_int,
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    claims = tt.verify_takeover_token(forged)
    assert claims["exp"] == float(exp_int)
    assert isinstance(claims["exp"], float)


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


def test_verify_error_message_wraps_original_jose_failure():
    token = tt.create_takeover_token("sess-1", "user-1")
    tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
    with pytest.raises(JWTError, match="Takeover token verification failed:"):
        tt.verify_takeover_token(tampered)


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


def test_ttl_seconds_matches_future_offset():
    future_claims: tt.TakeoverTokenClaims = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "exp": (datetime.now(UTC) + timedelta(seconds=1000)).timestamp(),
    }
    ttl = tt.takeover_token_ttl_seconds(future_claims)
    assert ttl == pytest.approx(1000, abs=2)


def test_create_takeover_token_reads_current_time_in_utc(monkeypatch):
    # now = datetime.now(UTC) must be called with the UTC tzinfo specifically —
    # a tz-naive "now" would silently shift iat/exp by the host's local offset.
    real_datetime = tt.datetime
    captured: list[object] = []

    class SpyDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            captured.append(tz)
            return real_datetime.now(tz)

    monkeypatch.setattr(tt, "datetime", SpyDatetime)
    tt.create_takeover_token("sess-1", "user-1")
    assert captured == [UTC]


def test_create_takeover_token_passes_configured_algorithm_to_jwt_encode(monkeypatch):
    captured: dict[str, object] = {}

    def fake_encode(claims, key, algorithm=None, headers=None, access_token=None):
        captured["algorithm"] = algorithm
        return "fake-token"

    monkeypatch.setattr(tt.jwt, "encode", fake_encode)
    token = tt.create_takeover_token("sess-1", "user-1")
    assert token == "fake-token"
    assert captured["algorithm"] == JWT_ALGORITHM


def test_verify_takeover_token_passes_configured_algorithms_to_jwt_decode(monkeypatch):
    token = tt.create_takeover_token("sess-1", "user-1")
    real_decode = tt.jwt.decode
    captured: dict[str, object] = {}

    def fake_decode(token_, key, algorithms=None, **kwargs):
        captured["algorithms"] = algorithms
        return real_decode(token_, key, algorithms=[JWT_ALGORITHM], **kwargs)

    monkeypatch.setattr(tt.jwt, "decode", fake_decode)
    claims = tt.verify_takeover_token(token)
    assert captured["algorithms"] == [JWT_ALGORITHM]
    assert claims["session_id"] == "sess-1"


def test_ttl_seconds_reads_current_time_in_utc(monkeypatch):
    real_datetime = tt.datetime
    captured: list[object] = []

    class SpyDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            captured.append(tz)
            return real_datetime.now(tz)

    monkeypatch.setattr(tt, "datetime", SpyDatetime)
    claims: tt.TakeoverTokenClaims = {
        "session_id": "sess-1",
        "user_id": "user-1",
        "exp": 0.0,
    }
    tt.takeover_token_ttl_seconds(claims)
    assert captured == [UTC]


def test_invalid_token_role_message_is_exact():
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
    with pytest.raises(JWTError) as exc_info:
        tt.verify_takeover_token(forged)
    assert str(exc_info.value) == "Invalid token role"


def test_missing_claims_message_is_exact():
    forged = jwt.encode(
        {
            "sub": "user-1",
            "role": "browser_takeover",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        _SECRET,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(JWTError) as exc_info:
        tt.verify_takeover_token(forged)
    assert str(exc_info.value) == "Takeover token missing session_id, subject, or expiry"


def test_missing_secret_message_is_exact(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_TAKEOVER_TOKEN_SECRET", None, raising=False)
    with pytest.raises(ValueError) as exc_info:
        tt.create_takeover_token("sess-1", "user-1")
    assert str(exc_info.value) == (
        "BROWSER_TAKEOVER_TOKEN_SECRET is required for browser takeover token signing. "
        "Generate with: openssl rand -hex 32"
    )
