"""Unit tests for the Resend-backed email notification channel adapter.

The HTTP call is faked at the wire (``respx``), not by stubbing the adapter's
own methods, so the assertions are on the exact JSON Resend would receive —
recipient, subject, body and the RFC 8058 one-click unsubscribe headers. The
only stubbed collaborators are the seams the adapter reaches through: the user
repository and the edition renderer (a real browser rasterization).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
from itsdangerous import URLSafeSerializer
import pytest
import respx

from app.config.settings import settings
from app.constants.notifications import (
    CHANNEL_TYPE_EMAIL,
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.models.user_models import UserDocument
from app.utils.email_utils import normalize_email
from app.utils.notification import email_templates
from app.utils.notification.channels import email as email_module
from app.utils.notification.channels.email import RESEND_SEND_URL, EmailChannelAdapter
from app.utils.notification.unsubscribe import _SALT
from tests.helpers import captured_wide_event

_USER_ID = "user-1"
_UNSUB_SECRET = "test-unsub-secret"
_API_HOST = "https://api.test"


def _expected_unsubscribe_url(user_id: str) -> str:
    """The link the adapter must sign for this user.

    Signed here with the same serializer the production helper uses rather
    than pasted as a literal, so the assertion proves the two agree — and so
    the file carries no string shaped like a live credential.
    """
    token = URLSafeSerializer(_UNSUB_SECRET, salt=_SALT).dumps(user_id)
    return f"{_API_HOST}/api/v1/notifications/unsubscribe?token={token}"


def _expected_unsubscribe_headers(user_id: str) -> dict[str, str]:
    return {
        "List-Unsubscribe": f"<{_expected_unsubscribe_url(user_id)}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


_UNSUB_URL = _expected_unsubscribe_url(_USER_ID)
_UNSUB_HEADERS = _expected_unsubscribe_headers(_USER_ID)
_BRIEF_PAYLOAD: dict[str, Any] = {
    "headline": "Three things today",
    "lede": "A calm morning.",
    "hue": 210,
}


@pytest.fixture(autouse=True)
def esp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully configured ESP with a fixed unsubscribe secret, so the signed
    token in the outgoing headers is deterministic."""
    # Deliberately not shaped like a real Resend key (`re_...`): secret scanning
    # flags the vendor prefix, and the value here only has to round-trip.
    monkeypatch.setattr(settings, "RESEND_API_KEY", "unit-test-esp-key")
    monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", _UNSUB_SECRET)
    monkeypatch.setattr(settings, "EMAIL_FROM", "brief@heygaia.io")
    monkeypatch.setattr(settings, "HOST", _API_HOST)


