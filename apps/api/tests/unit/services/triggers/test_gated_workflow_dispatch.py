"""A gated workflow at dispatch: a skip lands on its gate and claims, batches and queues nothing.

Inside the user's quiet hours a held workflow is queued for the end of them and
an urgent one is queued now, carrying why it could not wait.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import UTC, datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from arq.connections import ArqRedis
from arq.jobs import JobDef
import fakeredis.aioredis
import httpx
from pymongo.errors import PyMongoError
import pytest
from sentry_sdk.types import Event
import time_machine

from app.constants.trigger_gates import GateAuthor
from app.constants.workflows import WorkflowDelivery
from app.db.redis import redis_cache
from app.models.trigger_configs import GmailPollInboxConfig
from app.models.trigger_gate_models import AuthoredGate, TriggerGate
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.services.triggers.handlers.gmail import GmailTriggerHandler
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from shared.py.analytics.catalog.triggers import TriggerGateDecided
from tests.helpers import captured_wide_event, trigger_gate_seams

pytestmark = pytest.mark.unit

_BASE = "app.services.triggers.base"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
WORKFLOW_ID = "wf_gated000001"
CONDITION = "the email is from a customer about billing"
_GATE = AuthoredGate(condition=CONDITION, author=GateAuthor.GAIA)
KOLKATA = "Asia/Kolkata"
# 14:30 on the user's clock in Kolkata.
AFTERNOON = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


def _workflow(
    gate: TriggerGate | None = _GATE,
    workflow_id: str = WORKFLOW_ID,
    trigger_config: TriggerConfig | None = None,
    trigger_name: str | None = "gmail_new_message",
) -> Workflow:
    return Workflow(
        delivery=WorkflowDelivery.NOW,
        id=workflow_id,
        user_id=USER_ID,
        title="Draft replies",
        description="Draft a reply to mail that needs one",
        steps=[WorkflowStep(title="Draft", description="Draft the reply")],
        trigger_config=trigger_config
        or TriggerConfig(type=TriggerType.INTEGRATION, trigger_name=trigger_name),
        gate=gate,
    )


class _Handler(GmailTriggerHandler):
    """The real Gmail handler, signals and all, with its workflow lookup served in memory."""

    def __init__(self, workflows: list[Workflow]) -> None:
        self._workflows = workflows

    def occurrence_key(self, event_type: str, data: Mapping[str, object]) -> str | None:
        return "occurrence-1"

    async def find_workflows(
        self, event_type: str, trigger_id: str, data: dict[str, object]
    ) -> list[Workflow]:
        return self._workflows


def _gate_answer(not_needed: float) -> dict[str, object]:
    return {
        "type": "choice",
        "choice": "not_needed" if not_needed >= 0.5 else "needed",
        "confidence": max(not_needed, 1 - not_needed),
        "probabilities": {"not_needed": not_needed, "needed": 1 - not_needed},
    }


def _jev_body(not_needed: float) -> dict[str, object]:
    return {"answers": {"gate": _gate_answer(not_needed)}}


def _night_body(*, can_wait: float, not_needed: float = 0.1) -> dict[str, object]:
    """Answer both questions; what is not can_wait leans to a meeting."""
    urgent = {"incident": 0.0, "service_down": 0.0, "meeting": 1 - can_wait, "can_wait": can_wait}
    return {
        "answers": {
            "gate": _gate_answer(not_needed),
            "urgent": {"type": "choice", "choice": "can_wait", "probabilities": urgent},
        }
    }


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    with (
        trigger_gate_seams(Timezone.parse(KOLKATA), now=AFTERNOON) as gate,
        patch(f"{_BASE}.TriggerHandler._queue_todo_dispatch", AsyncMock(return_value=True)),
        patch(f"{_BASE}.get_signal_matching_context", AsyncMock(return_value="")),
        patch(f"{_BASE}._claim_occurrence", AsyncMock(return_value=True)) as claim,
        patch(f"{_BASE}.buffer_trigger_event", AsyncMock(return_value=False)) as buffer,
        patch(f"{_BASE}.WorkflowQueueService.queue_workflow_execution", AsyncMock()) as queue,
    ):
        yield SimpleNamespace(
            jev=gate.jev,
            claim=claim,
            buffer=buffer,
            queue=queue,
            skipped=gate.workflow_skips,
            capture=gate.capture,
            wrote=gate.wrote,
        )


async def _fire(workflows: list[Workflow], **payload: object) -> None:
    data: dict[str, object] = {"thread_id": "t1", "message_id": "t1", "subject": "Sale!", **payload}
    await _Handler(workflows).process_event("GMAIL_NEW_GMAIL_MESSAGE", None, USER_ID, data)


async def test_a_skip_lands_on_the_gate_and_claims_nothing(seams: SimpleNamespace) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))

    await _fire([_workflow()])

    seams.queue.assert_not_awaited()
    seams.buffer.assert_not_awaited()
    # The occurrence stays unclaimed, so a later trigger for the same one still runs.
    seams.claim.assert_not_awaited()
    workflow_id, user_id, skip = seams.skipped.await_args.args
    assert (workflow_id, user_id) == (WORKFLOW_ID, USER_ID)
    assert (skip.event, skip.certainty) == ("Sale!", 0.99)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json=_jev_body(0.90)),
        httpx.Response(500, text="boom"),
        httpx.Response(200, text="garbage"),
    ],
    ids=["unsure", "5xx", "garbage"],
)
async def test_an_unsure_or_failing_gate_queues_as_today(
    seams: SimpleNamespace, response: httpx.Response
) -> None:
    seams.jev.mock(return_value=response)

    await _fire([_workflow()])

    seams.queue.assert_awaited_once()
    seams.skipped.assert_not_awaited()


async def test_a_real_thread_reply_runs_without_asking_jev(seams: SimpleNamespace) -> None:
    await _fire([_workflow()], message_id="m2")

    assert not seams.jev.called
    seams.queue.assert_awaited_once()


async def test_a_reply_on_a_thread_the_user_never_wrote_in_is_asked_about(
    seams: SimpleNamespace,
) -> None:
    seams.wrote.return_value = False
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))

    await _fire([_workflow()], message_id="m2", sender="GitGuardian <security@gitguardian.com>")

    seams.queue.assert_not_awaited()
    (call,) = seams.skipped.await_args_list
    assert call.args[2].event == "GitGuardian · Sale!"


async def test_an_ungated_workflow_never_asks_jev(seams: SimpleNamespace) -> None:
    await _fire([_workflow(gate=None)])

    assert not seams.jev.called
    seams.queue.assert_awaited_once()


async def test_each_matched_workflow_gets_its_own_verdict(seams: SimpleNamespace) -> None:
    other = "the email is a meeting request"

    def answer(request: httpx.Request) -> httpx.Response:
        criteria = json.loads(request.content)["questions"]["gate"]["criteria"]
        return (
            httpx.Response(200, json=_jev_body(0.99))
            if criteria["needed"] == CONDITION
            else httpx.Response(503, text="down")
        )

    seams.jev.mock(side_effect=answer)

    await _fire(
        [
            _workflow(),
            _workflow(AuthoredGate(condition=other, author=GateAuthor.USER), "wf_gated000002"),
        ]
    )

    seams.skipped.assert_awaited_once()
    assert seams.skipped.await_args.args[0] == WORKFLOW_ID
    seams.queue.assert_awaited_once()
    assert seams.queue.await_args.args[0] == "wf_gated000002"


async def test_matched_workflows_are_gated_at_the_same_time(seams: SimpleNamespace) -> None:
    both_asked = asyncio.Event()
    in_flight = most_in_flight = 0

    async def answer(_: httpx.Request) -> httpx.Response:
        nonlocal in_flight, most_in_flight
        in_flight += 1
        most_in_flight = max(most_in_flight, in_flight)
        if in_flight == 2:
            both_asked.set()
        try:
            # A dispatcher that asks one at a time never has the second question in flight.
            await asyncio.wait_for(both_asked.wait(), timeout=1)
        finally:
            in_flight -= 1
        return httpx.Response(200, json=_jev_body(0.1))

    seams.jev.mock(side_effect=answer)

    await _fire([_workflow(), _workflow(workflow_id="wf_gated000002")])

    assert most_in_flight == 2
    assert seams.queue.await_count == 2


@pytest.fixture
async def arq() -> AsyncIterator[ArqRedis]:
    """Serve a real ArqRedis on fakeredis, so a queued run's job and its time are as in production."""
    server = fakeredis.aioredis.FakeRedis()
    pool = ArqRedis(pool_or_conn=server.connection_pool)
    with patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)):
        yield pool
    await server.aclose()


