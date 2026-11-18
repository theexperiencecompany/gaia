"""The process-wide WorkOS clients, built on first use and only under WorkOS auth.

Built lazily because a local-auth instance has no WorkOS credentials at all, so
constructing a client at import time would crash its boot.
"""

from functools import lru_cache
from typing import TypeVar

from jwt import PyJWKClient
from workos import AsyncWorkOSClient, WorkOSClient
from workos.session import SessionModule

from app.config.settings import settings
from app.constants.auth import (
    WORKOS_JWKS_CACHE_SECONDS,
    WORKOS_JWKS_FETCH_TIMEOUT_SECONDS,
    WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS,
)

SessionT = TypeVar("SessionT", bound=SessionModule)


def _require_workos_auth() -> None:
    """Raise when this deployment authenticates locally and so has no WorkOS."""
    if settings.deployment.local_auth:
        raise RuntimeError("WorkOS is not used under AUTH_MODE=local; no client can be built")


@lru_cache(maxsize=1)
def get_workos_client() -> WorkOSClient:
    """Return the shared synchronous WorkOS client."""
    _require_workos_auth()
    return WorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)


@lru_cache(maxsize=1)
def get_async_workos_client() -> AsyncWorkOSClient:
    """Return the shared asynchronous WorkOS client."""
    _require_workos_auth()
    return AsyncWorkOSClient(api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID)


@lru_cache(maxsize=4)
def workos_signing_keys(jwks_url: str) -> PyJWKClient:
    """Return the process-wide cache of the keys WorkOS signs session JWTs with, for one JWKS URL.

    The SDK gives every session it loads a fresh PyJWKClient, whose empty cache
    made each request fetch the key set over blocking HTTP. Sessions share this
    one instead; see the WORKOS_JWKS_* constants for its lifespan, refetch
    cooldown and fetch timeout.
    """
    return PyJWKClient(
        jwks_url,
        lifespan=WORKOS_JWKS_CACHE_SECONDS,
        cooldown_duration=WORKOS_JWKS_REFRESH_COOLDOWN_SECONDS,
        timeout=WORKOS_JWKS_FETCH_TIMEOUT_SECONDS,
    )


def with_shared_signing_keys(session: SessionT) -> SessionT:
    """Point a loaded session at the process's cached signing keys for its own WorkOS client."""
    session.jwks = workos_signing_keys(session.user_management.get_jwks_url())
    return session
