"""The process-wide WorkOS clients, built on first use and only under WorkOS auth.

Built lazily because a local-auth instance has no WorkOS credentials at all, so
constructing a client at import time would crash its boot.
"""

from functools import lru_cache

from workos import AsyncWorkOSClient, WorkOSClient

from app.config.settings import settings


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
