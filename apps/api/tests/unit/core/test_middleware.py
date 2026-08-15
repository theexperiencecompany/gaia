"""Middleware registration order — the invariant PostHog identity rests on.

Starlette runs ``app.user_middleware`` outermost-first, so a middleware's index
IS its execution order. Two orderings here are load-bearing and neither was
asserted anywhere; the module had no unit test at all.
"""

from fastapi import FastAPI
import pytest

from app.core.middleware import configure_middleware


@pytest.fixture
def middleware_names() -> list[str]:
    app = FastAPI()
    configure_middleware(app)
    return [m.cls.__name__ for m in app.user_middleware]


def test_posthog_context_is_registered(middleware_names: list[str]) -> None:
    """Without it no authenticated request is identified and every capture in
    a route handler lands on an anonymous profile."""
    assert "PostHogRequestContextMiddleware" in middleware_names


def test_posthog_context_runs_inside_workos_auth(middleware_names: list[str]) -> None:
    """It reads ``request.state.user``, which WorkOSAuthMiddleware populates.

    Registered the other way round it would run first, see no user, and
    silently identify nobody — the events still send, just unattributed.
    """
    assert middleware_names.index("WorkOSAuthMiddleware") < middleware_names.index(
        "PostHogRequestContextMiddleware"
    )


def test_bot_auth_runs_inside_posthog_context(middleware_names: list[str]) -> None:
    """The documented reason bot routes must attribute explicitly.

    BotAuthMiddleware populates ``request.state.user`` for bot API-key traffic,
    but it runs INSIDE the PostHog context, which has already decided there is
    nobody to identify. Hence ``capture_event(user_id, ...)`` rather than
    ``capture_context_event`` on every bot route (see apps/api/CLAUDE.md).
    Should this order ever flip, that guidance becomes wrong.
    """
    assert middleware_names.index("PostHogRequestContextMiddleware") < (
        middleware_names.index("BotAuthMiddleware")
    )
