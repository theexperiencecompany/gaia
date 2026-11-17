"""WorkOS session JWTs are verified against one cached signing-key set per process.

Real crypto end to end: a Fernet-sealed cookie, RS256 tokens, the WorkOS SDK's own
session, and PyJWT's key client. Only the JWKS network fetch is faked, so these
pin that caching the keys changed how often they are fetched, never what passes.
"""

import asyncio
import base64
from collections.abc import Iterator
import contextlib
import hashlib
import hmac
import io
import json
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import urllib.error
import urllib.request

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
import jwt
from jwt import api_jwk, jwk_set_cache, jwks_client
from jwt.algorithms import RSAAlgorithm
import pytest
from workos import AsyncWorkOSClient, WorkOSClient
from workos.session import AsyncSession, Session

from app.config.settings import settings
from app.config.workos import with_shared_signing_keys, workos_signing_keys
from app.constants.auth import (
    WORKOS_JWKS_CACHE_SECONDS,
    WORKOS_JWKS_FETCH_TIMEOUT_SECONDS,
    WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS,
)
from app.models.user_models import UserDocument
from app.utils import auth_utils
from app.utils.auth_utils import authenticate_workos_session

COOKIE_PASSWORD = Fernet.generate_key().decode()
WORKOS_USER = {
    "object": "user",
    "id": "user_01",
    "email": "alice@example.com",
    "email_verified": True,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}
KEY_1, KEY_2, FORGER = (
    rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(3)
)


def _jwk(kid: str, key: RSAPrivateKey) -> dict[str, Any]:
    return {**json.loads(RSAAlgorithm.to_jwk(key.public_key())), "kid": kid, "alg": "RS256"}


def _token(key: RSAPrivateKey, kid: str, *, expires_in: int = 300) -> str:
    claims = {"sid": "session_01", "sub": "user_01", "exp": int(time.time()) + expires_in}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _hs256_with_public_key(kid: str) -> str:
    """Forge an HS256 token keyed with the public key: the classic algorithm-confusion attack."""
    secret = KEY_1.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    claims = {"sid": "session_01", "sub": "user_01", "exp": int(time.time()) + 300}
    body = b64(json.dumps(claims).encode())
    signature = b64(hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def _sealed(access_token: str) -> str:
    return Session.seal_data(
        {"access_token": access_token, "refresh_token": "refresh", "user": WORKOS_USER},
        COOKIE_PASSWORD,
    )


class _Jwks:
    """The JWKS endpoint, faked at the network: PyJWKClient.fetch_data runs for real.

    Faking fetch_data itself would skip what it does after the HTTP call (caching
    the set, starting the refresh cooldown), which is exactly what is under test.
    """

    def __init__(self, *keys: dict[str, Any], wait_for: threading.Event | None = None) -> None:
        self.keys = list(keys)
        self.fetches = 0
        self.down = False
        self.timeouts: list[float] = []
        self._wait_for = wait_for

    def build_opener(self, *_handlers: object) -> "_Jwks":
        return self

    def open(
        self, _request: object, timeout: float
    ) -> contextlib.AbstractContextManager[io.BytesIO]:
        self.timeouts.append(timeout)
        if self._wait_for is not None and not self._wait_for.wait(timeout=2):
            raise TimeoutError("the event loop was blocked during the key fetch")
        if self.down:
            raise urllib.error.URLError("WorkOS JWKS endpoint unreachable")
        self.fetches += 1
        return contextlib.nullcontext(io.BytesIO(json.dumps({"keys": self.keys}).encode()))


@contextlib.contextmanager
def _serving(jwks: _Jwks) -> Iterator[_Jwks]:
    with patch.object(urllib.request, "build_opener", jwks.build_opener):
        yield jwks


@contextlib.contextmanager
def _key_cache_clock(now: list[float]) -> Iterator[None]:
    """Drive the key cache's clock (PyJWT's modules only, never asyncio's)."""
    clock = SimpleNamespace(monotonic=lambda: now[0])
    with (
        patch.object(jwks_client, "time", clock),
        patch.object(jwk_set_cache, "time", clock),
        patch.object(api_jwk, "time", clock),
    ):
        yield


@pytest.fixture(autouse=True)
def _fresh_signing_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "WORKOS_COOKIE_PASSWORD", COOKIE_PASSWORD)
    workos_signing_keys.cache_clear()
    yield
    workos_signing_keys.cache_clear()


@pytest.fixture
def known_user() -> Iterator[None]:
    with patch.object(auth_utils, "user_repository") as users:
        users.get_by_email = AsyncMock(
            return_value=UserDocument(id="64abc123def4567890abcdef", email="alice@example.com")
        )
        yield


@pytest.fixture
def refresh() -> Iterator[AsyncMock]:
    """Stub refresh, where a rejected token falls through: it must not reach WorkOS here."""
    with patch.object(
        AsyncSession, "refresh", AsyncMock(return_value=MagicMock(authenticated=False))
    ) as refreshed:
        yield refreshed


def _client() -> AsyncWorkOSClient:
    return AsyncWorkOSClient(api_key="sk_test_unit", client_id="client_unit")


async def _authenticate(access_token: str) -> UserDocument | None:
    user, _ = await authenticate_workos_session(_sealed(access_token), workos_client=_client())
    return None if user is None else UserDocument(id=user.user_id, email=user.email)