@pytest.fixture(autouse=True)
def user_on_file(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    getter = AsyncMock(return_value=UserDocument(id=_USER_ID, email="Test.User@Example.COM"))
    monkeypatch.setattr(user_repository, "get", getter)
    return getter


@pytest.fixture
def failed_edition_render(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """The edition renderer blows up, so ``deliver`` degrades to the HTML
    template. Its message is the one the wide event has to carry."""
    renderer = AsyncMock(side_effect=RuntimeError("browser died"))
    monkeypatch.setattr(email_module, "render_edition_email", renderer)
    return renderer


def _content(
    kind: str | None = None,
    payload: dict[str, Any] | None = None,
    title: str | None = "Reminder",
    body: str | None = "Stand-up in 10 minutes",
) -> dict[str, Any]:
    return {"kind": kind, "payload": payload, "title": title, "body": body}


def _mock_send(status_code: int = 200) -> respx.Route:
    return respx.post(RESEND_SEND_URL).mock(
        return_value=httpx.Response(status_code, json={"id": "resend-msg-1"})
    )


def _sent_body(route: respx.Route) -> dict[str, Any]:
    request = route.calls.last.request
    parsed: dict[str, Any] = json.loads(request.content)
    return parsed


# ========================================================================
# Adapter identity and content transformation
# ========================================================================


class TestEmailChannelAdapterContract:
    def test_channel_type(self) -> None:
        assert EmailChannelAdapter().channel_type == CHANNEL_TYPE_EMAIL

    def test_can_handle_is_unconditional(self) -> None:
        adapter = EmailChannelAdapter()
        notification = _make_request()

        assert adapter.can_handle(notification) is True
        assert adapter.can_handle(_make_request(kind=None, rich_content=None)) is True

    @pytest.mark.asyncio
    async def test_transform_projects_kind_payload_title_and_body(self) -> None:
        notification = _make_request(
            kind=NOTIFICATION_KIND_BRIEFING_DAILY, rich_content=_BRIEF_PAYLOAD
        )

        assert await EmailChannelAdapter().transform(notification) == {
            "kind": NOTIFICATION_KIND_BRIEFING_DAILY,
            "payload": _BRIEF_PAYLOAD,
            "title": "Reminder",
            "body": "Stand-up in 10 minutes",
        }

    @pytest.mark.asyncio
    async def test_transform_without_kind_or_rich_content(self) -> None:
        assert await EmailChannelAdapter().transform(_make_request()) == {
            "kind": None,
            "payload": None,
            "title": "Reminder",
            "body": "Stand-up in 10 minutes",
        }


def _make_request(
    kind: str | None = None,
    rich_content: dict[str, Any] | None = None,
) -> NotificationRequest:
    return NotificationRequest(
        id="notif-1",
        user_id=_USER_ID,
        source=NotificationSourceEnum.AI_TODO_ADDED,
        type=NotificationType.INFO,
        priority=2,
        channels=[ChannelConfig(channel_type=CHANNEL_TYPE_EMAIL, enabled=True)],
        content=NotificationContent(
            title="Reminder",
            body="Stand-up in 10 minutes",
            rich_content=rich_content,
        ),
        metadata={"kind": kind} if kind else {},
    )


# ========================================================================
# Skip paths — nothing is sent
# ========================================================================


@pytest.mark.asyncio
class TestDeliverSkips:
    @respx.mock
    async def test_skips_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "RESEND_API_KEY", None)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.status == NotificationStatus.FAILED
        assert (
            status.error_message == "email: RESEND_API_KEY/EMAIL_UNSUBSCRIBE_SECRET not configured"
        )
        assert not route.called

    @respx.mock
    async def test_skips_when_api_key_is_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RESEND_API_KEY", "")
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert not route.called

    @respx.mock
    async def test_skips_when_unsubscribe_secret_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", None)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert (
            status.error_message == "email: RESEND_API_KEY/EMAIL_UNSUBSCRIBE_SECRET not configured"
        )
        assert not route.called

    @respx.mock
    async def test_skips_when_user_not_found(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = None
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "email: no email address on file"
        assert status.channel_type == CHANNEL_TYPE_EMAIL
        assert not route.called

    @respx.mock
    async def test_skips_when_user_has_no_email(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(id=_USER_ID, email=None)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.error_message == "email: no email address on file"
        assert not route.called

    @respx.mock
    async def test_skips_when_email_is_not_a_valid_address(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(id=_USER_ID, email="not-an-address")
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.error_message == "email: no email address on file"
        assert not route.called

    @respx.mock
    async def test_a_missing_address_is_never_replaced_by_a_placeholder(
        self, user_on_file: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stand-in address would mail somebody else's inbox a stranger's
        brief, so the empty string — which normalizes to nothing — is the only
        acceptable fallback for a user with no address."""
        user_on_file.return_value = UserDocument(id=_USER_ID, email=None)
        normalizer = MagicMock(side_effect=normalize_email)
        monkeypatch.setattr(email_module, "normalize_email", normalizer)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        normalizer.assert_called_once_with("")
        assert status.skipped is True
        assert not route.called

    async def test_reads_the_user_by_id(self, user_on_file: AsyncMock) -> None:
        with respx.mock:
            _mock_send()
            await EmailChannelAdapter().deliver(_content(), "someone-else")

        user_on_file.assert_awaited_once_with("someone-else")


# ========================================================================
# The outgoing Resend request
# ========================================================================


@pytest.mark.asyncio
class TestDeliverRequestShape:
    @respx.mock
    async def test_plain_notification_payload(self) -> None:
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert _sent_body(route) == {
            "from": "brief@heygaia.io",
            "to": ["test.user@example.com"],
            "subject": "Reminder",
            "html": email_templates.render_plain_notification_email(
                "Reminder", "Stand-up in 10 minutes", _UNSUB_URL
            ),
            "headers": _UNSUB_HEADERS,
        }
        assert status.status == NotificationStatus.DELIVERED
        assert status.skipped is False
        assert status.channel_type == CHANNEL_TYPE_EMAIL
        assert status.delivered_at is not None
        assert status.error_message is None

    @respx.mock
    async def test_authorization_header_carries_the_api_key(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), _USER_ID)

        # The raw list, not the case-insensitive lookup: it is the literal
        # bytes Resend receives, so it pins the header name as well as the key.
        assert (
            b"Authorization",
            b"Bearer unit-test-esp-key",
        ) in route.calls.last.request.headers.raw

    @respx.mock
    async def test_the_send_is_bounded_by_a_ten_second_timeout(self) -> None:
        """An unbounded POST parks a notification worker on a hung ESP."""
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert route.calls.last.request.extensions["timeout"] == {
            "connect": 10.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 10.0,
        }

    @respx.mock
    async def test_unsubscribe_headers_are_per_user(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), "another-user")

        headers = _sent_body(route)["headers"]
        assert headers == _expected_unsubscribe_headers("another-user")
        assert headers["List-Unsubscribe"] != _UNSUB_HEADERS["List-Unsubscribe"]

    @respx.mock
    async def test_mailto_address_is_normalized(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(
            id=_USER_ID, email="mailto:Someone@Example.com?subject=hi"
        )
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert _sent_body(route)["to"] == ["someone@example.com"]

    @respx.mock
    async def test_missing_title_and_body_fall_back_to_defaults(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(title=None, body=None), _USER_ID)

        body = _sent_body(route)
        assert body["subject"] == "GAIA"
        assert body["html"] == email_templates.render_plain_notification_email(
            "GAIA", "", _UNSUB_URL
        )

    @respx.mock
    async def test_unknown_kind_uses_the_plain_template(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind="todo_due", payload=_BRIEF_PAYLOAD), _USER_ID
        )

        body = _sent_body(route)
        assert body["subject"] == "Reminder"
        assert body["html"] == email_templates.render_plain_notification_email(
            "Reminder", "Stand-up in 10 minutes", _UNSUB_URL
        )


# ========================================================================
# Briefing kinds — edition image, with the HTML template as the fallback
# ========================================================================


@pytest.mark.asyncio
class TestDeliverBriefings:
    @respx.mock
    async def test_daily_briefing_renders_the_edition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        renderer = AsyncMock(return_value="<html>edition</html>")
        monkeypatch.setattr(email_module, "render_edition_email", renderer)
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        renderer.assert_awaited_once_with(
            _BRIEF_PAYLOAD,
            kind=NOTIFICATION_KIND_BRIEFING_DAILY,
            user_id=_USER_ID,
            unsubscribe_url=_UNSUB_URL,
        )
        body = _sent_body(route)
        assert body["html"] == "<html>edition</html>"
        assert body["subject"] == "Three things today"

    @respx.mock
    async def test_weekly_briefing_renders_the_edition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        renderer = AsyncMock(return_value="<html>weekly</html>")
        monkeypatch.setattr(email_module, "render_edition_email", renderer)
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        assert renderer.await_args.kwargs["kind"] == NOTIFICATION_KIND_BRIEFING_WEEKLY
        assert _sent_body(route)["html"] == "<html>weekly</html>"

    @respx.mock
    async def test_subject_falls_back_to_title_then_to_a_constant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            email_module, "render_edition_email", AsyncMock(return_value="<html>e</html>")
        )
        route = _mock_send()
        headline_less = {"lede": "no headline here"}

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=headline_less), _USER_ID
        )
        assert _sent_body(route)["subject"] == "Reminder"

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=headline_less, title=None),
            _USER_ID,
        )
        assert _sent_body(route)["subject"] == "Your GAIA brief"

    @respx.mock
    async def test_edition_render_failure_degrades_to_the_daily_template(
        self, failed_edition_render: AsyncMock
    ) -> None:
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        body = _sent_body(route)
        assert body["html"] == email_templates.render_daily_brief_email(_BRIEF_PAYLOAD, _UNSUB_URL)
        assert body["subject"] == "Three things today"
        assert status.status == NotificationStatus.DELIVERED

    @respx.mock
    async def test_edition_render_failure_degrades_to_the_weekly_template(
        self, failed_edition_render: AsyncMock
    ) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        body = _sent_body(route)
        assert body["html"] == email_templates.render_weekly_digest_email(
            _BRIEF_PAYLOAD, _UNSUB_URL
        )
        assert body["subject"] == "Three things today"

    @respx.mock
    async def test_weekly_fallback_subject_falls_back_to_the_title(
        self, failed_edition_render: AsyncMock
    ) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload={"lede": "no headline here"}),
            _USER_ID,
        )

        assert _sent_body(route)["subject"] == "Reminder"

    async def test_edition_render_failure_is_recorded_on_the_wide_event(
        self, failed_edition_render: AsyncMock
    ) -> None:
        """Degrading is only defensible because the failure stays observable —
        so the warning's message and every field it carries are pinned."""
        with respx.mock:
            _mock_send()
            async with captured_wide_event() as event:
                await EmailChannelAdapter().deliver(
                    _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload=_BRIEF_PAYLOAD),
                    _USER_ID,
                )

        assert event["warnings"] == [
            {
                "msg": "[NOTIFICATION] Edition render failed, using plain template",
                "user_id": _USER_ID,
                "kind": NOTIFICATION_KIND_BRIEFING_WEEKLY,
                "error": "browser died",
            }
        ]

    @respx.mock
    async def test_briefing_without_a_payload_never_calls_the_renderer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        renderer = AsyncMock(return_value="<html>edition</html>")
        monkeypatch.setattr(email_module, "render_edition_email", renderer)
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=None), _USER_ID
        )

        renderer.assert_not_awaited()
        body = _sent_body(route)
        assert body["html"] == email_templates.render_daily_brief_email({}, _UNSUB_URL)
        assert body["subject"] == "Reminder"

    @respx.mock
    async def test_daily_and_weekly_fallbacks_use_different_templates(
        self, failed_edition_render: AsyncMock
    ) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=_BRIEF_PAYLOAD), _USER_ID
        )
        daily_html = _sent_body(route)["html"]

        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload=_BRIEF_PAYLOAD), _USER_ID
        )
        weekly_html = _sent_body(route)["html"]

        assert "Daily Brief" in daily_html
        assert "Weekly Digest" in weekly_html
        assert daily_html != weekly_html


