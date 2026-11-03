"""Trigger gates: one JEV call at fire time, where every failure runs the job as today.

JEV is served at its HTTP boundary (respx on the Decisions URL), so the real
client, its validation and the gate's handling of a 5xx, a timeout or a garbage
body are what these tests exercise.
"""

from collections.abc import Iterator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.constants.hil import HIL_JEV_URL
from app.constants.trigger_gates import GateAuthor, GateOutcome, GateOwner, GateReason
from app.models.trigger_subscription_models import (
    ConditionOperator,
    GateChoice,
    SubscriptionCondition,
    TriggerGate,
)
from app.services.providers.provider_credentials_service import ProviderConfig
from app.services.triggers.trigger_gate import admit_event, decide_gate, event_fields

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
GMAIL = "gmail_new_message"
_GATE_MODULE = "app.services.triggers.trigger_gate"


def _gate(**overrides: Any) -> TriggerGate:
    return TriggerGate.model_validate(
        {
            "question": "Is a real person waiting on the user?",
            "choices": [
                {"label": "needs_you", "meaning": "Someone is waiting on the user."},
                {"label": "not_needed", "meaning": "Nothing is waiting on the user."},
            ],
            "skip_on": ["not_needed"],
            "min_confidence": 0.95,
            "author": GateAuthor.SYSTEM,
            **overrides,
        }
    )


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "thread_id": "t1",
        "message_id": "t1",
        "sender": "Priya <priya@northwind.dev>",
        "subject": "Demo tomorrow?",
        "message_text": "are we still on for 4pm?",
        "label_ids": ["INBOX", "CATEGORY_PERSONAL"],
        **overrides,
    }


def _answer(choice: str, not_needed: float) -> dict[str, object]:
    return {
        "answers": {
            "gate": {
                "type": "choice",
                "choice": choice,
                "confidence": max(not_needed, 1 - not_needed),
                "probabilities": {"not_needed": not_needed, "needs_you": 1 - not_needed},
            }
        },
        "usage": {"input_tokens": 850, "output_tokens": 0},
    }


@pytest.fixture
def jev() -> Iterator[respx.Route]:
    with (
        respx.mock(assert_all_called=False) as router,
        patch(
            "app.services.hil.jev_client.resolve",
            AsyncMock(return_value=ProviderConfig(api_key="or-key")),  # pragma: allowlist secret
        ),
    ):
        yield router.post(HIL_JEV_URL)


async def _decide(gate: TriggerGate | None = None, **payload: object) -> Any:
    return await decide_gate(gate or _gate(), GMAIL, _payload(**payload), "Inbox desk: triage mail")


class TestVerdicts:
    async def test_a_confident_skip_choice_skips(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("not_needed", 0.99)))
        decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.SKIP, GateReason.JEV_SKIP)
        assert decision.detail == "Nothing is waiting on the user. (not_needed, 0.99)"

    async def test_a_skip_choice_under_min_confidence_runs(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("not_needed", 0.94)))
        decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.JEV_UNSURE)

    async def test_the_line_itself_skips(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("not_needed", 0.95)))
        assert (await _decide()).outcome is GateOutcome.SKIP

    async def test_a_run_choice_runs_however_confident(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("needs_you", 0.01)))
        decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.JEV_RUN)


class TestEveryFailureRuns:
    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(500, text="upstream exploded"),
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, text="<html>not json</html>"),
            httpx.Response(200, json={"answers": {}}),
            httpx.Response(200, json={"answers": {"gate": {"type": "text", "choice": "x"}}}),
            httpx.Response(200, json={"answers": {"gate": {"type": "choice", "choice": "maybe"}}}),
        ],
        ids=["5xx", "429", "not-json", "no-answer", "non-choice", "unknown-choice"],
    )
    async def test_a_bad_response_runs(self, jev: respx.Route, response: httpx.Response) -> None:
        jev.mock(return_value=response)
        decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.JEV_ERROR)

    @pytest.mark.parametrize(
        "error", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")], ids=["timeout", "down"]
    )
    async def test_a_transport_failure_runs(self, jev: respx.Route, error: Exception) -> None:
        jev.mock(side_effect=error)
        decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.JEV_ERROR)

    async def test_no_openrouter_key_runs(self) -> None:
        with patch("app.services.hil.jev_client.resolve", AsyncMock(return_value=None)):
            decision = await _decide()
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.JEV_ERROR)


