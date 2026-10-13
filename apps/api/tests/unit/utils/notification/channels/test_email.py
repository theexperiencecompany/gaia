"""Unit tests for the email notification channel adapter.

The only faked seams are the user repository and ``send_email`` (the platform
email service, tested on its own): assertions read the exact ``EmailMessage``
the provider would receive — recipient, subject, rendered body and the RFC 8058
one-click unsubscribe headers. Templates render for real.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from itsdangerous import URLSafeSerializer
from pydantic import ValidationError
import pytest

from app.config.settings import settings
from app.constants.notifications import (
    NOTIFICATION_KIND_BRIEFING_DAILY,
    NOTIFICATION_KIND_BRIEFING_WEEKLY,
)
from app.db.repositories.users import user_repository
from app.models.notification.notification_models import NotificationStatus
from app.models.user_models import UserDocument
from app.services.email.models import EmailMessage
from app.utils.notification.channels import email as email_module
from app.utils.notification.channels.email import EmailChannelAdapter
from app.utils.notification.unsubscribe import _SALT

_USER_ID = "user-1"
_UNSUB_SECRET = "test-unsub-secret"
_API_HOST = "https://api.test"


def _expected_unsubscribe_url(user_id: str) -> str:
    """Signed with the production serializer so the assertion proves the two agree."""
    token = URLSafeSerializer(_UNSUB_SECRET, salt=_SALT).dumps(user_id)
    return f"{_API_HOST}/api/v1/notifications/unsubscribe?token={token}"


_BRIEF_PAYLOAD: dict[str, Any] = {
    "kicker": "THE MORNING BRIEF",
    "date": "2026-10-13",
    "headline": "Three things today",
    "lede": "A calm morning.",
    "sections": [
        {
            "numeral": "I",
            "title": "NEEDS YOU",
            "items": [{"text": "Approve it", "todo_id": "t-1", "kind": "you"}],
        }
    ],
    "mood": "clear",
    "caption": "Onward.",
}


@pytest.fixture(autouse=True)
def esp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deliberately not shaped like a real Resend key: the value only has to be set.
    monkeypatch.setattr(settings, "RESEND_API_KEY", "unit-test-esp-key")
    monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", _UNSUB_SECRET)
    monkeypatch.setattr(settings, "EMAIL_FROM", "brief@heygaia.io")
    monkeypatch.setattr(settings, "HOST", _API_HOST)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.test")


@pytest.fixture(autouse=True)
def user_on_file(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    getter = AsyncMock(return_value=UserDocument(id=_USER_ID, email="Test.User@Example.COM"))
    monkeypatch.setattr(user_repository, "get", getter)
    return getter


@pytest.fixture(autouse=True)
def sent(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    send = AsyncMock()
    monkeypatch.setattr(email_module, "send_email", send)
    return send


def _content(
    kind: str | None = None,
    payload: dict[str, Any] | None = None,
    title: str | None = "Reminder",
    body: str | None = "Stand-up in 10 minutes",
) -> dict[str, Any]:
    return {"kind": kind, "payload": payload, "title": title, "body": body}


def _message(send: AsyncMock) -> EmailMessage:
    send.assert_awaited_once()
    (message,) = send.await_args.args
    assert isinstance(message, EmailMessage)
    return message


class TestPreconditions:
    @pytest.mark.parametrize("missing", ["RESEND_API_KEY", "EMAIL_UNSUBSCRIBE_SECRET"])
    async def test_unconfigured_esp_skips_without_sending(
        self, monkeypatch: pytest.MonkeyPatch, sent: AsyncMock, missing: str
    ) -> None:
        monkeypatch.setattr(settings, missing, None)

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped
        assert "not configured" in (status.error_message or "")
        sent.assert_not_awaited()

    async def test_user_without_an_email_is_skipped(
        self, user_on_file: AsyncMock, sent: AsyncMock
    ) -> None:
        user_on_file.return_value = UserDocument(id=_USER_ID, email=None)

        status = await EmailChannelAdapter().deliver(_content(), _USER_ID)

        assert status.skipped
        assert "no email address" in (status.error_message or "")
        sent.assert_not_awaited()


class TestBriefingEmail:
    async def test_daily_brief_is_sent_with_its_headline_and_unsubscribe_headers(
        self, sent: AsyncMock
    ) -> None:
        status = await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        message = _message(sent)
        assert status.status == NotificationStatus.DELIVERED
        assert message.to == ["test.user@example.com"]
        assert message.sender == "GAIA <brief@heygaia.io>"
        assert message.subject == "Three things today"
        assert message.headers == {
            "List-Unsubscribe": f"<{_expected_unsubscribe_url(_USER_ID)}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
        assert 'href="https://app.test/todos?todoId=t-1"' in message.html
        assert "GAIA sends this brief every morning." in message.html

    async def test_weekly_recap_uses_the_weekly_template(self, sent: AsyncMock) -> None:
        await EmailChannelAdapter().deliver(
            _content(kind=NOTIFICATION_KIND_BRIEFING_WEEKLY, payload=_BRIEF_PAYLOAD), _USER_ID
        )

        assert "every Sunday evening" in _message(sent).html

    async def test_briefing_without_its_payload_fails_loud(self, sent: AsyncMock) -> None:
        with pytest.raises(ValidationError):
            await EmailChannelAdapter().deliver(
                _content(kind=NOTIFICATION_KIND_BRIEFING_DAILY, payload=None), _USER_ID
            )
        sent.assert_not_awaited()


class TestPlainNotification:
    async def test_plain_notification_uses_title_as_subject(self, sent: AsyncMock) -> None:
        await EmailChannelAdapter().deliver(_content(), _USER_ID)

        message = _message(sent)
        assert message.subject == "Reminder"
        assert "Stand-up in 10 minutes" in message.html

    async def test_missing_title_falls_back_to_the_product_name(self, sent: AsyncMock) -> None:
        await EmailChannelAdapter().deliver(_content(title=None), _USER_ID)

        assert _message(sent).subject == "GAIA"

    async def test_a_failed_send_propagates_to_the_orchestrator(self, sent: AsyncMock) -> None:
        sent.side_effect = RuntimeError("provider down")

        with pytest.raises(RuntimeError, match="provider down"):
            await EmailChannelAdapter().deliver(_content(), _USER_ID)
