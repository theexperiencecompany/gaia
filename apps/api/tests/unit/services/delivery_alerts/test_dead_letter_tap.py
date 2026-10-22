"""Which broker dead-letters alert, and what they say."""

from datetime import UTC, datetime
import json

from pydantic import ValidationError
import pytest

from app.constants.delivery_alerts import DeliveryFailureKind
from app.services.delivery_alerts.dead_letter_tap import dead_letter_failure

DIED_AT = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)
ENVELOPE = json.dumps(
    {"id": "env-1", "platform": "telegram", "destination_id": "-100999", "is_channel": True}
).encode()


def _headers(reason: str, queue: str = "outbound.telegram") -> dict[str, object]:
    return {"x-death": [{"reason": reason, "queue": queue, "count": 1, "time": DIED_AT}]}


class TestDeadLetterFailure:
    def test_an_expired_message_alerts_with_its_envelope(self) -> None:
        failure = dead_letter_failure(_headers("expired"), ENVELOPE)

        assert failure is not None
        assert failure.kind is DeliveryFailureKind.EXPIRED
        assert failure.platform.value == "telegram"
        assert failure.reason == "expired"
        assert failure.envelope_id == "env-1"
        assert failure.destination_id == "-100999"
        assert failure.is_channel is True
        assert failure.occurred_at == DIED_AT

    def test_a_bot_rejection_is_left_to_the_bot_that_reported_it(self) -> None:
        assert dead_letter_failure(_headers("rejected"), ENVELOPE) is None

    def test_an_unreadable_message_still_alerts_without_a_recipient(self) -> None:
        failure = dead_letter_failure(_headers("maxlen"), b"{ not json")

        assert failure is not None
        assert failure.destination_id is None
        assert failure.reason == "maxlen"

    def test_a_message_from_another_queue_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="not an outbound work queue"):
            dead_letter_failure(_headers("expired", queue="websocket.events"), ENVELOPE)

    def test_a_message_without_x_death_is_an_error(self) -> None:
        with pytest.raises(ValidationError, match="x-death"):
            dead_letter_failure({}, ENVELOPE)
