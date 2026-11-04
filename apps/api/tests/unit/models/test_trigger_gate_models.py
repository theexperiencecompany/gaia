"""A trigger gate as its owner stores it: GAIA's or the user's condition, or a code preset."""

from pydantic import ValidationError
import pytest

from app.constants.trigger_gates import GateAuthor, SystemGatePreset
from app.models.trigger_gate_models import AuthoredGate, AuthoredGateEdit, SystemGate, TriggerGate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.models.workflow_models import TriggerConfig, TriggerType, Workflow, WorkflowUpdate

pytestmark = pytest.mark.unit

AUTHORED = AuthoredGate(
    condition="the email is from a customer about billing", author=GateAuthor.GAIA
)
DESK = SystemGate(preset=SystemGatePreset.INBOX_DESK)


def _subscription(**overrides: object) -> TriggerSubscription:
    return TriggerSubscription.model_validate(
        {
            "trigger_name": "gmail_new_message",
            "action": SubscriptionAction.EXECUTE,
            "resolution": SubscriptionResolution.ACCOUNT,
            **overrides,
        }
    )


def _workflow(trigger_type: TriggerType, gate: TriggerGate | None) -> Workflow:
    trigger = TriggerConfig(
        type=trigger_type,
        trigger_name="gmail_new_message" if trigger_type is TriggerType.INTEGRATION else None,
    )
    return Workflow.model_validate(
        {
            "user_id": "u1",
            "title": "Billing replies",
            "steps": [],
            "trigger_config": trigger,
            "gate": gate,
        }
    )


class TestStoredGates:
    @pytest.mark.parametrize("gate", [AUTHORED, DESK], ids=["authored", "system"])
    def test_a_subscription_gate_reloads_from_the_partial_write_it_is_stored_with(
        self, gate: TriggerGate
    ) -> None:
        stored = _subscription(gate=gate).model_dump(exclude_unset=True)

        assert TriggerSubscription.model_validate(stored).gate == gate

    @pytest.mark.parametrize("gate", [AUTHORED, DESK], ids=["authored", "system"])
    def test_a_workflow_gate_reloads_from_the_partial_write_it_is_stored_with(
        self, gate: TriggerGate
    ) -> None:
        stored = WorkflowUpdate(gate=gate).model_dump(exclude_unset=True)["gate"]

        assert _workflow(TriggerType.INTEGRATION, stored).gate == gate

    def test_a_subscription_stored_before_gates_still_loads(self) -> None:
        stored = _subscription().model_dump(exclude={"gate"})

        assert TriggerSubscription.model_validate(stored).gate is None

    def test_a_turned_off_gate_keeps_its_condition(self) -> None:
        off = AUTHORED.model_copy(update={"enabled": False})

        reloaded = _subscription(gate=off).model_dump(exclude_unset=True)

        assert TriggerSubscription.model_validate(reloaded).gate == off

    def test_a_system_gate_reads_its_condition_from_the_preset(self) -> None:
        assert DESK.display_condition == "a real person or a real obligation is waiting on you"


class TestWhereAGateMayLive:
    @pytest.mark.parametrize(
        "action",
        [SubscriptionAction.NOTIFY, SubscriptionAction.COMPLETE, SubscriptionAction.UNBLOCK],
    )
    def test_only_a_subscription_that_runs_the_todo_takes_a_gate(
        self, action: SubscriptionAction
    ) -> None:
        with pytest.raises(ValidationError, match="a gate needs action execute"):
            _subscription(action=action, gate=AUTHORED)

    def test_an_execute_subscription_takes_a_gate(self) -> None:
        assert _subscription(gate=AUTHORED).gate == AUTHORED

    @pytest.mark.parametrize("trigger_type", [TriggerType.SCHEDULE, TriggerType.MANUAL])
    def test_only_an_integration_workflow_takes_a_gate(self, trigger_type: TriggerType) -> None:
        with pytest.raises(ValidationError, match="a gate needs an integration trigger"):
            _workflow(trigger_type, AUTHORED)

    def test_an_integration_workflow_takes_a_gate(self) -> None:
        assert _workflow(TriggerType.INTEGRATION, DESK).gate == DESK


class TestAClientsEdit:
    def test_an_unchanged_condition_keeps_its_author(self) -> None:
        edit = AuthoredGateEdit(condition=AUTHORED.condition, enabled=False)

        assert edit.applied_to(AUTHORED) == AUTHORED.model_copy(update={"enabled": False})

    @pytest.mark.parametrize("current", [AUTHORED, DESK, None], ids=["authored", "system", "none"])
    def test_a_new_condition_is_the_users(self, current: TriggerGate | None) -> None:
        edit = AuthoredGateEdit.model_validate(
            {"condition": "the email is from a customer", "author": "gaia"}
        )

        assert edit.applied_to(current) == AuthoredGate(
            condition="the email is from a customer", author=GateAuthor.USER
        )
