"""Signed, stateless unsubscribe tokens for notification emails.

An email's unsubscribe link must work with no login, from any mail
client, so the token itself carries and authenticates the user id (HMAC-signed
via itsdangerous) instead of relying on a session.
"""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

from app.config.settings import settings

_SALT = "email-unsubscribe"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.EMAIL_UNSUBSCRIBE_SECRET, salt=_SALT)


def build_unsubscribe_url(user_id: str) -> str:
    """Builds the absolute one-click unsubscribe URL for a user."""
    token = _serializer().dumps(user_id)
    return f"{settings.HOST}/api/v1/notifications/unsubscribe?token={token}"


def build_unsubscribe_headers(user_id: str) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe headers for lifecycle email
    (https://resend.com/docs/dashboard/emails/add-unsubscribe-to-transactional-emails)."""
    return {
        "List-Unsubscribe": f"<{build_unsubscribe_url(user_id)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def verify_unsubscribe_token(token: str) -> str | None:
    """Returns the user_id a token was signed for, or None if invalid/tampered."""
    if not settings.EMAIL_UNSUBSCRIBE_SECRET:
        return None
    try:
        decoded = _serializer().loads(token)
    except BadSignature:
        return None
    return decoded if isinstance(decoded, str) else None