@pytest.fixture
def night(fake_redis: fakeredis.aioredis.FakeRedis, arq: ArqRedis) -> Iterator[SimpleNamespace]:
    """Gate a workflow with the real queue and batch underneath; the test sets the clock."""
    with (
        trigger_gate_seams(Timezone.parse(KOLKATA)) as gate,
        patch(f"{_BASE}.TriggerHandler._queue_todo_dispatch", AsyncMock(return_value=True)),
        patch(f"{_BASE}.get_signal_matching_context", AsyncMock(return_value="")),
        patch(f"{_BASE}._claim_occurrence", AsyncMock(return_value=True)) as claim,
    ):
        yield SimpleNamespace(
            jev=gate.jev, claim=claim, skipped=gate.workflow_skips, arq=arq, redis=fake_redis
        )


async def _fire_at(
    night: SimpleNamespace, workflow: Workflow, *, zone: str, at: datetime
) -> tuple[list[JobDef], list[str]]:
    """Fire one first-of-thread email at a moment, for a user on zone's clock.

    Returns the queue and the workflow's batch, read before the clock moves on:
    their keys expire against wall time.
    """
    with (
        patch(
            "app.services.user_service.get_profile_timezone",
            AsyncMock(return_value=Timezone.parse(zone)),
        ),
        time_machine.travel(at, tick=False),
    ):
        await _fire([workflow])
        batch = await night.redis.lrange(f"trigger_batch:{workflow.id}", 0, -1)
        return await night.arq.queued_jobs(), batch


