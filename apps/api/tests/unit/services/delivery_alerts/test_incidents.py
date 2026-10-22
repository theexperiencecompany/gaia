"""Incident grouping in Redis: what one more failure does to its incident."""

from datetime import UTC, datetime

import fakeredis.aioredis

from app.constants.chat import ConversationSource
from app.constants.delivery_alerts import DELIVERY_INCIDENT_QUIET_SECONDS, DeliveryFailureKind
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.incidents import (
    attach_slack_message,
    discard_incident,
    incident_fingerprint,
    read_incident,
    record_occurrence,
)

FIRST = datetime(2026, 10, 22, 15, 40, tzinfo=UTC)
LATER = datetime(2026, 10, 22, 15, 53, tzinfo=UTC)


def _failure(**overrides: object) -> DeliveryFailure:
    fields: dict[str, object] = {
        "platform": ConversationSource.WHATSAPP,
        "kind": DeliveryFailureKind.PLATFORM_REJECTED,
        "reason": "platform_error",
        "error_code": "130497",
        "error_message": "Business account is restricted from messaging users in this country.",
        "destination_id": "5511900000001",
        "country": "BR",
        "occurred_at": FIRST,
        "reporter": "whatsapp-bot",
    }
    return DeliveryFailure.model_validate(fields | overrides)


class TestFingerprint:
    def test_a_platform_error_code_groups_before_the_reason(self) -> None:
        assert incident_fingerprint(_failure()) == "whatsapp:platform_rejected:130497"

    def test_without_a_code_the_reason_groups(self) -> None:
        failure = _failure(
            kind=DeliveryFailureKind.SEND_FAILED, reason="destination_blocked", error_code=None
        )
        assert incident_fingerprint(failure) == "whatsapp:send_failed:destination_blocked"


class TestRecordOccurrence:
    async def test_the_first_failure_opens_an_incident_with_no_slack_message(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        incident = await record_occurrence(fake_redis, _failure())

        assert incident.count == 1
        assert incident.users == 1
        assert incident.countries == ("BR",)
        assert incident.first_at == FIRST
        assert incident.slack_ts is None
        assert incident.error_code == "130497"

    async def test_repeats_to_one_recipient_count_failures_not_people(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_occurrence(fake_redis, _failure())
        incident = await record_occurrence(fake_redis, _failure(occurred_at=LATER))

        assert incident.count == 2
        assert incident.users == 1
        assert incident.first_at == FIRST
        assert incident.last_at == LATER

    async def test_a_linked_user_is_one_person_however_they_were_addressed(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_occurrence(fake_redis, _failure(user_id="u1", destination_id="111"))
        await record_occurrence(fake_redis, _failure(user_id="u1", destination_id="222"))
        incident = await record_occurrence(fake_redis, _failure(user_id="u2"))

        assert incident.users == 2

    async def test_the_incident_closes_after_the_quiet_window(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_occurrence(fake_redis, _failure())

        ttls = [await fake_redis.ttl(key) for key in await fake_redis.keys("delivery_alerts:*")]
        assert ttls
        assert all(0 < ttl <= DELIVERY_INCIDENT_QUIET_SECONDS for ttl in ttls)


class TestSlackMessageBookkeeping:
    async def test_the_parent_message_is_remembered_for_later_failures(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_occurrence(fake_redis, _failure())
        await attach_slack_message(fake_redis, "whatsapp:platform_rejected:130497", "1700.01")

        incident = await record_occurrence(fake_redis, _failure())

        assert incident.slack_ts == "1700.01"

    async def test_a_discarded_incident_reopens_on_the_next_failure(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        await record_occurrence(fake_redis, _failure())
        await record_occurrence(fake_redis, _failure())

        await discard_incident(fake_redis, "whatsapp:platform_rejected:130497")

        assert await read_incident(fake_redis, "whatsapp:platform_rejected:130497") is None
        reopened = await record_occurrence(fake_redis, _failure())
        assert reopened.count == 1
