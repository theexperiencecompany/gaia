"""Unit tests for the email notification channel adapter.

The send is faked at the platform email service (send_email), so assertions are on
the exact message the provider would receive. The other stubbed collaborator is the
user repository. A briefing's edition image is rendered and hosted once by the
briefing service; the email embeds that stored URL, and the rasterizer and CDN upload
are replaced with fakes that fail the test if the email path ever calls them.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from itsdangerous import URLSafeSerializer
from pydantic import ValidationError
import pytest

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
    NotificationChannel,
)
from app.db.repositories.users import user_repository
from app.models.briefing_models import BriefingPayload
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
    NotificationType,
)
from app.models.user_models import UserDocument
from app.services.briefing import edition_email
from app.services.email.models import EmailMessage
from app.utils.email_utils import normalize_email
from app.utils.notification import email_templates
from app.utils.notification.channels import email as email_module
from app.utils.notification.channels.email import (
    BriefingEmail,
    EmailChannelAdapter,
    EmailContent,
)
from app.utils.notification.unsubscribe import _SALT

_USER_ID = "user-1"
_UNSUB_SECRET = "test-unsub-secret"
_API_HOST = "https://api.test"
_FRONTEND_URL = "https://app.test"
_BRIEF_URL = "https://heygaia.link/brief42short"
_EDITION_IMAGE_URL = "https://cdn.test/briefing/editions/user-1/briefing_daily_2026-10-14.png"


def _expected_unsubscribe_url(user_id: str) -> str:
    """Build the link the adapter must sign for this user.

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
    "kicker": "THE MORNING BRIEF",
    "date": "2026-10-14",
    "headline": "Three things today",
    "lede": "A calm morning.",
    "sections": [
        {"numeral": "I", "title": "NEEDS YOU", "items": [{"text": "Pick a slot", "kind": "you"}]}
    ],
    "mood": "clear",
    "caption": "Onward.",
    "hue": 210,
}
_BRIEF = BriefingPayload.model_validate(_BRIEF_PAYLOAD)
_DAILY = BriefingEmail(
    kind=NOTIFICATION_KIND_BRIEFING_DAILY,
    payload=_BRIEF,
    brief_url=_BRIEF_URL,
    edition_image_url=_EDITION_IMAGE_URL,
)
_WEEKLY = BriefingEmail(
    kind=NOTIFICATION_KIND_BRIEFING_WEEKLY,
    payload=_BRIEF,
    brief_url=_BRIEF_URL,
    edition_image_url=_EDITION_IMAGE_URL,
)
_BRIEFING_METADATA = {"brief_url": _BRIEF_URL, "edition_image_url": _EDITION_IMAGE_URL}


@pytest.fixture(autouse=True)
def esp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure a full ESP with a fixed unsubscribe secret.

    That keeps the signed token in the outgoing headers deterministic.
    """
    # Deliberately not shaped like a real Resend key (`re_...`): secret scanning
    # flags the vendor prefix, and the value here only has to round-trip.
    monkeypatch.setattr(settings, "RESEND_API_KEY", "unit-test-esp-key")
    monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", _UNSUB_SECRET)
    monkeypatch.setattr(settings, "EMAIL_FROM", "brief@heygaia.io")
    monkeypatch.setattr(settings, "HOST", _API_HOST)
    monkeypatch.setattr(settings, "FRONTEND_URL", _FRONTEND_URL)


@pytest.fixture(autouse=True)
def user_on_file(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    getter = AsyncMock(return_value=UserDocument(id=_USER_ID, email="Test.User@Example.COM"))
    monkeypatch.setattr(user_repository, "get", getter)
    return getter


@pytest.fixture(autouse=True)
def edition_rendering(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, MagicMock]:
    """Fake the rasterizer and the CDN upload so any email-path call is visible."""
    rasterizer = AsyncMock(side_effect=AssertionError("the email must not render"))
    upload = MagicMock(side_effect=AssertionError("the email must not upload"))
    monkeypatch.setattr(edition_email, "render_html_to_image", rasterizer)
    monkeypatch.setattr(edition_email, "upload_file_to_cloudinary", upload)
    return rasterizer, upload


def _content(
    briefing: BriefingEmail | None = None,
    title: str = "Reminder",
    body: str = "Stand-up in 10 minutes",
) -> EmailContent:
    return EmailContent(title=title, body=body, briefing=briefing)


_SEND = AsyncMock()


@pytest.fixture(autouse=True)
def send_email_seam(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Every test sends through a fresh fake of the platform email service."""
    _SEND.reset_mock(return_value=True, side_effect=True)
    monkeypatch.setattr(email_module, "send_email", _SEND)
    return _SEND


def _mock_send() -> AsyncMock:
    return _SEND


