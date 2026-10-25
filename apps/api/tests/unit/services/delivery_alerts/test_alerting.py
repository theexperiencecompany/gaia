"""From one reported failure to what lands in Slack.

Real incident state (fakeredis behind redis_cache); faked seams only: the Slack
client, the user repository, the distributed lock and the ARQ enqueue.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
import contextlib
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from tests.helpers import captured_wide_event
import time_machine

from app.constants.delivery_alerts import (
    DELIVERY_INCIDENT_LOCK_ACQUIRE_SECONDS,
    DELIVERY_INCIDENT_LOCK_LEASE_SECONDS,
    DELIVERY_INCIDENT_LOCK_MAX_HOLD_SECONDS,
    DELIVERY_INCIDENT_LOCK_RENEW_SECONDS,
    DELIVERY_INCIDENT_THREAD_LIMIT,
    RECORD_DELIVERY_FAILURE_TASK,
    REFRESH_DELIVERY_INCIDENT_TASK,
)
from app.db.redis import redis_cache
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts import alerting
from app.services.delivery_alerts.incidents import Incident, record_occurrence
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
    made: ClassVar[list["FakeLock"]] = []

    def __init__(self, key: str, **timing: float) -> None:
        self.key = key
        self.timing = timing
        FakeLock.made.append(self)

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


@pytest.fixture
def pool() -> MagicMock:
    return MagicMock(name="arq-pool")


@pytest.fixture(autouse=True)
def _seams(
    fake_redis: fakeredis.aioredis.FakeRedis,
    slack: FakeSlack,
    enqueue: AsyncMock,
    platform_lookup: AsyncMock,
    pool: MagicMock,
) -> Iterator[None]:
    FakeLock.held = True
    FakeLock.made = []
    with (
        patch.object(alerting, "get_delivery_alerts_slack", AsyncMock(return_value=slack)),
        patch.object(alerting, "DistributedLock", FakeLock),
        patch.object(alerting.user_repository, "get_by_platform_id", platform_lookup),
        patch.object(alerting.RedisPoolManager, "get_pool", AsyncMock(return_value=pool)),
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

    async def test_a_platform_recipient_is_looked_up_by_platform_and_destination(
        self, platform_lookup: AsyncMock
    ) -> None:
        await alerting.alert_delivery_failure(_failure())

        platform_lookup.assert_awaited_once_with("whatsapp", "5511900000001")

    async def test_a_known_user_is_alerted_with_their_email(self, slack: FakeSlack) -> None:
        get_user = AsyncMock(return_value=MagicMock(email="k@example.com"))
        with patch("app.services.delivery_alerts.alerting.user_repository.get", get_user):
            await alerting.alert_delivery_failure(_failure(user_id="user-9"))

        get_user.assert_awaited_once_with("user-9")
        assert slack.replies[0][2] == AlertRecipient(user_id="user-9", email="k@example.com")

    async def test_a_user_id_with_no_account_is_alerted_without_an_email(
        self, slack: FakeSlack
    ) -> None:
        with patch(
            "app.services.delivery_alerts.alerting.user_repository.get",
            AsyncMock(return_value=None),
        ):
            await alerting.alert_delivery_failure(_failure(user_id="user-9"))

        assert slack.replies[0][2] == AlertRecipient(user_id="user-9", email=None)

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

    async def test_locks_the_incident_with_its_own_key_and_timing(self) -> None:
        await alerting.alert_delivery_failure(_failure())

        ((lock_key, timing),) = [(lock.key, lock.timing) for lock in FakeLock.made]
        assert lock_key == f"delivery_alerts:incident:{FINGERPRINT}:lock"
        assert timing == {
            "lease_seconds": DELIVERY_INCIDENT_LOCK_LEASE_SECONDS,
            "acquire_timeout_seconds": DELIVERY_INCIDENT_LOCK_ACQUIRE_SECONDS,
            "renew_seconds": DELIVERY_INCIDENT_LOCK_RENEW_SECONDS,
            "max_hold_seconds": DELIVERY_INCIDENT_LOCK_MAX_HOLD_SECONDS,
        }

    async def test_refuses_to_run_unlocked(self, slack: FakeSlack) -> None:
        FakeLock.held = False

        with pytest.raises(RuntimeError, match="lock not acquired"):
            await alerting.alert_delivery_failure(_failure())

        assert slack.parents == []

    @time_machine.travel(datetime(2026, 10, 22, 15, 40, 10, tzinfo=UTC), tick=False)
    async def test_schedules_one_refresh_at_the_end_of_the_current_bucket(
        self, enqueue: AsyncMock, pool: MagicMock
    ) -> None:
        await alerting.alert_delivery_failure(_failure())

        bucket = int(datetime(2026, 10, 22, 15, 40, tzinfo=UTC).timestamp()) // 30
        enqueue.assert_awaited_once_with(
            pool,
            REFRESH_DELIVERY_INCIDENT_TASK,
            FINGERPRINT,
            _job_id=f"delivery_alerts:refresh:{FINGERPRINT}:{bucket}",
            _defer_until=datetime(2026, 10, 22, 15, 40, 30, tzinfo=UTC),
            _expires=timedelta(seconds=120),
        )

    async def test_the_wide_event_names_the_failure_and_its_incident(self) -> None:
        async with captured_wide_event() as event:
            await alerting.alert_delivery_failure(_failure(envelope_id="env-1"))

        assert event["delivery_failure"] == {
            "platform": "whatsapp",
            "kind": "platform_rejected",
            "reason": "platform_error",
            "error_code": "130497",
            "reporter": "whatsapp-bot",
            "envelope_id": "env-1",
            "user_id": "6ada1f9a85c9a325f548f82f",
        }
        assert event["delivery_incident"] == {"fingerprint": FINGERPRINT, "count": 1}

    async def test_unconfigured_slack_is_a_warning_not_silence(self) -> None:
        with patch.object(alerting, "get_delivery_alerts_slack", AsyncMock(return_value=None)):
            async with captured_wide_event() as event:
                await alerting.alert_delivery_failure(_failure())

        assert event["warnings"] == [
            {
                "msg": "delivery failure not posted: Slack delivery alerts are not configured",
                "platform": "whatsapp",
                "kind": "platform_rejected",
            }
        ]


class TestRefreshDeliveryIncident:
    async def test_re_renders_the_parent_with_the_current_count(self, slack: FakeSlack) -> None:
        for _ in range(3):
            await alerting.alert_delivery_failure(_failure())

        async with captured_wide_event() as event:
            await alerting.refresh_delivery_incident(FINGERPRINT)

        ((incident, ts),) = slack.updates
        assert (incident.count, ts) == (3, "ts-1")
        assert event["delivery_incident"] == {"fingerprint": FINGERPRINT, "count": 3}

    async def test_a_closed_incident_is_left_alone(self, slack: FakeSlack) -> None:
        async with captured_wide_event() as event:
            await alerting.refresh_delivery_incident(FINGERPRINT)

        assert slack.updates == []
        assert event["delivery_incident"] == {"fingerprint": FINGERPRINT, "state": "closed"}

    async def test_an_incident_not_yet_in_slack_is_left_alone(self, slack: FakeSlack) -> None:
        await record_occurrence(redis_cache.client, _failure())

        async with captured_wide_event() as event:
            await alerting.refresh_delivery_incident(FINGERPRINT)

        assert slack.updates == []
        assert event["delivery_incident"] == {"fingerprint": FINGERPRINT, "state": "unposted"}


class TestReportingToTheWorker:
    async def test_a_queued_failure_reaches_the_task_unchanged(
        self, slack: FakeSlack, pool: MagicMock
    ) -> None:
        enqueue = AsyncMock()
        with (
            patch(
                "app.services.delivery_alerts.reporting.RedisPoolManager.get_pool",
                AsyncMock(return_value=pool),
            ),
            patch("app.services.delivery_alerts.reporting.enqueue_worker_job", enqueue),
        ):
            await queue_delivery_failure(_failure(envelope_id="env-1"))

        (queued_on, task, payload), _ = enqueue.await_args
        assert (queued_on, task) == (pool, RECORD_DELIVERY_FAILURE_TASK)
        await record_delivery_failure({}, payload)
        assert slack.replies[0][1].envelope_id == "env-1"

    async def test_a_failure_that_cannot_be_queued_is_logged_not_raised(self) -> None:
        failure = _failure(envelope_id="env-1", user_id="user-9")
        queue = AsyncMock(side_effect=ConnectionError("redis down"))
        with patch("app.services.delivery_alerts.reporting.queue_delivery_failure", queue):
            async with captured_wide_event() as event:
                await report_delivery_failure(failure)

        queue.assert_awaited_once_with(failure)
        assert event["errors"] == [
            {
                "msg": "delivery failure could not be queued for alerting",
                "platform": "whatsapp",
                "kind": "platform_rejected",
                "reason": "platform_error",
                "error_code": "130497",
                "user_id": "user-9",
                "envelope_id": "env-1",
                "error": "redis down",
                "error_type": "ConnectionError",
            }
        ]

    async def test_a_stalled_redis_is_cut_off_for_every_caller(self) -> None:
        async def stall(*_args: object, **_kwargs: object) -> None:
            await asyncio.Event().wait()

        with (
            patch("app.services.delivery_alerts.reporting.RedisPoolManager.get_pool", AsyncMock()),
            patch("app.services.delivery_alerts.reporting.enqueue_worker_job", stall),
            patch(
                "app.services.delivery_alerts.reporting.DELIVERY_FAILURE_QUEUE_TIMEOUT_SECONDS",
                0.01,
            ),
            pytest.raises(TimeoutError),
        ):
            await queue_delivery_failure(_failure())
