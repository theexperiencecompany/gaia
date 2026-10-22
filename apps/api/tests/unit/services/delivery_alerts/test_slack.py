"""What an incident and one of its failures look like in Slack."""

from datetime import UTC, datetime
from typing import Any

from app.constants.delivery_alerts import DELIVERY_INCIDENT_THREAD_LIMIT, DeliveryFailureKind
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.incidents import Incident
from app.services.delivery_alerts.slack import AlertRecipient, render_incident, render_occurrence

AT = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)


_BASE_INCIDENT = Incident(
    fingerprint="whatsapp:platform_rejected:130497",
    platform="whatsapp",
    kind=DeliveryFailureKind.PLATFORM_REJECTED,
    reason="platform_error",
    error_code="130497",
    error_message="Business account is restricted from messaging users in this country.",
    count=14,
    users=1,
    countries=("BR",),
    first_at=AT,
    last_at=AT,
    slack_ts=None,
)


def _incident(**overrides: Any) -> Incident:
    return _BASE_INCIDENT.model_copy(update=overrides)


def _failure(**overrides: object) -> DeliveryFailure:
    fields: dict[str, object] = {
        "platform": "whatsapp",
        "kind": "platform_rejected",
        "reason": "platform_error",
        "destination_id": "5511900000001",
        "country": "BR",
        "platform_message_id": "wamid.X",
        "occurred_at": AT,
        "reporter": "whatsapp-bot",
    }
    return DeliveryFailure.model_validate(fields | overrides)


class TestRenderIncident:
    def test_names_the_platform_the_failure_and_the_platform_error(self) -> None:
        text = render_incident(_incident())

        assert "*WhatsApp: platform rejected the message*" in text
        assert "`130497` Business account is restricted" in text
        assert "*14 failures*" in text
        assert "1 recipient" in text
        assert "BR" in text

    def test_falls_back_to_the_reason_without_a_platform_code(self) -> None:
        text = render_incident(
            _incident(
                kind=DeliveryFailureKind.SEND_FAILED,
                reason="destination_blocked",
                error_code=None,
                error_message=None,
            )
        )

        assert "`destination_blocked`" in text

    def test_escapes_platform_text_slack_would_read_as_markup(self) -> None:
        text = render_incident(_incident(error_message="<!channel> & friends"))

        assert "&lt;!channel&gt; &amp; friends" in text
        assert "<!channel>" not in text

    def test_says_when_the_thread_shows_only_the_first_failures(self) -> None:
        assert "shown in thread" not in render_incident(
            _incident(count=DELIVERY_INCIDENT_THREAD_LIMIT)
        )
        assert f"_First {DELIVERY_INCIDENT_THREAD_LIMIT} shown in thread._" in render_incident(
            _incident(count=DELIVERY_INCIDENT_THREAD_LIMIT + 1)
        )


class TestRenderOccurrence:
    def test_a_linked_user_is_named_by_id_and_email(self) -> None:
        text = render_occurrence(
            _failure(), AlertRecipient(user_id="6ada1f9a85c9a325f548f82f", email="j@example.com")
        )

        assert "user `6ada1f9a85c9a325f548f82f` j@example.com" in text
        assert "message `wamid.X`" in text
        assert "via whatsapp-bot" in text

    def test_never_shows_the_raw_platform_id(self) -> None:
        text = render_occurrence(_failure(), AlertRecipient(user_id=None, email=None))

        assert "an unlinked recipient" in text
        assert "5511900000001" not in text

    def test_a_group_channel_is_named_as_one(self) -> None:
        text = render_occurrence(
            _failure(is_channel=True, destination_id="-100999"),
            AlertRecipient(user_id=None, email=None),
        )

        assert "a group channel" in text
