"""Local session tokens: minted with a version, revoked by the credential row's version."""

from datetime import UTC, datetime, timedelta
import time
from unittest.mock import AsyncMock

import pytest

from app.models.auth_models import LocalCredentialDocument
from app.utils import local_auth_utils
from app.utils.local_auth_utils import (
    SESSION_TTL_SECONDS,
    issue_session_token,
    resolve_session_token,
)
from tests.helpers import (
    JOSE_MINTED_SESSION_TOKEN,
    captured_wide_event,
    forge_jwt,
    hostile_jwts,
    local_timezone,
    read_jwt,
)

TEST_SECRET = "test-instance-secret-" + "x" * 16
USER_ID = "507f1f77bcf86cd799439011"


class _Credentials:
    """The one credential-store read session resolution makes."""

    def __init__(self) -> None:
        self.rows: dict[str, LocalCredentialDocument] = {}
        self.get_by_user_id = AsyncMock(side_effect=lambda user_id: self.rows.get(user_id))

    def add(self, *, version: int = 0, disabled: bool = False) -> None:
        self.rows[USER_ID] = LocalCredentialDocument(
            user_id=USER_ID,
            password_hash="bcrypt-hash",
            token_version=version,
            disabled_at=datetime.now(UTC) if disabled else None,
        )


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> _Credentials:
    store = _Credentials()
    monkeypatch.setattr(local_auth_utils, "local_credentials_repository", store)
    monkeypatch.setattr(local_auth_utils, "_resolved_secret", TEST_SECRET)
    return store


async def test_only_a_token_of_the_current_version_resolves(credentials: _Credentials) -> None:
    credentials.add(version=2)

    assert await resolve_session_token(await issue_session_token(USER_ID, 2)) == USER_ID
    assert await resolve_session_token(await issue_session_token(USER_ID, 1)) is None
    credentials.get_by_user_id.assert_awaited_with(USER_ID)


async def test_a_removed_account_stops_resolving(credentials: _Credentials) -> None:
    credentials.add(disabled=True)

    assert await resolve_session_token(await issue_session_token(USER_ID, 0)) is None


async def test_without_a_credential_row_only_a_legacy_token_resolves(
    credentials: _Credentials,
) -> None:
    assert await resolve_session_token(await issue_session_token(USER_ID, 0)) == USER_ID
    assert await resolve_session_token(await issue_session_token(USER_ID, 1)) is None


async def test_with_the_store_down_only_a_legacy_token_resolves_and_it_is_warned(
    credentials: _Credentials,
) -> None:
    credentials.get_by_user_id.side_effect = ConnectionError("mongo down")

    async with captured_wide_event() as event:
        legacy = await resolve_session_token(await issue_session_token(USER_ID, 0))
        versioned = await resolve_session_token(await issue_session_token(USER_ID, 1))

    assert (legacy, versioned) == (USER_ID, None)
    assert (
        event["warnings"]
        == [
            {
                "msg": "local session version check failed — DB unavailable",
                "error": "mongo down",
                "error_type": "ConnectionError",
            }
        ]
        * 2
    )


async def test_a_token_signed_with_another_algorithm_is_refused(credentials: _Credentials) -> None:
    forged = forge_jwt(
        {
            "sub": USER_ID,
            "ver": 0,
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        alg="HS512",
    )

    assert await resolve_session_token(forged) is None


async def test_a_cold_process_reads_the_instance_secret_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load = AsyncMock(return_value=TEST_SECRET)
    monkeypatch.setattr(local_auth_utils, "get_instance_secret", load)
    monkeypatch.setattr(local_auth_utils, "_resolved_secret", None)

    token = await issue_session_token("u1", 0)
    await issue_session_token("u2", 0)

    assert local_auth_utils._decode_session(token, TEST_SECRET) == ("u1", 0)
    load.assert_awaited_once_with()


async def test_a_token_stamps_the_true_instant_whatever_the_host_zone(
    credentials: _Credentials,
) -> None:
    with local_timezone("Asia/Kolkata"):
        token = await issue_session_token(USER_ID, 0)
        _, claims = read_jwt(token)

    assert abs(claims["iat"] - time.time()) < 60
    assert claims["exp"] - claims["iat"] == SESSION_TTL_SECONDS


async def test_a_token_is_signed_with_the_configured_algorithm(
    credentials: _Credentials, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_auth_utils, "JWT_ALGORITHM", "HS512")
    credentials.add(version=0)

    token = await issue_session_token(USER_ID, 0)

    assert read_jwt(token)[0]["alg"] == "HS512"
    assert await resolve_session_token(token) == USER_ID


async def test_a_session_token_minted_by_python_jose_still_resolves(
    credentials: _Credentials,
) -> None:
    credentials.rows["u-jose"] = LocalCredentialDocument(
        user_id="u-jose", password_hash="bcrypt-hash", token_version=3
    )

    assert await resolve_session_token(JOSE_MINTED_SESSION_TOKEN) == "u-jose"


@pytest.mark.parametrize("kind", sorted(hostile_jwts({}, "s")))
async def test_a_hostile_session_token_is_refused(credentials: _Credentials, kind: str) -> None:
    credentials.add(version=0)
    claims = {"sub": USER_ID, "ver": 0, "exp": int(time.time()) + 3600}

    assert await resolve_session_token(hostile_jwts(claims, TEST_SECRET)[kind]) is None


async def test_a_session_token_naming_no_user_is_refused(credentials: _Credentials) -> None:
    credentials.add(version=0)
    token = forge_jwt({"ver": 0, "exp": int(time.time()) + 3600}, TEST_SECRET)

    assert await resolve_session_token(token) is None


def test_a_session_token_with_a_non_integer_version_is_refused() -> None:
    forged = forge_jwt({"sub": "u1", "ver": "abc", "exp": int(time.time()) + 600}, TEST_SECRET)

    assert local_auth_utils._decode_session(forged, TEST_SECRET) is None
