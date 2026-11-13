"""One way to answer a crash: capture it, then return the 500 envelope.

Shared by the pure-ASGI catch-all inside CORS and by the last-resort handler in
ServerErrorMiddleware, so the two cannot report the same crash differently.
"""

from fastapi import Request, status
from fastapi.responses import UJSONResponse

from app.constants.analytics import POSTHOG_PROVIDER_KEY
from app.core.lazy_loader import providers
from app.schemas.errors import ErrorEnvelope, error_response

INTERNAL_ERROR_MESSAGE = "Internal server error"
INTERNAL_ERROR_CODE = "internal_server_error"


def internal_error_response() -> UJSONResponse:
    """Render the generic 500 body, which never leaks what actually failed."""
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorEnvelope(message=INTERNAL_ERROR_MESSAGE, code=INTERNAL_ERROR_CODE),
    )


def capture_unhandled_exception(request: Request, exc: Exception) -> None:
    """Attribute a crash to the user who hit it, in PostHog.

    PostHogRequestContextMiddleware identifies inside a context around
    call_next, which an escaping exception unwinds before it can be read, so
    every 500 would land on an anonymous profile. request.state survives
    because it lives on the request object, not a contextvar.
    """
    # Guard like PostHogRequestContextMiddleware: this runs even in apps built
    # without the production lifespan (tests, scripts), where the provider is
    # never registered and providers.get would raise KeyError.
    posthog_client = (
        providers.get(POSTHOG_PROVIDER_KEY)
        if providers.is_available(POSTHOG_PROVIDER_KEY)
        else None
    )
    if posthog_client is None:
        return
    # Read by attribute rather than through AuthenticatedUser: the embedding
    # sidecar shares this module and must stay free of app.config.settings,
    # which importing the user model (or the auth middleware) would load.
    user_id = getattr(getattr(request.state, "user", None), "user_id", None)
    if isinstance(user_id, str) and user_id:
        posthog_client.capture_exception(exc, distinct_id=user_id)
    else:
        posthog_client.capture_exception(exc)