def _score(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


class TestQuietHours:
    @pytest.mark.parametrize(
        ("zone", "at", "morning"),
        [
            # 00:15 on Oct 2 in Kolkata is still Oct 1 in UTC.
            (KOLKATA, datetime(2026, 10, 1, 18, 45, tzinfo=UTC), datetime(2026, 10, 2, 8)),
            # 23:30 on Oct 1 in Los Angeles is already Oct 2 in UTC.
            (
                "America/Los_Angeles",
                datetime(2026, 10, 2, 6, 30, tzinfo=UTC),
                datetime(2026, 10, 2, 8),
            ),
        ],
        ids=["after-local-midnight", "before-local-midnight"],
    )
    async def test_a_held_workflow_runs_when_the_users_quiet_hours_end(
        self, night: SimpleNamespace, zone: str, at: datetime, morning: datetime
    ) -> None:
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        immediate = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="slack_new_message")

        (job,), (held,) = await _fire_at(
            night, _workflow(trigger_config=immediate), zone=zone, at=at
        )

        assert job.function == "execute_workflow_by_id"
        assert job.score == _score(morning.replace(tzinfo=ZoneInfo(zone)))
        workflow_id, context = job.args
        assert workflow_id == WORKFLOW_ID
        assert context["quiet_hours"] == {"kind": "hold"}
        assert context["trigger_batch_key"] == f"trigger_batch:{WORKFLOW_ID}"
        assert json.loads(held)["message_id"] == "t1"
        # Claimed when held: the event will run, so a second trigger for it must not.
        night.claim.assert_awaited_once()

    async def test_a_held_event_redis_cannot_batch_still_waits_for_the_morning(
        self, night: SimpleNamespace
    ) -> None:
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        immediate = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="slack_new_message")

        with patch.object(redis_cache, "redis", None):
            async with captured_wide_event() as event:
                (job,), _ = await _fire_at(
                    night,
                    _workflow(trigger_config=immediate),
                    zone=KOLKATA,
                    at=datetime(2026, 10, 1, 21, 0, tzinfo=UTC),
                )

        assert job.score == _score(datetime(2026, 10, 2, 8, tzinfo=ZoneInfo(KOLKATA)))
        assert job.args[1]["trigger_data"]["message_id"] == "t1"
        assert {
            "msg": "[TRIGGER] Redis unavailable — trigger event cannot be batched",
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
        } in event["warnings"]

    async def test_a_night_of_events_on_an_unbatched_trigger_is_one_morning_run(
        self, night: SimpleNamespace
    ) -> None:
        """One run per held event would collide on the conversation lock at 08:00 and lose all but one."""
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        immediate = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="slack_new_message")
        workflow = _workflow(trigger_config=immediate)

        with (
            patch(
                "app.services.user_service.get_profile_timezone",
                AsyncMock(return_value=Timezone.parse(KOLKATA)),
            ),
            time_machine.travel(datetime(2026, 10, 1, 21, 0, tzinfo=UTC), tick=False),
        ):
            await _fire([workflow], text="Deploy is done")
            await _fire([workflow], message_id="t2", text="Can you review the PR?")
            batch = await night.redis.lrange(f"trigger_batch:{WORKFLOW_ID}", 0, -1)
            jobs = await night.arq.queued_jobs()

        (job,) = jobs
        assert job.score == _score(datetime(2026, 10, 2, 8, tzinfo=ZoneInfo(KOLKATA)))
        assert job.args[1]["trigger_batch_key"] == f"trigger_batch:{WORKFLOW_ID}"
        assert [json.loads(event)["text"] for event in batch] == [
            "Deploy is done",
            "Can you review the PR?",
        ]

    async def test_a_held_batched_workflow_drains_when_quiet_hours_end(
        self, night: SimpleNamespace
    ) -> None:
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))
        polled = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            trigger_data=GmailPollInboxConfig(interval=15),
        )

        (job,), (held,) = await _fire_at(
            night,
            _workflow(trigger_config=polled),
            zone=KOLKATA,
            at=datetime(2026, 10, 1, 21, 0, tzinfo=UTC),
        )

        assert job.args[1]["trigger_batch_key"] == f"trigger_batch:{WORKFLOW_ID}"
        assert job.score == _score(datetime(2026, 10, 2, 8, tzinfo=ZoneInfo(KOLKATA)))
        assert json.loads(held)["message_id"] == "t1"

    async def test_a_held_email_on_a_daily_batch_drains_that_morning_not_a_day_later(
        self, night: SimpleNamespace
    ) -> None:
        """A per-email workflow batches a day; what it held at 02:30 still drains at 08:00."""
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=1.0)))

        (job,), _ = await _fire_at(
            night, _workflow(), zone=KOLKATA, at=datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
        )

        assert job.score == _score(datetime(2026, 10, 2, 8, tzinfo=ZoneInfo(KOLKATA)))

    async def test_an_urgent_workflow_runs_now_and_says_why(self, night: SimpleNamespace) -> None:
        night.jev.mock(return_value=httpx.Response(200, json=_night_body(can_wait=0.0)))
        at = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)

        (job,), batch = await _fire_at(night, _workflow(), zone=KOLKATA, at=at)

        assert batch == []
        # Not held for its daily batch either: an urgent email cannot wait a day.
        assert job.function == "execute_workflow_by_id"
        assert job.score == _score(at)
        assert job.args[1]["quiet_hours"] == {
            "kind": "bypass",
            "reason": "someone is waiting on you for a meeting happening soon",
        }

    async def test_a_confident_skip_at_night_lands_on_the_gate(
        self, night: SimpleNamespace
    ) -> None:
        body = _night_body(can_wait=1.0, not_needed=0.99)
        night.jev.mock(return_value=httpx.Response(200, json=body))

        jobs, batch = await _fire_at(
            night, _workflow(), zone=KOLKATA, at=datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
        )

        assert (jobs, batch) == ([], [])
        night.skipped.assert_awaited_once()
        night.claim.assert_not_awaited()

    async def test_an_ungated_workflow_runs_at_night_as_by_day(
        self, night: SimpleNamespace
    ) -> None:
        at = datetime(2026, 10, 1, 21, 0, tzinfo=UTC)
        immediate = TriggerConfig(type=TriggerType.INTEGRATION, trigger_name="slack_new_message")

        (job,), _ = await _fire_at(
            night, _workflow(gate=None, trigger_config=immediate), zone=KOLKATA, at=at
        )

        assert not night.jev.called
        assert job.score == _score(at)
        assert "quiet_hours" not in job.args[1]