def _sent_body(send: AsyncMock) -> dict[str, Any]:
    """Return the last message, keyed the way the provider's API names its fields."""
    (message,) = send.await_args.args
    assert isinstance(message, EmailMessage)
    return {
        "from": message.sender,
        "to": message.to,
        "subject": message.subject,
        "html": message.html,
        "headers": message.headers,
    }


# ========================================================================
# Adapter identity and content transformation
# ========================================================================


class TestEmailChannelAdapterContract:
    def test_channel_type(self) -> None:
        assert EmailChannelAdapter().channel_type == NotificationChannel.EMAIL

    def test_can_handle_is_unconditional(self) -> None:
        adapter = EmailChannelAdapter()
        notification = _make_request()

        assert adapter.can_handle(notification) is True
        assert adapter.can_handle(_make_request(kind=None, rich_content=None)) is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("briefing", [_DAILY, _WEEKLY], ids=["daily", "weekly"])
    async def test_transform_validates_a_briefing_kinds_payload(
        self, briefing: BriefingEmail
    ) -> None:
        notification = _make_request(
            kind=briefing.kind, rich_content=_BRIEF_PAYLOAD, **_BRIEFING_METADATA
        )

        assert await EmailChannelAdapter().transform(notification) == _content(briefing)

    @pytest.mark.asyncio
    async def test_transform_without_kind_or_rich_content(self) -> None:
        assert await EmailChannelAdapter().transform(_make_request()) == _content()

    @pytest.mark.asyncio
    async def test_transform_leaves_another_kinds_rich_content_unread(self) -> None:
        notification = _make_request(kind="todo_due", rich_content={"todo_id": "t-1"})

        assert await EmailChannelAdapter().transform(notification) == _content()

    @pytest.mark.asyncio
    async def test_transform_fails_loud_on_a_briefing_kind_without_a_payload(self) -> None:
        notification = _make_request(
            kind=NOTIFICATION_KIND_BRIEFING_DAILY, rich_content=None, **_BRIEFING_METADATA
        )

        with pytest.raises(ValidationError):
            await EmailChannelAdapter().transform(notification)

    @pytest.mark.asyncio
    async def test_transform_fails_loud_on_a_malformed_briefing_payload(self) -> None:
        notification = _make_request(
            kind=NOTIFICATION_KIND_BRIEFING_DAILY,
            rich_content={"headline": "only this"},
            **_BRIEFING_METADATA,
        )

        with pytest.raises(ValidationError):
            await EmailChannelAdapter().transform(notification)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "missing",
        [
            {"brief_url": _BRIEF_URL},
            {"edition_image_url": _EDITION_IMAGE_URL},
            {"brief_url": _BRIEF_URL, "edition_image_url": None},
        ],
        ids=["no-image-url", "no-brief-url", "null-image-url"],
    )
    async def test_transform_fails_loud_on_a_briefing_without_its_hosted_edition(
        self, missing: dict[str, str | None]
    ) -> None:
        notification = _make_request(
            kind=NOTIFICATION_KIND_BRIEFING_DAILY, rich_content=_BRIEF_PAYLOAD, **missing
        )

        with pytest.raises(ValidationError):
            await EmailChannelAdapter().transform(notification)


def _make_request(
    kind: str | None = None,
    rich_content: dict[str, Any] | None = None,
    **briefing_metadata: str | None,
) -> NotificationRequest:
    return NotificationRequest(
        id="notif-1",
        user_id=_USER_ID,
        source=NotificationSourceEnum.AI_TODO_ADDED,
        type=NotificationType.INFO,
        priority=2,
        channels=[ChannelConfig(channel_type=NotificationChannel.EMAIL, enabled=True)],
        content=NotificationContent(
            title="Reminder",
            body="Stand-up in 10 minutes",
            rich_content=rich_content,
        ),
        metadata={**({"kind": kind} if kind else {}), **briefing_metadata},
    )


# ========================================================================
# Skip paths — nothing is sent
# ========================================================================