@pytest.mark.usefixtures("known_user", "refresh")
async def test_requests_share_one_key_fetch() -> None:
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks:
        first = await _authenticate(_token(KEY_1, "key-1"))
        second = await _authenticate(_token(KEY_1, "key-1"))

    assert first is not None and first.email == "alice@example.com"
    assert second is not None
    assert jwks.fetches == 1


@pytest.mark.usefixtures("known_user")
async def test_a_token_signed_by_another_key_under_a_known_kid_is_rejected(
    refresh: AsyncMock,
) -> None:
    with _serving(_Jwks(_jwk("key-1", KEY_1))):
        user = await _authenticate(_token(FORGER, "key-1"))

    assert user is None
    refresh.assert_awaited_once()


@pytest.mark.usefixtures("known_user")
async def test_an_hs256_token_keyed_with_the_public_key_is_rejected(refresh: AsyncMock) -> None:
    with _serving(_Jwks(_jwk("key-1", KEY_1))):
        user = await _authenticate(_hs256_with_public_key("key-1"))

    assert user is None
    refresh.assert_awaited_once()


@pytest.mark.usefixtures("known_user")
async def test_an_expired_token_is_rejected_even_with_its_key_cached(refresh: AsyncMock) -> None:
    with _serving(_Jwks(_jwk("key-1", KEY_1))):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        user = await _authenticate(_token(KEY_1, "key-1", expires_in=-60))

    assert user is None
    refresh.assert_awaited_once()


@pytest.mark.usefixtures("known_user", "refresh")
async def test_a_rotated_key_is_fetched_once_the_refresh_cooldown_has_passed() -> None:
    now = [1000.0]
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks, _key_cache_clock(now):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        jwks.keys.append(_jwk("key-2", KEY_2))
        now[0] += WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS
        rotated = await _authenticate(_token(KEY_2, "key-2"))

    assert rotated is not None
    assert jwks.fetches == 2


@pytest.mark.usefixtures("known_user", "refresh")
async def test_a_stale_key_id_inside_the_cooldown_forces_no_fetch() -> None:
    now = [1000.0]
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks, _key_cache_clock(now):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        now[0] += WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS - 1
        first = await _authenticate(_token(KEY_2, "retired-key"))
        second = await _authenticate(_token(KEY_2, "retired-key"))

    assert (first, second) == (None, None)
    assert jwks.fetches == 1


@pytest.mark.usefixtures("known_user", "refresh")
async def test_a_key_workos_removed_stops_verifying_once_the_cached_set_expires() -> None:
    now = [1000.0]
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks, _key_cache_clock(now):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        jwks.keys = [_jwk("key-2", KEY_2)]
        now[0] += WORKOS_JWKS_CACHE_SECONDS + 1
        user = await _authenticate(_token(KEY_1, "key-1"))

    assert user is None


@pytest.mark.usefixtures("known_user", "refresh")
async def test_an_outage_after_the_cache_expires_fails_closed() -> None:
    now = [1000.0]
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks, _key_cache_clock(now):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        jwks.down = True
        now[0] += WORKOS_JWKS_CACHE_SECONDS + 1
        user = await _authenticate(_token(KEY_1, "key-1"))

    assert user is None


@pytest.mark.usefixtures("known_user", "refresh")
async def test_a_key_fetch_is_bounded_by_the_fetch_timeout() -> None:
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks:
        await _authenticate(_token(KEY_1, "key-1"))

    assert jwks.timeouts == [WORKOS_JWKS_FETCH_TIMEOUT_SECONDS]


def test_sessions_of_one_client_share_its_key_cache_and_other_clients_get_their_own() -> None:
    def loaded(client_id: str) -> Session:
        client = WorkOSClient(api_key="sk_test_unit", client_id=client_id)
        return with_shared_signing_keys(
            client.user_management.load_sealed_session(
                sealed_session=_sealed(_token(KEY_1, "key-1")), cookie_password=COOKIE_PASSWORD
            )
        )

    first, second, other = loaded("client_a"), loaded("client_a"), loaded("client_b")

    assert first.jwks is second.jwks
    assert other.jwks is not first.jwks
    assert other.jwks.uri.endswith("client_b")


@pytest.mark.usefixtures("known_user", "refresh")
async def test_a_key_fetch_never_blocks_the_event_loop() -> None:
    loop_ran = threading.Event()

    async def other_request() -> None:
        loop_ran.set()

    # The fetch answers only once another coroutine has run: on the loop thread it would starve it.
    with _serving(_Jwks(_jwk("key-1", KEY_1), wait_for=loop_ran)):
        user, _ = await asyncio.gather(_authenticate(_token(KEY_1, "key-1")), other_request())

    assert user is not None


@pytest.mark.usefixtures("known_user", "refresh")
async def test_the_cached_key_set_is_refetched_once_it_outlives_its_lifespan() -> None:
    now = [1000.0]
    with _serving(_Jwks(_jwk("key-1", KEY_1))) as jwks, _key_cache_clock(now):
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        now[0] += WORKOS_JWKS_CACHE_SECONDS
        assert await _authenticate(_token(KEY_1, "key-1")) is not None
        assert jwks.fetches == 1
        now[0] += 1
        assert await _authenticate(_token(KEY_1, "key-1")) is not None

    assert jwks.fetches == 2