async def test_the_gate_asks_about_each_workflow_under_its_own_id(seams: SimpleNamespace) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.1)))

    async with captured_wide_event() as event:
        await _fire([_workflow(), _workflow(workflow_id="wf_gated000002")])

    assert set(event["trigger_gate"]) == {WORKFLOW_ID, "wf_gated000002"}
    automations = {json.loads(c.request.content)["state"]["automation"] for c in seams.jev.calls}
    assert automations == {"Draft replies: Draft a reply to mail that needs one"}


async def test_a_workflow_whose_trigger_names_nothing_is_gated_under_the_event(
    seams: SimpleNamespace,
) -> None:
    await _fire([_workflow(trigger_name=None)])

    (decided,) = [c.args[1] for c in seams.capture.call_args_list]
    assert isinstance(decided, TriggerGateDecided)
    assert decided.trigger_name == "GMAIL_NEW_GMAIL_MESSAGE"
    seams.queue.assert_awaited_once()


async def test_the_run_reads_the_signals_derived_from_the_event(seams: SimpleNamespace) -> None:
    await _fire([_workflow(gate=None)])

    trigger_data = seams.queue.await_args.kwargs["context"]["trigger_data"]
    assert trigger_data["continues_thread"] is False


async def test_a_gate_that_crashes_runs_its_workflow_and_spares_the_others(
    seams: SimpleNamespace,
) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))

    with patch(
        "app.services.triggers.trigger_gate.is_trigger_gates_enforced",
        AsyncMock(side_effect=RuntimeError("flag store down")),
    ):
        await _fire([_workflow(), _workflow(gate=None, workflow_id="wf_ungated0001")])

    queued = {c.args[0] for c in seams.queue.await_args_list}
    assert queued == {WORKFLOW_ID, "wf_ungated0001"}
    seams.skipped.assert_not_awaited()


