"""From one reported failure to what lands in Slack.

Real incident state (fakeredis behind redis_cache); faked seams only: the Slack
client, the user repository, the distributed lock and the ARQ enqueue.
"""

from collections.abc import AsyncIterator
import contextlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from tests.helpers import captured_wide_event

from app.constants.delivery_alerts import (
    DELIVERY_INCIDENT_REFRESH_SECONDS,
    DELIVERY_INCIDENT_THREAD_LIMIT,
    RECORD_DELIVERY_FAILURE_TASK,
    REFRESH_DELIVERY_INCIDENT_TASK,
)
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts import alerting
from app.services.delivery_alerts.incidents import Incident
from app.services.delivery_alerts.reporting import queue_delivery_failure, report_delivery_failure
from app.services.delivery_alerts.slack import AlertRecipient
from app.workers.tasks.delivery_alert_tasks import record_delivery_failure

FINGERPRINT = "whatsapp:platform_rejected:130497"


class FakeSlack:
    """Records what would have been posted; post_incident can be made to fail."""

    def __init__(self) -> None:
        self.parents: list[Incident] = []
        self.replies: list[tuple[str, DeliveryFailure, AlertRecipient]] = []
        self.updates: list[tuple[Incident, str]] = []
        self.fail_parent = False

    async def post_incident(self, incident: Incident) -> str:
        if self.fail_parent:
            raise RuntimeError("slack unavailable")
        self.parents.append(incident)
        return f"ts-{len(self.parents)}"

    async def update_incident(self, incident: Incident, ts: str) -> None:
        self.updates.append((incident, ts))

    async def post_occurrence(
        self, ts: str, failure: DeliveryFailure, recipient: AlertRecipient
    ) -> None:
        self.replies.append((ts, failure, recipient))


class FakeLock:
    held = True

    def __init__(self, key: str, **_timing: float) -> None:
        self.key = key

    @contextlib.asynccontextmanager
    async def hold(self) -> AsyncIterator[bool]:
        yield FakeLock.held


def _failure(**overrides: object) -> DeliveryFailure:
    fields: dict[str, object] = {
        "platform": "whatsapp",
        "kind": "platform_rejected",
        "reason": "platform_error",
        "error_code": "130497",
        "destination_id": "5511900000001",
        "country": "BR",
        "occurred_at": datetime(2026, 10, 22, 15, 40, tzinfo=UTC),
        "reporter": "whatsapp-bot",
    }
    return DeliveryFailure.model_validate(fields | overrides)


@pytest.fixture
def slack() -> FakeSlack:
    return FakeSlack()


@pytest.fixture
def enqueue() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def platform_lookup() -> AsyncMock:
    return AsyncMock(return_value=MagicMock(id="6ada1f9a85c9a325f548f82f", email="j@example.com"))


@pytest.fixture(autouse=True)
def _seams(
    fake_redis: fakeredis.aioredis.FakeRedis,
    slack: FakeSlack,
    enqueue: AsyncMock,
    platform_lookup: AsyncMock,
) -> Any:
    FakeLock.held = True
    with (
        patch.object(alerting, "get_delivery_alerts_slack", AsyncMock(return_value=slack)),
        patch.object(alerting, "DistributedLock", FakeLock),
        patch.object(alerting.user_repository, "get_by_platform_id", platform_lookup),
        patch.object(alerting.RedisPoolManager, "get_pool", AsyncMock()),
        patch.object(alerting, "enqueue_worker_job", enqueue),
    ):
        yield


