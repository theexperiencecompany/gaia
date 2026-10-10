"""The e2e's judgement of what reached PostHog: a clean run passes, and each way a run goes wrong fails it.

The clean events are the ones a real run emitted (2026-10-08, API plus ARQ
worker, captured at a local PostHog sink); every other test corrupts one of
them the way a real regression would.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import fakeredis
import pytest
from scripts.analytics_ops import e2e
from scripts.analytics_ops.e2e_journeys import Stack
from scripts.analytics_ops.posthog_api import ROW_CAP

from app.workers.config.worker_settings import WorkerSettings
from shared.py.analytics import UserId
from tests.unit.scripts.analytics_ops.conftest import FakeReader

USER = "6ac74a19fa5dfaf1f5770471"
SESSION = "6be4c37a-8a72-4bbd-831f-6f793d241c95"
WEB = {"actor": "user", "trigger": "interactive", "surface": "web", "$session_id": SESSION}
WEBHOOK = {"actor": "agent", "trigger": "webhook", "surface": "worker"}
BOT = {"actor": "user", "trigger": "interactive", "surface": "bot"}
# The agent acts in the run tree the user's request started.
AGENT_WEB = {**WEB, "actor": "agent"}
AGENT_BOT = {**BOT, "actor": "agent"}
CONVERSATION = "6d3dbe42-7de8-4f11-a897-fedb2cb44193"
BOT_CONVERSATION = "2014a5eb-fff2-4414-9a74-530e562a9f96"
WORKFLOW_CONVERSATION = "acd858d4-2d9b-46a6-ade1-ca7de0f1ada1"
TURN = {"conversation_id": CONVERSATION, "mode": "interactive", "agent": "comms"}
BOT_TURN = {"conversation_id": BOT_CONVERSATION, "mode": "interactive", "agent": "comms"}
WORKFLOW_RUN = {"conversation_id": WORKFLOW_CONVERSATION, "mode": "background", "agent": "comms"}
COMPLETED = {
    "delegated": False,
    "queued": False,
    "voice_mode": False,
    "ttft_ms": 44.0,
    "e2e_ack_ms": 4.0,
    "e2e_full_ms": 4.0,
}

CLEAN: list[tuple[str, dict[str, object]]] = [
    ("user:active", WEB),
    ("onboarding:completed", {**WEB, "needs": ["inbox"], "has_other_need": False}),
    (
        "chat:conversation_created",
        {**WEB, "is_onboarding_demo": False, "is_system_generated": True},
    ),
    ("onboarding:phase_completed", {**WEB, "phase": "getting_started"}),
    ("paywall:blocked", {**WEB, "feature": "/api/v1/chat-stream"}),
    (
        "subscription:activated",
        {
            **WEBHOOK,
            "subscription_id": "sub_e2e_1",
            "plan_name": "Pro",
            "currency": "USD",
            "amount": 20,
        },
    ),
    ("payment:succeeded", {**WEBHOOK, "payment_id": "pay_e2e_1", "currency": "USD", "amount": 20}),
    (
        "chat:message_submitted",
        {
            **WEB,
            "source": "web",
            "stream_id": "s-web",
            "is_retry": False,
            "has_files": False,
            "is_new_conversation": True,
            "message_count": 1,
        },
    ),
    (
        "chat:conversation_created",
        {**WEB, "is_onboarding_demo": False, "is_system_generated": False},
    ),
    ("chat:conversation_renamed", {**AGENT_WEB, "conversation_id": CONVERSATION}),
    ("agent:run_started", {**AGENT_WEB, **TURN}),
    ("agent:run_completed", {**AGENT_WEB, **TURN}),
    (
        "chat:message_completed",
        {
            **WEB,
            **COMPLETED,
            "conversation_id": CONVERSATION,
            "stream_id": "s-web",
            "source": "web",
            "is_new_conversation": True,
        },
    ),
    (
        "workflow:created",
        {**WEB, "steps_count": 1, "generated_immediately": False, "trigger_type": "manual"},
    ),
    ("workflow:executed", WEB),
    # The ARQ worker's run of that workflow.
    (
        "chat:conversation_created",
        {**AGENT_WEB, "is_system_generated": True, "system_purpose": "workflow_execution"},
    ),
    ("agent:run_started", {**AGENT_WEB, **WORKFLOW_RUN}),
    ("agent:run_completed", {**AGENT_WEB, **WORKFLOW_RUN}),
    (
        "chat:message_submitted",
        {**BOT, "source": "telegram", "stream_id": "s-bot", "is_retry": False, "has_files": False},
    ),
    (
        "chat:conversation_created",
        {**BOT, "is_onboarding_demo": False, "is_system_generated": False},
    ),
    ("agent:run_started", {**AGENT_BOT, **BOT_TURN}),
    ("bot:chat_started", {"message_length": 21, "streaming_enabled": True}),
    ("bot:message_received", {"interaction_type": "chat", "message_length": 21}),
    ("agent:run_completed", {**AGENT_BOT, **BOT_TURN}),
    (
        "chat:message_completed",
        {
            **BOT,
            **COMPLETED,
            "conversation_id": BOT_CONVERSATION,
            "stream_id": "s-bot",
            "source": "telegram",
            "is_new_conversation": False,
        },
    ),
    ("bot:chat_completed", {"duration_ms": 4348, "response_length": 13, "streaming_enabled": True}),
]


def _received(events: list[tuple[str, dict[str, object]]]) -> list[e2e.Received]:
    return [
        e2e.Received(str(i), name, USER, f"t{i}", dict(props))
        for i, (name, props) in enumerate(events)
    ]


def _judge(
    events: list[tuple[str, dict[str, object]]], strays: list[list[object]] | None = None
) -> list[str]:
    stack = Stack(
        api_url="http://unused", email="e2e@gaia.local", session_id=SESSION, user_id=UserId(USER)
    )
    verdict = e2e.Verdict()
    e2e.judge(
        e2e.build_journeys(Path("/dev/null")), _received(events), strays or [], stack, verdict
    )
    return verdict.failures


def _with(index: int, **changes: object) -> list[tuple[str, dict[str, object]]]:
    events = [(name, dict(props)) for name, props in CLEAN]
    events[index][1].update(changes)
    return events


def _index(name: str) -> int:
    return next(i for i, (event, _) in enumerate(CLEAN) if event == name)


def test_the_events_a_real_run_stored_pass() -> None:
    assert _judge(CLEAN) == []


def test_an_event_arriving_twice_fails() -> None:
    failures = _judge([*CLEAN, CLEAN[_index("paywall:blocked")]])

    assert failures == ["paywall: paywall:blocked: arrived 2x, expected 1x"]


def test_a_missing_event_fails() -> None:
    events = [event for event in CLEAN if event[0] != "workflow:executed"]

    assert _judge(events) == ["workflow: workflow:executed: arrived 0x, expected 1x"]


def test_a_browser_event_outside_the_browsers_session_fails() -> None:
    [failure] = _judge(_with(_index("onboarding:completed"), **{"$session_id": "another-tab"}))

    assert failure.startswith("onboarding: onboarding:completed: $session_id 'another-tab'")


def test_a_webhook_event_carrying_a_browser_session_fails() -> None:
    [failure] = _judge(_with(_index("payment:succeeded"), **{"$session_id": SESSION}))

    assert "on an event no browser caused" in failure


def test_a_property_the_catalog_does_not_declare_fails() -> None:
    [failure] = _judge(_with(_index("subscription:activated"), email="someone@example.com"))

    assert (
        failure
        == "payment webhook: subscription:activated: properties not in the catalog: ['email']"
    )


def test_a_property_of_the_wrong_kind_fails_catalog_validation() -> None:
    [failure] = _judge(_with(_index("workflow:created"), steps_count="one"))

    assert failure.startswith("workflow: workflow:created: catalog validation")


@pytest.mark.parametrize(
    ("field", "wrong"), [("actor", "user"), ("trigger", "interactive"), ("surface", "web")]
)
def test_wrong_attribution_on_the_webhook_fails(field: str, wrong: str) -> None:
    [failure] = _judge(_with(_index("payment:succeeded"), **{field: wrong}))

    assert failure.startswith("payment webhook: payment:succeeded: attribution")


def test_a_bot_runtime_event_must_not_carry_server_attribution() -> None:
    [failure] = _judge(_with(_index("bot:message_received"), actor="user"))

    assert failure == "bot message: bot:message_received: properties not in the catalog: ['actor']"


def test_an_event_on_another_distinct_id_fails() -> None:
    events = _received(CLEAN)
    events[_index("payment:succeeded")] = e2e.Received(
        "x", "payment:succeeded", "someone-else", "t", dict(CLEAN[_index("payment:succeeded")][1])
    )
    stack = Stack(
        api_url="http://unused", email="e2e@gaia.local", session_id=SESSION, user_id=UserId(USER)
    )
    verdict = e2e.Verdict()

    e2e.judge(e2e.build_journeys(Path("/dev/null")), events, [], stack, verdict)

    assert "distinct_id 'someone-else', expected the user's Mongo id" in verdict.failures[0]


def test_an_unexpected_catalog_event_on_the_user_fails() -> None:
    failures = _judge([*CLEAN, ("todo:created", WEB)])

    assert failures == [f"unexpected todo:created at t{len(CLEAN)} on {USER}"]


def test_a_stray_event_on_another_distinct_id_fails_and_is_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    failures = _judge(CLEAN, strays=[["chat:message_submitted", "telegram:dev-1", 1]])

    message = "unexpected chat:message_submitted x1 on another distinct_id 'telegram:dev-1'"
    assert failures == [message]
    assert f"  XX {message}" in capsys.readouterr().out.splitlines()


def test_sdk_person_operations_are_not_judged() -> None:
    assert _judge([*CLEAN, ("$set", {}), ("$ai_generation", {"$ai_model": "stub"})]) == []


def test_two_journeys_expecting_the_same_event_each_need_their_own() -> None:
    first_created = _index("chat:conversation_created")
    events = [event for i, event in enumerate(CLEAN) if i != first_created]

    assert _judge(events) == [
        "onboarding: chat:conversation_created [surface=web, is_system_generated=True, "
        "system_purpose=None]: arrived 0x, expected 1x"
    ]


def test_a_query_that_fills_the_row_cap_stops_the_run() -> None:
    reader = FakeReader({e2e.RUN_EVENTS_HOGQL: [["u", "e", USER, "t", "{}"]] * ROW_CAP})
    stack = Stack(api_url="http://unused", email="e", session_id=SESSION, user_id=UserId(USER))

    with pytest.raises(SystemExit, match="partial"):
        e2e.fetch(reader, stack, e2e.datetime.now(e2e.UTC))


def test_a_workflow_run_the_worker_never_finished_fails() -> None:
    events = [event for event in CLEAN if event[1].get("conversation_id") != WORKFLOW_CONVERSATION]

    assert _judge(events) == [
        "workflow: agent:run_started [surface=web, mode=background]: arrived 0x, expected 1x",
        "workflow: agent:run_completed [surface=web, mode=background]: arrived 0x, expected 1x",
    ]


def test_a_user_attributed_agent_run_fails() -> None:
    [failure] = _judge(_with(_index("agent:run_started"), actor="user"))

    assert failure.startswith(
        "web chat turn: agent:run_started [surface=web, mode=interactive]: attribution"
    )


class TestWaitForWorker:
    def test_a_healthy_worker_lets_the_run_drive(self) -> None:
        client = fakeredis.FakeRedis()
        client.set(WorkerSettings.health_check_key, "ok")

        e2e.wait_for_worker(client, timeout_s=0)

    def test_no_worker_refuses_to_drive_the_journeys(self) -> None:
        with pytest.raises(SystemExit, match=WorkerSettings.health_check_key):
            e2e.wait_for_worker(fakeredis.FakeRedis(), timeout_s=0)


def test_another_users_work_on_a_shared_stack_is_not_a_stray() -> None:
    """A reminder another session queued fires on its own owner: correctly attributed, not this run's."""
    other_user = "6ac90c08c6a0326b0c4385c9"

    assert _judge(CLEAN, strays=[["reminder:completed", other_user, 1]]) == []


