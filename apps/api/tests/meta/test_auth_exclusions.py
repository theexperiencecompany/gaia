"""Every path the auth middleware leaves public is a path the app serves.

The exclusions are typed by hand, so an entry without the /api/v1 prefix
matches nothing and its route is silently authenticated.
"""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
import pytest

from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.config.settings import settings
from app.core.app_factory import create_app


@pytest.fixture
def bypass_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build the app as dev bypass mounts it, so the dev router's exclusion has routes to match."""
    monkeypatch.setattr(settings, "DEV_AUTH_BYPASS_EMAIL", "dev@example.com")
    return create_app()


def _matcher(entry: str) -> WorkOSAuthMiddleware:
    """Build a middleware excluding only entry; workos mode appends no exclusions of its own."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "AUTH_MODE", "workos")
        return WorkOSAuthMiddleware(
            app=MagicMock(), workos_client=MagicMock(), exclude_paths=[entry]
        )


@pytest.mark.regression
def test_every_auth_exclusion_matches_a_mounted_route(bypass_app: FastAPI) -> None:
    mounted = [ctx.path for ctx in iter_route_contexts(bypass_app.routes) if ctx.path]
    exclusions = WorkOSAuthMiddleware(app=MagicMock(), workos_client=MagicMock()).exclude_paths

    assert [e for e in exclusions if not any(map(_matcher(e)._is_excluded, mounted))] == []