class TestAlertDeliveryFailure:
    async def test_the_first_failure_posts_the_incident_and_its_first_reply(
        self, slack: FakeSlack
    ) -> None:
        await alerting.alert_delivery_failure(_failure())

        assert [p.count for p in slack.parents] == [1]
        ((ts, failure, recipient),) = slack.replies
        assert ts == "ts-1"
        assert failure.user_id == "6ada1f9a85c9a325f548f82f"
        assert recipient == AlertRecipient(
            user_id="6ada1f9a85c9a325f548f82f", email="j@example.com"
        )

    async def test_later_failures_thread_under_the_same_incident(self, slack: FakeSlack) -> None:
        for _ in range(3):
            await alerting.alert_delivery_failure(_failure())

        assert len(slack.parents) == 1
        assert [ts for ts, _, _ in slack.replies] == ["ts-1"] * 3

    async def test_past_the_thread_limit_failures_are_only_counted(self, slack: FakeSlack) -> None:
        for _ in range(DELIVERY_INCIDENT_THREAD_LIMIT + 3):
            await alerting.alert_delivery_failure(_failure())

        assert len(slack.replies) == DELIVERY_INCIDENT_THREAD_LIMIT

    async def test_a_different_cause_opens_its_own_incident(self, slack: FakeSlack) -> None:
        await alerting.alert_delivery_failure(_failure())
        await alerting.alert_delivery_failure(_failure(error_code="131047"))

        assert len(slack.parents) == 2

    async def test_a_channel_destination_is_not_looked_up_as_a_user(
        self, slack: FakeSlack, platform_lookup: AsyncMock
    ) -> None:
        await alerting.alert_delivery_failure(_failure(is_channel=True, destination_id="-100999"))

        platform_lookup.assert_not_awaited()
        assert slack.replies[0][2] == AlertRecipient(user_id=None, email=None)

    async def test_a_parent_slack_could_not_post_is_retried_by_the_next_failure(
        self, slack: FakeSlack
    ) -> None:
        slack.fail_parent = True
        with pytest.raises(RuntimeError, match="slack unavailable"):
            await alerting.alert_delivery_failure(_failure())

        slack.fail_parent = False
        await alerting.alert_delivery_failure(_failure())

        assert [p.count for p in slack.parents] == [1]

    async def test_refuses_to_run_unlocked(self, slack: FakeSlack) -> None:
        FakeLock.held = False

        with pytest.raises(RuntimeError, match="lock not acquired"):
            await alerting.alert_delivery_failure(_failure())

        assert slack.parents == []

    async def test_schedules_one_refresh_at_the_end_of_the_current_bucket(
        self, enqueue: AsyncMock
    ) -> None:
        await alerting.alert_delivery_failure(_failure())

        (_, task, fingerprint), kwargs = enqueue.await_args
        assert (task, fingerprint) == (REFRESH_DELIVERY_INCIDENT_TASK, FINGERPRINT)
        bucket_end = kwargs["_defer_until"].timestamp()
        assert bucket_end % DELIVERY_INCIDENT_REFRESH_SECONDS == 0
        assert kwargs["_job_id"].startswith(f"delivery_alerts:refresh:{FINGERPRINT}:")

    async def test_unconfigured_slack_is_a_warning_not_silence(self) -> None:
        with patch.object(alerting, "get_delivery_alerts_slack", AsyncMock(return_value=None)):
            async with captured_wide_event() as event:
                await alerting.alert_delivery_failure(_failure())

        assert any("not configured" in w["msg"] for w in event["warnings"])


class TestRefreshDeliveryIncident:
    async def test_re_renders_the_parent_with_the_current_count(self, slack: FakeSlack) -> None:
        for _ in range(3):
            await alerting.alert_delivery_failure(_failure())

        await alerting.refresh_delivery_incident(FINGERPRINT)

        ((incident, ts),) = slack.updates
        assert (incident.count, ts) == (3, "ts-1")

    async def test_a_closed_incident_is_left_alone(self, slack: FakeSlack) -> None:
        await alerting.refresh_delivery_incident(FINGERPRINT)

        assert slack.updates == []


class TestReportingToTheWorker:
    async def test_a_queued_failure_reaches_the_task_unchanged(self, slack: FakeSlack) -> None:
        enqueue = AsyncMock()
        with (
            patch("app.services.delivery_alerts.reporting.RedisPoolManager.get_pool", AsyncMock()),
            patch("app.services.delivery_alerts.reporting.enqueue_worker_job", enqueue),
        ):
            await queue_delivery_failure(_failure(envelope_id="env-1"))

        (_, task, payload), _ = enqueue.await_args
        assert task == RECORD_DELIVERY_FAILURE_TASK
        await record_delivery_failure({}, payload)
        assert slack.replies[0][1].envelope_id == "env-1"

    async def test_a_failure_that_cannot_be_queued_is_logged_not_raised(self) -> None:
        with patch(
            "app.services.delivery_alerts.reporting.queue_delivery_failure",
            AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            async with captured_wide_event() as event:
                await report_delivery_failure(_failure(envelope_id="env-1"))

        (error,) = event["errors"]
        assert error["msg"] == "delivery failure could not be queued for alerting"
        assert error["envelope_id"] == "env-1"