async def test_a_skip_whose_gate_write_fails_is_reported_and_still_skips(
    seams: SimpleNamespace, sentry_events: list[Event]
) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))
    seams.skipped.side_effect = PyMongoError("history down")

    async with captured_wide_event() as event:
        await _fire([_workflow(), _workflow(gate=None, workflow_id="wf_ungated0001")])

    assert [c.args[0] for c in seams.queue.await_args_list] == ["wf_ungated0001"]
    assert event["errors"] == [
        {
            "msg": "trigger_gate.skip_unrecorded",
            "owner": "workflow",
            "job_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "error_type": "PyMongoError",
            "error": "history down",
        }
    ]
    assert [e["exception"]["values"][-1]["type"] for e in sentry_events] == ["PyMongoError"]


async def test_a_workflow_that_fails_to_queue_names_its_trigger(seams: SimpleNamespace) -> None:
    seams.queue.side_effect = RuntimeError("queue down")

    async with captured_wide_event() as event:
        await _Handler([_workflow(gate=None)]).process_event(
            "GMAIL_NEW_GMAIL_MESSAGE",
            "trg_1",
            USER_ID,
            {"thread_id": "t1", "message_id": "t1", "subject": "Sale!"},
        )

    assert [e for e in event["errors"] if e["msg"] == "trigger_workflow_queue_failed"] == [
        {
            "msg": "trigger_workflow_queue_failed",
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "event_type": "GMAIL_NEW_GMAIL_MESSAGE",
            "trigger_id": "trg_1",
            "error_type": "RuntimeError",
            "error": "queue down",
        }
    ]
