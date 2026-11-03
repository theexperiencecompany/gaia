"""A gated workflow at dispatch: a confident skip records a visible skipped run and claims nothing."""

from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.constants.hil import HIL_JEV_URL
from app.constants.trigger_gates import GateAuthor
from app.models.trigger_subscription_models import (
    ConditionOperator,
    GateChoice,
    SubscriptionCondition,
    TriggerGate,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowStep
from app.services.providers.provider_credentials_service import ProviderConfig
from app.services.triggers.handlers.gmail import GmailTriggerHandler

pytestmark = pytest.mark.unit

_BASE = "app.services.triggers.base"
USER_ID = "6812f0b3c9a14e2b7d5a91cc"
WORKFLOW_ID = "wf_gated000001"
_GATE = TriggerGate(
    question="Is someone waiting on the user?",
    choices=[
        GateChoice(label="needs_you", meaning="Someone is waiting."),
        GateChoice(label="not_needed", meaning="Nobody is waiting."),
    ],
    skip_on=["not_needed"],
    min_confidence=0.95,
    run_when=[
        SubscriptionCondition(
            field_name="continues_thread", operator=ConditionOperator.EQUALS, value=True
        )
    ],
    author=GateAuthor.GAIA,
)


def _workflow(gate: TriggerGate | None = _GATE) -> Workflow:
    return Workflow(
        id=WORKFLOW_ID,
        user_id=USER_ID,
        title="Draft replies",
        description="Draft a reply to mail that needs one",
        steps=[WorkflowStep(title="Draft", description="Draft the reply")],
        trigger_config=TriggerConfig(
            type=TriggerType.INTEGRATION, trigger_name="gmail_new_message", gate=gate
        ),
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
                "choice": "not_needed" if not_needed >= 0.5 else "needs_you",
                "confidence": max(not_needed, 1 - not_needed),
                "probabilities": {"not_needed": not_needed, "needs_you": 1 - not_needed},
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
    ):
        yield SimpleNamespace(
            jev=router.post(HIL_JEV_URL), claim=claim, buffer=buffer, queue=queue, skipped=skipped
        )


async def _fire(workflows: list[Workflow], **payload: object) -> None:
    data: dict[str, object] = {"thread_id": "t1", "message_id": "t1", "subject": "Sale!", **payload}
    await _Handler(workflows).process_event("GMAIL_NEW_GMAIL_MESSAGE", None, USER_ID, data)


async def test_a_confident_skip_records_a_skipped_run_and_claims_nothing(
    seams: SimpleNamespace,
) -> None:
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
        "Skipped by gate: Nobody is waiting. (not_needed, 0.99)",
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
async def test_unsure_or_failing_gate_queues_as_today(
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


async def test_an_ungated_workflow_never_asks_jev(seams: SimpleNamespace) -> None:
    await _fire([_workflow(gate=None)])

    assert not seams.jev.called
    seams.queue.assert_awaited_once()