def _rows(events: list[tuple[str, dict[str, object]]], uuid_prefix: str) -> list[list[object]]:
    return [
        [f"{uuid_prefix}{i}", name, USER, f"t{i}", json.dumps(props)]
        for i, (name, props) in enumerate(events)
    ]


def _poll(reader: FakeReader, monkeypatch: pytest.MonkeyPatch) -> list[e2e.Received]:
    monkeypatch.setattr(e2e, "POLL_INTERVAL_S", 0)
    stack = Stack(api_url="http://unused", email="e", session_id=SESSION, user_id=UserId(USER))
    expects = [x for journey in e2e.build_journeys(Path("/dev/null")) for x in journey.expects]
    return e2e.poll(reader, stack, e2e.datetime.now(e2e.UTC), expects, timeout_s=5)


def test_sdk_events_still_arriving_do_not_hold_the_poll_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: every poll saw a new $ai_span, so the asserted set never counted as stable."""
    polls = itertools.count()

    def answer(_values: object) -> list[list[object]]:
        n = next(polls)
        return [*_rows(CLEAN, "c"), *_rows([("$ai_span", {})] * (n + 1), f"sdk{n}-")]

    reader = FakeReader({e2e.RUN_EVENTS_HOGQL: answer})

    _poll(reader, monkeypatch)

    assert len(reader.queries) == 2


def test_a_read_the_query_api_timed_out_is_retried_within_the_deadline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = itertools.count()

    def answer(_values: object) -> list[list[object]]:
        if next(calls) == 0:
            raise TimeoutError("The read operation timed out")
        return _rows(CLEAN, "c")

    received = _poll(FakeReader({e2e.RUN_EVENTS_HOGQL: answer}), monkeypatch)

    assert len(received) == len(CLEAN)
    assert "PostHog read timed out" in capsys.readouterr().out
