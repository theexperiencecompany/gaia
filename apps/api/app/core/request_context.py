"""The authenticated user for the current request, reachable without a ``Request``.

``WorkOSAuthMiddleware`` is the single source of truth for who is calling: it
sets ``request.state.user``. Decorators that wrap route handlers can't read that
— they only see ``*args``/``**kwargs``, and FastAPI invokes handlers with keyword
arguments whose names are chosen per-endpoint. ``@tiered_rate_limit`` used to
resolve the caller by looking for a kwarg literally named ``user``, which meant
naming the parameter ``current_user``/``user_id``/``_user`` silently disabled
rate limiting for that route — no log, no error, just unlimited access.

This ContextVar carries the same dict the middleware puts on ``request.state``,
so the decorator reads the authenticated user directly instead of guessing at
parameter names. ContextVars set before ``call_next`` propagate into the
downstream task, and a set inside one request's task never leaks into another's.
"""

from contextvars import ContextVar

from app.models.user_models import AuthenticatedUser

_authenticated_user: ContextVar[AuthenticatedUser | None] = ContextVar(
    "authenticated_user", default=None
)


def set_authenticated_user(user: AuthenticatedUser | None) -> None:
    """Mirror ``request.state.user`` into the request context."""
    _authenticated_user.set(user)


def get_authenticated_user() -> AuthenticatedUser | None:
    """The authenticated user for this request, or ``None`` on a public route."""
    return _authenticated_user.get()