class TestFreeRules:
    async def test_a_run_when_rule_runs_without_asking_jev(self, jev: respx.Route) -> None:
        gate = _gate(
            run_when=[
                SubscriptionCondition(
                    field_name="continues_thread", operator=ConditionOperator.EQUALS, value=True
                )
            ]
        )
        decision = await _decide(gate, continues_thread=True)
        assert (decision.outcome, decision.reason) == (GateOutcome.RUN, GateReason.RULE)
        assert not jev.called

    async def test_a_run_when_rule_that_does_not_hold_asks_jev(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("not_needed", 0.99)))
        gate = _gate(
            run_when=[
                SubscriptionCondition(
                    field_name="continues_thread", operator=ConditionOperator.EQUALS, value=True
                )
            ]
        )
        assert (await _decide(gate, continues_thread=False)).outcome is GateOutcome.SKIP

    async def test_a_skip_when_rule_skips_without_asking_jev(self, jev: respx.Route) -> None:
        gate = _gate(
            skip_when=[
                SubscriptionCondition(
                    field_name="label_ids", operator=ConditionOperator.CONTAINS, value="SPAM"
                )
            ]
        )
        decision = await _decide(gate, label_ids=["SPAM"])
        assert (decision.outcome, decision.reason) == (GateOutcome.SKIP, GateReason.RULE)
        assert decision.detail == "label_ids contains SPAM"
        assert not jev.called


class TestRequest:
    async def test_jev_reads_the_curated_fields_clipped_and_the_job(self, jev: respx.Route) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("needs_you", 0.0)))
        await _decide(message_text="x" * 5000, payload={"headers": [{"name": "X", "value": "y"}]})
        body = json.loads(jev.calls.last.request.content)
        event = body["state"]["event"]
        assert event["message_text"] == "x" * 300 + "…"
        assert "payload" not in event
        assert body["state"]["automation"] == "Inbox desk: triage mail"
        assert set(body["questions"]["gate"]["criteria"]) == {"needs_you", "not_needed"}
        assert "Is a real person waiting on the user?" in body["questions"]["gate"]["instructions"]

    def test_a_trigger_with_no_catalog_sends_its_scalar_fields(self) -> None:
        fields = event_fields("no_such_trigger", {"title": "Hi", "count": 2, "nested": {"a": 1}})
        assert fields == {"title": "Hi", "count": 2}


class TestAdmit:
    async def test_no_gate_asks_nothing(self, jev: respx.Route) -> None:
        verdict = await admit_event(
            None,
            owner=GateOwner.TODO,
            user_id=USER_ID,
            trigger_name=GMAIL,
            payload={},
            automation="",
        )
        assert verdict is None
        assert not jev.called

    async def test_a_disabled_gate_asks_nothing(self, jev: respx.Route) -> None:
        verdict = await admit_event(
            _gate(enabled=False),
            owner=GateOwner.TODO,
            user_id=USER_ID,
            trigger_name=GMAIL,
            payload=_payload(),
            automation="",
        )
        assert verdict is None
        assert not jev.called

    @pytest.mark.parametrize("enforced", [False, True], ids=["shadow", "enforced"])
    async def test_a_skip_acts_only_when_enforced_and_is_counted_either_way(
        self, jev: respx.Route, enforced: bool, posthog_events: list[dict[str, object]]
    ) -> None:
        jev.mock(return_value=httpx.Response(200, json=_answer("not_needed", 0.99)))
        with patch(f"{_GATE_MODULE}.is_trigger_gates_enforced", AsyncMock(return_value=enforced)):
            verdict = await admit_event(
                _gate(),
                owner=GateOwner.WORKFLOW,
                user_id=USER_ID,
                trigger_name=GMAIL,
                payload=_payload(),
                automation="job",
            )
        assert verdict is not None
        assert verdict.decision.outcome is GateOutcome.SKIP
        assert verdict.skips is enforced
        [event] = [e for e in posthog_events if e["event"] == "workflow:trigger_gate_decided"]
        props = event["properties"]
        assert isinstance(props, dict)
        assert (props["outcome"], props["skipped"], props["enforced"]) == (
            "skip",
            enforced,
            enforced,
        )
        assert (props["owner_type"], props["author"], props["reason"]) == (
            "workflow",
            "system",
            "jev_skip",
        )
        assert event["distinct_id"] == USER_ID


class TestGateModel:
    def test_every_choice_skipping_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one gate choice must run"):
            _gate(skip_on=["needs_you", "not_needed"])

    def test_skip_on_must_name_a_choice(self) -> None:
        with pytest.raises(ValueError, match="does not offer"):
            _gate(skip_on=["maybe"])

    def test_a_bare_question_gets_yes_no_skipping_no(self) -> None:
        gate = TriggerGate(question="Is this about the launch?", author=GateAuthor.USER)
        assert [c.label for c in gate.choices] == ["yes", "no"]
        assert gate.skip_on == ["no"]
        assert gate.min_confidence == 0.90

    def test_duplicate_choices_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            _gate(choices=[GateChoice(label="a", meaning="x"), GateChoice(label="a", meaning="y")])
