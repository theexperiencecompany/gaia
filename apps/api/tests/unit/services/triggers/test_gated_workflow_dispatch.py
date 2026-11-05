"""A gated workflow at dispatch: a skip records a visible skipped run and claims, batches and queues nothing."""

import asyncio
from collections.abc import Iterator, Mapping
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from pymongo.errors import PyMongoError
import pytest
import respx
from sentry_sdk.types import Event

from app.constants.hil import HIL_JEV_URL
from app.constants.trigger_gates import GateAuthor
from app.models.trigger_gate_models import AuthoredGate, TriggerGate
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.services.providers.provider_credentials_service import ProviderConfig
from app.services.triggers.handlers.gmail import GmailTriggerHandler
from shared.py.analytics.catalog.triggers import TriggerGateDecided
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_BASE = "app.services.triggers.base"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
WORKFLOW_ID = "wf_gated000001"
CONDITION = "the email is from a customer about billing"
_GATE = AuthoredGate(condition=CONDITION, author=GateAuthor.GAIA)


def _workflow(
    gate: TriggerGate | None = _GATE,
    workflow_id: str = WORKFLOW_ID,
    trigger_name: str | None = "gmail_new_message",
) -> Workflow:
    return Workflow(
        id=workflow_id,
        user_id=USER_ID,
        title="Draft replies",
        description="Draft a reply to mail that needs one",
        steps=[WorkflowStep(title="Draft", description="Draft the reply")],
        trigger_config=TriggerConfig(type=TriggerType.INTEGRATION, trigger_name=trigger_name),
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


def _jev_body(not_needed: float) -> dict[str, object]:
    return {
        "answers": {
            "gate": {
                "type": "choice",
                "choice": "not_needed" if not_needed >= 0.5 else "needed",
                "confidence": max(not_needed, 1 - not_needed),
                "probabilities": {"not_needed": not_needed, "needed": 1 - not_needed},
            }
        }
    }


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    with (
        respx.mock(assert_all_called=False) as router,
        patch(
            "app.services.hil.jev_client.resolve",
            AsyncMock(return_value=ProviderConfig(api_key="or-key")),  # pragma: allowlist secret
        ),
        patch(
            "app.services.triggers.trigger_gate.is_trigger_gates_enforced",
            AsyncMock(return_value=True),
        ),
        patch(f"{_BASE}.TriggerHandler._queue_todo_dispatch", AsyncMock(return_value=True)),
        patch(f"{_BASE}.get_signal_matching_context", AsyncMock(return_value="")),
        patch(f"{_BASE}._claim_occurrence", AsyncMock(return_value=True)) as claim,
        patch(f"{_BASE}.buffer_trigger_event", AsyncMock(return_value=False)) as buffer,
        patch(f"{_BASE}.WorkflowQueueService.queue_workflow_execution", AsyncMock()) as queue,
        patch(f"{_BASE}.record_skipped_execution", AsyncMock()) as skipped,
        patch("app.services.triggers.trigger_gate.capture") as capture,
        patch(
            "app.services.triggers.trigger_gate.user_wrote_in_thread", AsyncMock(return_value=True)
        ) as wrote,
    ):
        yield SimpleNamespace(
            jev=router.post(HIL_JEV_URL),
            claim=claim,
            buffer=buffer,
            queue=queue,
            skipped=skipped,
            capture=capture,
            wrote=wrote,
        )


async def _fire(workflows: list[Workflow], **payload: object) -> None:
    data: dict[str, object] = {"thread_id": "t1", "message_id": "t1", "subject": "Sale!", **payload}
    await _Handler(workflows).process_event("GMAIL_NEW_GMAIL_MESSAGE", None, USER_ID, data)


async def test_a_skip_records_a_skipped_run_and_claims_nothing(seams: SimpleNamespace) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))

    await _fire([_workflow()])

    seams.queue.assert_not_awaited()
    seams.buffer.assert_not_awaited()
    # The occurrence stays unclaimed, so a later trigger for the same one still runs.
    seams.claim.assert_not_awaited()
    seams.skipped.assert_awaited_once_with(
        WORKFLOW_ID,
        USER_ID,
        TriggerType.INTEGRATION.value,
        f'Skipped: "Sale!". Not a match for "{CONDITION}" (99% sure).',
    )


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
    assert call.args[3].startswith('Skipped: GitGuardian <security@gitguardian.com>, "Sale!".')


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


async def test_a_skip_whose_history_write_fails_is_reported_and_spares_the_others(
    seams: SimpleNamespace, sentry_events: list[Event]
) -> None:
    seams.jev.mock(return_value=httpx.Response(200, json=_jev_body(0.99)))
    seams.skipped.side_effect = PyMongoError("history down")

    async with captured_wide_event() as event:
        await _fire([_workflow(), _workflow(gate=None, workflow_id="wf_ungated0001")])

    assert [c.args[0] for c in seams.queue.await_args_list] == ["wf_ungated0001"]
    assert event["errors"] == [
        {
            "msg": "trigger_workflow_skip_record_failed",
            "workflow_id": WORKFLOW_ID,
            "user_id": USER_ID,
            "error_type": "PyMongoError",
            "error": "history down",
        }
    ]
    assert [e["exception"]["values"][-1]["type"] for e in sentry_events] == ["PyMongoError"]