@pytest.mark.asyncio
class TestDeliverSkips:
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

    async def test_skips_when_api_key_is_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "RESEND_API_KEY", "")
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert not route.called

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

    async def test_skips_when_user_not_found(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = None
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.status == NotificationStatus.FAILED
        assert status.error_message == "email: no email address on file"
        assert status.channel_type == NotificationChannel.EMAIL
        assert not route.called

    async def test_skips_when_user_has_no_email(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(id=_USER_ID, email=None)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.error_message == "email: no email address on file"
        assert not route.called

    async def test_skips_when_email_is_not_a_valid_address(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(id=_USER_ID, email="not-an-address")
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped is True
        assert status.error_message == "email: no email address on file"
        assert not route.called

    async def test_a_missing_address_is_never_replaced_by_a_placeholder(
        self, user_on_file: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing address yields the empty string, never a placeholder."""
        user_on_file.return_value = UserDocument(id=_USER_ID, email=None)
        normalizer = MagicMock(side_effect=normalize_email)
        monkeypatch.setattr(email_module, "normalize_email", normalizer)
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        normalizer.assert_called_once_with("")
        assert status.skipped is True
        assert not route.called

    async def test_reads_the_user_by_id(self, user_on_file: AsyncMock) -> None:
        await EmailChannelAdapter().deliver(_content(), "someone-else")

        user_on_file.assert_awaited_once_with("someone-else")


# ========================================================================
# The outgoing message
# ========================================================================


@pytest.mark.asyncio
class TestDeliverRequestShape:
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
        assert status.channel_type == NotificationChannel.EMAIL
        assert status.delivered_at is not None
        assert status.error_message is None

    async def test_unsubscribe_headers_are_per_user(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), "another-user")

        headers = _sent_body(route)["headers"]
        assert headers == _expected_unsubscribe_headers("another-user")
        assert headers["List-Unsubscribe"] != _UNSUB_HEADERS["List-Unsubscribe"]

    async def test_mailto_address_is_normalized(self, user_on_file: AsyncMock) -> None:
        user_on_file.return_value = UserDocument(
            id=_USER_ID, email="mailto:Someone@Example.com?subject=hi"
        )
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert _sent_body(route)["to"] == ["someone@example.com"]

    async def test_missing_title_and_body_fall_back_to_defaults(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(title="", body=""), _USER_ID)

        body = _sent_body(route)
        assert body["subject"] == "GAIA"
        assert body["html"] == email_templates.render_plain_notification_email(
            "GAIA", "", _UNSUB_URL
        )


# ========================================================================
# Briefing kinds — the stored edition image, linked to the brief's own page
# ========================================================================


@pytest.mark.asyncio
class TestDeliverBriefings:
    @pytest.mark.parametrize("briefing", [_DAILY, _WEEKLY], ids=["daily", "weekly"])
    async def test_briefing_embeds_the_stored_edition_image(
        self, briefing: BriefingEmail, edition_rendering: tuple[AsyncMock, MagicMock]
    ) -> None:
        route = _mock_send()

        status = await EmailChannelAdapter().deliver(_content(briefing), _USER_ID)

        body = _sent_body(route)
        assert f'<img src="{_EDITION_IMAGE_URL}"' in body["html"]
        assert body["subject"] == "Three things today"
        assert status.status == NotificationStatus.DELIVERED
        rasterizer, upload = edition_rendering
        rasterizer.assert_not_awaited()
        upload.assert_not_called()

    async def test_the_image_links_to_the_briefs_heygaia_link(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(_DAILY), _USER_ID)

        assert (
            f'<a href="{_BRIEF_URL}" style="text-decoration:none;"><img'
            in _sent_body(route)["html"]
        )

    async def test_the_preheader_is_the_skim_of_the_brief(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(_DAILY), _USER_ID)

        assert (
            '<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">Pick a slot</div>'
        ) in _sent_body(route)["html"]

    async def test_the_briefing_carries_the_users_unsubscribe_link(self) -> None:
        route = _mock_send()

        await EmailChannelAdapter().deliver(_content(_DAILY), _USER_ID)

        body = _sent_body(route)
        assert f'href="{_UNSUB_URL}"' in body["html"]
        assert body["headers"] == _UNSUB_HEADERS

    async def test_a_briefing_without_a_headline_uses_the_notification_title(self) -> None:
        route = _mock_send()
        untitled = BriefingEmail(
            kind=NOTIFICATION_KIND_BRIEFING_DAILY,
            payload=_BRIEF.model_copy(update={"headline": ""}),
            brief_url=_BRIEF_URL,
            edition_image_url=_EDITION_IMAGE_URL,
        )

        await EmailChannelAdapter().deliver(_content(untitled, title="Morning"), _USER_ID)

        assert _sent_body(route)["subject"] == "Morning"

    async def test_transform_then_deliver_sends_the_stored_image(self) -> None:
        route = _mock_send()
        adapter = EmailChannelAdapter()
        notification = _make_request(
            kind=NOTIFICATION_KIND_BRIEFING_WEEKLY,
            rich_content=_BRIEF_PAYLOAD,
            **_BRIEFING_METADATA,
        )

        await adapter.deliver(await adapter.transform(notification), _USER_ID)

        html = _sent_body(route)["html"]
        assert f'<img src="{_EDITION_IMAGE_URL}"' in html
        assert f'href="{_BRIEF_URL}"' in html


# ========================================================================
# Send failures
# ========================================================================


@pytest.mark.asyncio
class TestDeliverFailures:
    async def test_a_failed_send_propagates_to_the_orchestrator(self) -> None:
        """A raising adapter propagates so the orchestrator records a failed channel."""
        _SEND.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            await EmailChannelAdapter().deliver(_content(), _USER_ID)
