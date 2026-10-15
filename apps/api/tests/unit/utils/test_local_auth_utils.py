"""Local session tokens: minted with a version, revoked by the credential row's version."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from jose import jwt
import pytest

from app.constants.auth import JWT_ALGORITHM
from app.models.auth_models import LocalCredentialDocument
from app.utils import local_auth_utils
from app.utils.local_auth_utils import issue_session_token, resolve_session_token
from tests.helpers import captured_wide_event

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
    forged = jwt.encode(
        {"sub": USER_ID, "ver": 0, "exp": datetime.now(UTC) + timedelta(hours=1)},
        TEST_SECRET,
        algorithm="HS512",
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

    assert jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])["sub"] == "u1"
    load.assert_awaited_once_with()
