"""Record that the request's user used GAIA, on the surface the request came from."""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.middleware.auth import get_current_user
from app.services.user_activity.recording import record_activity
from shared.py.analytics.catalog.attribution import Actor
from shared.py.analytics.context import current_analytics_context


class ActivityRecordingMiddleware(BaseHTTPMiddleware):
    """Mark a signed-in user active when the request is theirs, not a client's automatic one.

    Runs inside PostHogRequestContextMiddleware, which binds the request's attribution.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        user = get_current_user(request)
        attribution = current_analytics_context().attribution
        if user and user.user_id and attribution.actor is Actor.USER:
            await record_activity(user.user_id, attribution.surface)
        return await call_next(request)
