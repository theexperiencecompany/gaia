"""Hashed identifiers for wide-event fields that would otherwise carry PII."""

from fastapi import Request

from app.config.settings import settings
from shared.py.logging import hash_log_identifier, text_shape
from shared.py.wide_events import TextShape


def _log_hash_secret() -> str | None:
    return settings.BOT_LOG_HASH_SECRET or settings.GAIA_BOT_API_KEY


def hash_platform_user_id(platform_user_id: str) -> str:
    """Hash a bot platform's user id with the bots' key, so user_hash joins their lines."""
    hashed: str = hash_log_identifier(platform_user_id, _log_hash_secret())
    return hashed


def hash_short_link_slug(slug: str) -> str:
    """Hash a heygaia.link slug for a log field.

    The slug is the capability, so a plaintext one in a log line is a working
    link to someone's artifact.
    """
    hashed: str = hash_log_identifier(slug, _log_hash_secret())
    return hashed


def user_text_shape(text: str) -> TextShape:
    """Shape of a user's query or message for a log field, keyed like every other log hash."""
    return text_shape(text, _log_hash_secret())


def log_route_template_as_path(request: Request) -> None:
    """Route dependency: log this request's path with its path parameters named.

    For routes whose path carries a secret (a heygaia.link slug is a working
    capability), so /api/v1/l/{slug} reaches the logs instead of the live link.
    """
    by_value = {value: f"{{{name}}}" for name, value in request.path_params.items()}
    request.state.loggable_path = "/".join(
        by_value.get(segment, segment) for segment in request.url.path.split("/")
    )


def loggable_request_path(request: Request) -> str:
    """Return the request path as logs may record it.

    Parameters named where a route marked its path secret (log_route_template_as_path),
    the URL path otherwise.
    """
    path: str = getattr(request.state, "loggable_path", request.url.path)
    return path