# ========================================================================
# Send failures
# ========================================================================


@pytest.mark.asyncio
class TestDeliverFailures:
    @respx.mock
    async def test_non_2xx_response_is_a_failure_not_a_skip(self) -> None:
        _mock_send(status_code=500)

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.status == NotificationStatus.FAILED
        assert status.skipped is False
        assert status.delivered_at is None
        assert status.error_message is not None
        assert status.error_message.startswith("email: send failed (")

    @respx.mock
    async def test_4xx_response_is_a_failure(self) -> None:
        _mock_send(status_code=422)

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.status == NotificationStatus.FAILED
        assert status.skipped is False

    @respx.mock
    async def test_transport_error_is_a_failure(self) -> None:
        respx.post(RESEND_SEND_URL).mock(side_effect=httpx.ConnectError("no route to host"))

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.status == NotificationStatus.FAILED
        assert status.skipped is False
        assert status.error_message == "email: send failed (no route to host)"

    async def test_send_failure_is_recorded_on_the_wide_event(self) -> None:
        """The status the caller gets carries only a message; the event is where
        the failure is queryable, so every field it carries is pinned."""
        with respx.mock:
            respx.post(RESEND_SEND_URL).mock(side_effect=httpx.ConnectError("no route to host"))
            async with captured_wide_event() as event:
                await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert event["errors"] == [
            {
                "msg": "[NOTIFICATION] Email send failed",
                "user_id": _USER_ID,
                "error_type": "ConnectError",
                "error": "no route to host",
            }
        ]

    @respx.mock
    async def test_timeout_is_a_failure(self) -> None:
        respx.post(RESEND_SEND_URL).mock(side_effect=httpx.ReadTimeout("timed out"))

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "email: send failed (timed out)"
