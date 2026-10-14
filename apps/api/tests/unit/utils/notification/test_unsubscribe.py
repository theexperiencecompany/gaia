"""Scoped unsubscribe tokens, the URLs and headers that carry them, and the confirmation page."""

from unittest.mock import patch

from app.utils.notification.unsubscribe import (
    UnsubscribeScope,
    build_invite_unsubscribe_url,
    build_unsubscribe_headers,
    build_unsubscribe_url,
    one_click_unsubscribe_headers,
    render_unsubscribe_confirmation,
    sign_unsubscribe_token,
    verify_scoped_unsubscribe_token,
    verify_unsubscribe_token,
)

HOST = "http://localhost:8000"
INVITE_URL_PREFIX = f"{HOST}/api/v1/referrals/unsubscribe/"
NOTIFICATIONS_URL_PREFIX = f"{HOST}/api/v1/notifications/unsubscribe?token="


def test_an_invite_link_carries_a_token_for_the_recipient_address() -> None:
    url = build_invite_unsubscribe_url("priya@example.com")

    assert url.startswith(INVITE_URL_PREFIX)
    token = url.removeprefix(INVITE_URL_PREFIX)
    assert (
        verify_scoped_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, token)
        == "priya@example.com"
    )


def test_a_lifecycle_link_carries_a_token_for_the_user() -> None:
    url = build_unsubscribe_url("user-123")

    assert url.startswith(NOTIFICATIONS_URL_PREFIX)
    assert verify_unsubscribe_token(url.removeprefix(NOTIFICATIONS_URL_PREFIX)) == "user-123"


def test_a_token_opts_out_of_its_own_scope_only() -> None:
    invite_token = sign_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, "priya@example.com")
    lifecycle_token = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, "user-123")

    assert verify_unsubscribe_token(invite_token) is None
    assert (
        verify_scoped_unsubscribe_token(UnsubscribeScope.REFERRAL_INVITES, lifecycle_token) is None
    )


def test_a_tampered_token_verifies_to_nothing() -> None:
    token = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, "user-123")

    assert verify_unsubscribe_token(token[:-2] + "xx") is None


def test_without_a_signing_secret_no_token_verifies() -> None:
    token = sign_unsubscribe_token(UnsubscribeScope.NOTIFICATIONS, "user-123")

    with patch("app.utils.notification.unsubscribe.settings.EMAIL_UNSUBSCRIBE_SECRET", ""):
        assert verify_unsubscribe_token(token) is None


def test_one_click_headers_point_at_the_url() -> None:
    assert one_click_unsubscribe_headers("https://x.test/u") == {
        "List-Unsubscribe": "<https://x.test/u>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def test_lifecycle_headers_carry_the_users_unsubscribe_url() -> None:
    headers = build_unsubscribe_headers("user-123")

    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    url = headers["List-Unsubscribe"].removeprefix("<").removesuffix(">")
    assert verify_unsubscribe_token(url.removeprefix(NOTIFICATIONS_URL_PREFIX)) == "user-123"


def test_the_confirmation_page_posts_to_the_action_and_escapes_both_inputs() -> None:
    page = render_unsubscribe_confirmation("Stop <invites>?", "/u/a'b")

    assert page == (
        "<!doctype html><html><body style='font-family: sans-serif; padding: 40px; "
        "text-align: center;'><p>Stop &lt;invites&gt;?</p>"
        "<form method='post' action='/u/a&#x27;b'>"
        "<button style='background-color: #00bbff; color: #ffffff; padding: 8px 16px; "
        "border: none; border-radius: 4px; cursor: pointer;'>Unsubscribe</button>"
        "</form></body></html>"
    )
