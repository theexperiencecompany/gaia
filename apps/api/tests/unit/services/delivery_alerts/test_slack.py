"""What an incident and one of its failures look like in Slack."""

from datetime import UTC, datetime
from typing import Any

from app.constants.delivery_alerts import DELIVERY_INCIDENT_THREAD_LIMIT, DeliveryFailureKind
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.incidents import Incident
from app.services.delivery_alerts.slack import AlertRecipient, render_incident, render_occurrence

AT = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)
AT_EPOCH = 1792683600
AT_ISO = "2026-10-22T15:40:00+00:00"


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
        assert render_incident(_incident()) == (
            ":rotating_light: *WhatsApp: platform rejected the message*\n"
            "`130497` Business account is restricted from messaging users in this country.\n"
            "*14 failures* · 1 recipient · BR"
            f" · first <!date^{AT_EPOCH}^{{date_short_pretty}} {{time}}|{AT_ISO}>"
            f" · last <!date^{AT_EPOCH}^{{time}}|{AT_ISO}>"
        )

    def test_counts_read_as_singular_only_for_exactly_one(self) -> None:
        def stats(**overrides: Any) -> str:
            return render_incident(_incident(**overrides)).splitlines()[2].split(" · first")[0]

        assert stats(count=1, users=1, countries=()) == "*1 failure* · 1 recipient"
        assert stats(count=2, users=2, countries=()) == "*2 failures* · 2 recipients"

    def test_lists_every_country_the_failures_went_to(self) -> None:
        text = render_incident(_incident(countries=("BR", "PT")))

        assert "· 1 recipient · BR, PT · first" in text

    def test_falls_back_to_the_reason_without_a_platform_code(self) -> None:
        text = render_incident(
            _incident(
                kind=DeliveryFailureKind.SEND_FAILED,
                reason="destination_blocked",
                error_code=None,
                error_message=None,
            )
        )

        assert text.splitlines()[1] == "`destination_blocked`"

    def test_escapes_platform_text_slack_would_read_as_markup(self) -> None:
        text = render_incident(_incident(error_message="<!channel> & friends"))

        assert text.splitlines()[1] == "`130497` &lt;!channel&gt; &amp; friends"

    def test_says_when_the_thread_shows_only_the_first_failures(self) -> None:
        assert "shown in thread" not in render_incident(
            _incident(count=DELIVERY_INCIDENT_THREAD_LIMIT)
        )
        assert render_incident(_incident(count=DELIVERY_INCIDENT_THREAD_LIMIT + 1)).endswith(
            f"\n_First {DELIVERY_INCIDENT_THREAD_LIMIT} shown in thread._"
        )


class TestRenderOccurrence:
    def test_a_linked_user_is_named_by_id_and_email(self) -> None:
        text = render_occurrence(
            _failure(envelope_id="env-1"),
            AlertRecipient(user_id="6ada1f9a85c9a325f548f82f", email="j@example.com"),
        )

        assert text == (
            f"<!date^{AT_EPOCH}^{{time_secs}}|{AT_ISO}>"
            " · user `6ada1f9a85c9a325f548f82f` j@example.com"
            " · BR · envelope `env-1` · message `wamid.X` · via whatsapp-bot"
        )

    def test_never_shows_the_raw_platform_id(self) -> None:
        text = render_occurrence(_failure(), AlertRecipient(user_id=None, email=None))

        assert text == (
            f"<!date^{AT_EPOCH}^{{time_secs}}|{AT_ISO}>"
            " · an unlinked recipient · BR · message `wamid.X` · via whatsapp-bot"
        )

    def test_a_group_channel_is_named_as_one(self) -> None:
        text = render_occurrence(
            _failure(is_channel=True, destination_id="-100999", country=None),
            AlertRecipient(user_id=None, email=None),
        )

        assert text == (
            f"<!date^{AT_EPOCH}^{{time_secs}}|{AT_ISO}>"
            " · a group channel · message `wamid.X` · via whatsapp-bot"
        )
