"""Unit tests for the platform email delivery path.

Covers what test_email_senders.py does not: the Resend adapter itself
(provider-level params), the service delegation + real template rendering,
and the support/pro senders (per-recipient isolation).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.support_models import SupportEmailNotification, SupportRequestType
from app.services.email.models import EmailMessage
from app.services.email.providers.resend_provider import ResendEmailProvider
from app.services.email.service import render_email_template, send_email

SERVICE_MOD = "app.services.email.service"
SENDERS_MOD = "app.services.email.senders"
PROVIDER_MOD = "app.services.email.providers.resend_provider"

SUPPORT_EMAIL = "support@heygaia.io"


def _support_notification(**overrides: object) -> SupportEmailNotification:
    data: dict[str, object] = {
        "user_name": "Alice",
        "user_email": "alice@example.com",
        "ticket_id": "TKT-1",
        "type": SupportRequestType.SUPPORT,
        "title": "Cannot log in",
        "description": "It says invalid credentials",
        "created_at": datetime.now(UTC),
        "support_emails": [SUPPORT_EMAIL],
        "attachments": [],
    }
    data.update(overrides)
    return SupportEmailNotification(**data)


@pytest.fixture
def mock_resend():
    """Fresh Resend module seams per test — call-history isolation matters.

    The credential-store resolver is bound to a stored key so no test touches
    Mongo; the provider applies it before every send/contact call.
    """
    with (
        patch(f"{PROVIDER_MOD}.settings") as m_settings,
        patch(f"{PROVIDER_MOD}.resend.Emails.send", new_callable=MagicMock) as m_send,
        patch(f"{PROVIDER_MOD}.resend.Contacts.create", new_callable=MagicMock) as m_contact,
        patch(
            f"{PROVIDER_MOD}.resolve_resend_config",
            new=AsyncMock(
                return_value={"api_key": "re-stored", "base_url": None, "model": None, "preset": None}
            ),
        ),
    ):
        m_settings.RESEND_API_KEY = "re_fake"
        m_settings.RESEND_AUDIENCE_ID = ""
        yield m_settings, m_send, m_contact


class TestResendProviderSend:
    async def test_sends_full_params(self, mock_resend):
        m_settings, m_send, m_contact = mock_resend
        provider = ResendEmailProvider()

        await provider.send(
            EmailMessage(
                sender="GAIA <no-reply@heygaia.io>",
                to=["alice@example.com"],
                subject="Hello",
                html="<p>hi</p>",
                reply_to="support@heygaia.io",
            )
        )

        params = m_send.call_args[0][0]
        assert params["from"] == "GAIA <no-reply@heygaia.io>"
        assert params["to"] == ["alice@example.com"]
        assert params["subject"] == "Hello"
        assert params["html"] == "<p>hi</p>"
        assert params["reply_to"] == "support@heygaia.io"

    async def test_omits_reply_to_when_unset(self, mock_resend):
        m_settings, m_send, m_contact = mock_resend
        provider = ResendEmailProvider()

        await provider.send(EmailMessage(sender="s", to=["a@example.com"], subject="t", html="h"))

        params = m_send.call_args[0][0]
        assert "reply_to" not in params

    async def test_failure_propagates(self, mock_resend):
        m_settings, m_send, m_contact = mock_resend
        m_send.side_effect = RuntimeError("resend down")
        provider = ResendEmailProvider()

        with pytest.raises(RuntimeError, match="resend down"):
            await provider.send(
                EmailMessage(sender="s", to=["a@example.com"], subject="t", html="h")
            )

    async def test_audience_opt_in_splits_name(self, mock_resend):
        m_settings, m_send, m_contact = mock_resend
        m_settings.RESEND_AUDIENCE_ID = "aud-1"
        provider = ResendEmailProvider()

        await provider.add_contact("alice@example.com", "Alice Marie Smith")

        params = m_contact.call_args[0][0]
        assert params["email"] == "alice@example.com"
        assert params["first_name"] == "Alice"
        assert params["last_name"] == "Marie Smith"
        assert params["unsubscribed"] is False
        assert params["audience_id"] == "aud-1"

    async def test_add_contact_noop_without_audience(self, mock_resend):
        m_settings, m_send, m_contact = mock_resend
        provider = ResendEmailProvider()

        await provider.add_contact("alice@example.com")

        m_contact.assert_not_called()


class TestServiceDelegation:
    async def test_send_email_delegates_to_provider(self):
        provider = AsyncMock()
        with patch(f"{SERVICE_MOD}.get_email_provider", return_value=provider):
            await send_email(EmailMessage(sender="s", to=["a@example.com"], subject="t", html="h"))

        message = provider.send.await_args.args[0]
        assert message.to == ["a@example.com"]
        assert message.subject == "t"

    async def test_send_email_failure_propagates(self):
        provider = AsyncMock()
        provider.send.side_effect = RuntimeError("provider down")
        with patch(f"{SERVICE_MOD}.get_email_provider", return_value=provider):
            with pytest.raises(RuntimeError, match="provider down"):
                await send_email(
                    EmailMessage(sender="s", to=["a@example.com"], subject="t", html="h")
                )

    def test_renders_real_template(self):
        html = render_email_template(
            "welcome.html",
            user_name="Alice",
            contact_email="aryan@heygaia.io",
            discord_url="https://discord.heygaia.io",
            whatsapp_url="https://whatsapp.heygaia.io",
            twitter_url="https://twitter.com/trygaia",
        )

        assert "Alice" in html
        assert "aryan@heygaia.io" in html

    def test_template_renders_without_optional_name(self):
        html = render_email_template(
            "welcome.html",
            user_name=None,
            contact_email="aryan@heygaia.io",
            discord_url="d",
            whatsapp_url="w",
            twitter_url="t",
        )

        assert "Hey" in html


class TestSendSupportTeamNotification:
    async def test_sends_to_every_support_email(self):
        with (
            patch(f"{SENDERS_MOD}.send_email", new_callable=AsyncMock) as m_send,
            patch(
                f"{SENDERS_MOD}.render_email_template", return_value="<h1>ticket</h1>"
            ) as m_render,
        ):
            from app.services.email.senders import send_support_team_notification

            await send_support_team_notification(
                _support_notification(support_emails=["support@a.io", "ops@a.io"])
            )

        assert m_send.await_count == 2
        m_render.assert_called_once()
        assert m_render.call_args.args[0] == "support_to_admin.html"

    async def test_message_contract(self):
        with (
            patch(f"{SENDERS_MOD}.send_email", new_callable=AsyncMock) as m_send,
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>ticket</h1>"),
        ):
            from app.services.email.senders import send_support_team_notification

            await send_support_team_notification(
                _support_notification(type=SupportRequestType.FEATURE)
            )

        message: EmailMessage = m_send.await_args.args[0]
        assert message.to == [SUPPORT_EMAIL]
        assert message.subject == "[TKT-1] New Feature Request: Cannot log in"
        assert message.reply_to == "alice@example.com"

    async def test_recipient_failure_does_not_block_others(self):
        with (
            patch(
                f"{SENDERS_MOD}.send_email",
                new_callable=AsyncMock,
                side_effect=[RuntimeError("smtp down"), None],
            ) as m_send,
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>ticket</h1>"),
        ):
            from app.services.email.senders import send_support_team_notification

            await send_support_team_notification(
                _support_notification(support_emails=["support@a.io", "ops@a.io"])
            )

        assert m_send.await_count == 2

    async def test_template_failure_propagates(self):
        with (
            patch(f"{SENDERS_MOD}.send_email", new_callable=AsyncMock) as m_send,
            patch(
                f"{SENDERS_MOD}.render_email_template",
                side_effect=RuntimeError("jinja boom"),
            ),
        ):
            from app.services.email.senders import send_support_team_notification

            with pytest.raises(RuntimeError, match="jinja boom"):
                await send_support_team_notification(_support_notification())

        m_send.assert_not_awaited()


class TestSendSupportToUserEmail:
    async def test_confirmation_message_contract(self):
        with (
            patch(f"{SENDERS_MOD}.send_email", new_callable=AsyncMock) as m_send,
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>got it</h1>"),
        ):
            from app.services.email.senders import send_support_to_user_email

            await send_support_to_user_email(_support_notification())

        message: EmailMessage = m_send.await_args.args[0]
        assert message.to == ["alice@example.com"]
        assert message.subject == "[TKT-1] Your support request has been received"
        assert message.reply_to is None

    async def test_failure_propagates(self):
        with (
            patch(
                f"{SENDERS_MOD}.send_email",
                new_callable=AsyncMock,
                side_effect=RuntimeError("down"),
            ),
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>got it</h1>"),
        ):
            from app.services.email.senders import send_support_to_user_email

            with pytest.raises(RuntimeError, match="down"):
                await send_support_to_user_email(_support_notification())


class TestSendProSubscriptionEmail:
    async def test_welcome_message_contract(self):
        with (
            patch(f"{SENDERS_MOD}.send_email", new_callable=AsyncMock) as m_send,
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>welcome pro</h1>"),
        ):
            from app.services.email.senders import send_pro_subscription_email

            await send_pro_subscription_email("Alice", "alice@example.com")

        message: EmailMessage = m_send.await_args.args[0]
        assert message.to == ["alice@example.com"]
        assert message.subject == "Welcome to GAIA Pro! 🚀"
        assert message.reply_to == "aryan@heygaia.io"
        assert message.html == "<h1>welcome pro</h1>"

    async def test_failure_propagates(self):
        with (
            patch(
                f"{SENDERS_MOD}.send_email",
                new_callable=AsyncMock,
                side_effect=RuntimeError("down"),
            ),
            patch(f"{SENDERS_MOD}.render_email_template", return_value="<h1>welcome pro</h1>"),
        ):
            from app.services.email.senders import send_pro_subscription_email

            with pytest.raises(RuntimeError, match="down"):
                await send_pro_subscription_email("Alice", "alice@example.com")
