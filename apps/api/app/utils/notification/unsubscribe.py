"""Signed, stateless unsubscribe tokens and the confirmation page every opt-out link opens.

An unsubscribe link must work with no login, from any mail client, so the token
itself carries and authenticates its subject (HMAC-signed via itsdangerous)
instead of relying on a session. Each scope signs with its own salt, so a token
minted for one list can never opt anyone out of another.
"""

from __future__ import annotations

from enum import StrEnum
from html import escape

from itsdangerous import BadSignature, URLSafeSerializer

from app.config.settings import settings
from app.constants.referrals import INVITE_UNSUBSCRIBE_PATH

NOTIFICATIONS_UNSUBSCRIBE_PATH = "/api/v1/notifications/unsubscribe"

UNSUBSCRIBE_INVALID_HTML = (
    "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
    "text-align: center;'><p>This unsubscribe link is invalid.</p>"
    "</body></html>"
)


class UnsubscribeScope(StrEnum):
    """Which opt-out a token is for; the value is the signing salt."""

    NOTIFICATIONS = "email-unsubscribe"
    REFERRAL_INVITES = "referral-invite-unsubscribe"


def _serializer(scope: UnsubscribeScope) -> URLSafeSerializer:
    return URLSafeSerializer(settings.EMAIL_UNSUBSCRIBE_SECRET, salt=scope.value)


def sign_unsubscribe_token(scope: UnsubscribeScope, subject: str) -> str:
    """Sign subject (a user id, or an address that has no account) for one opt-out scope."""
    token = _serializer(scope).dumps(subject)
    return str(token)


def verify_scoped_unsubscribe_token(scope: UnsubscribeScope, token: str) -> str | None:
    """Return the subject a token was signed for in this scope, or None if invalid or tampered."""
    if not settings.EMAIL_UNSUBSCRIBE_SECRET:
        return None
    try:
        decoded = _serializer(scope).loads(token)
    except BadSignature:
        return None
    return decoded if isinstance(decoded, str) else None


def one_click_unsubscribe_headers(url: str) -> dict[str, str]:
    """Build RFC 8058 one-click unsubscribe headers pointing at url."""
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def render_unsubscribe_confirmation(prompt: str, action_url: str) -> str:
    """Render the page an unsubscribe link opens: a button that POSTs, so a link scanner's GET opts nobody out."""
    return (
        "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
        f"text-align: center;'><p>{escape(prompt)}</p>"
        f"<form method='post' action='{escape(action_url)}'>"
        "<button style='background-color: #00bbff; color: #ffffff; padding: 8px 16px; "
        "border: none; border-radius: 4px; cursor: pointer;'>Unsubscribe</button>"
        "</form></body></html>"
    )


def build_unsubscribe_url(user_id: str) -> str:
    """Build the absolute one-click unsubscribe URL for a user's lifecycle emails."""
    token = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, user_id)
    return f"{settings.HOST}{NOTIFICATIONS_UNSUBSCRIBE_PATH}?token={token}"


def build_unsubscribe_headers(user_id: str) -> dict[str, str]:
    """Build RFC 8058 one-click unsubscribe headers for a lifecycle email."""
    return one_click_unsubscribe_headers(build_unsubscribe_url(user_id))


def verify_unsubscribe_token(token: str) -> str | None:
    """Return the user_id a lifecycle-email token was signed for, or None if invalid/tampered."""
    return verify_scoped_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, token)


def build_invite_unsubscribe_url(email: str) -> str:
    """Build the absolute opt-out URL for an invite recipient, who may have no account."""
    token = sign_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, email)
    return f"{settings.HOST}{INVITE_UNSUBSCRIBE_PATH}{token}"
