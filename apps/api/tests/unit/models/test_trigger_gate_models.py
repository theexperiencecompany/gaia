"""A trigger gate as its owner stores it: GAIA's or the user's condition, or a code preset."""

from datetime import UTC, datetime

from pydantic import ValidationError
import pytest

from app.constants.trigger_gates import GateAuthor, SystemGatePreset
from app.models.todo_models import TodoDocument, TodoResponse
from app.models.trigger_gate_models import AuthoredGate, SystemGate, TriggerGate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.models.workflow_models import (
    TriggerConfig,
    TriggerType,
    Workflow,
    WorkflowUpdate,
    as_read_view,
)

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
        with pytest.raises(ValidationError) as refused:
            _workflow(trigger_type, AUTHORED)

        assert [e["msg"] for e in refused.value.errors()] == [
            "Value error, a gate needs an integration trigger"
        ]

    def test_an_integration_workflow_takes_a_gate(self) -> None:
        assert _workflow(TriggerType.INTEGRATION, DESK).gate == DESK


class TestTheGateTheUserReads:
    """The API shows each gate's condition and whether it can skip a run yet; neither is stored."""

    @pytest.mark.parametrize(
        ("gate", "shown", "enforced"),
        [
            (AUTHORED, AUTHORED.condition, False),
            (DESK, "a real person or a real obligation is waiting on you", True),
        ],
        ids=["authored_in_shadow", "system_enforced"],
    )
    def test_a_workflow_shows_its_gate(self, gate: TriggerGate, shown: str, enforced: bool) -> None:
        wire = as_read_view(_workflow(TriggerType.INTEGRATION, gate)).model_dump(mode="json")

        assert (wire["gate"]["display_condition"], wire["gate"]["enforced"]) == (shown, enforced)

    def test_a_tracked_todo_shows_each_watchs_gate(self) -> None:
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="Inbox desk",
            created_at=datetime(2026, 11, 5, tzinfo=UTC),
            updated_at=datetime(2026, 11, 5, tzinfo=UTC),
            trigger_subscriptions=[_subscription(gate=DESK), _subscription()],
        )

        wire = TodoResponse.from_document(doc).model_dump(mode="json")

        assert [w["gate"] for w in wire["trigger_subscriptions"]] == [
            {
                "kind": "system",
                "recent_skips": [],
                "preset": "inbox_desk",
                "enabled": True,
                "display_condition": "a real person or a real obligation is waiting on you",
                "enforced": True,
            },
            None,
        ]

    @pytest.mark.parametrize("gate", [AUTHORED, DESK], ids=["authored", "system"])
    def test_a_gate_read_through_the_view_is_written_back_without_its_display_fields(
        self, gate: TriggerGate
    ) -> None:
        read = as_read_view(_workflow(TriggerType.INTEGRATION, gate))

        assert WorkflowUpdate(gate=read.gate).model_dump(exclude_unset=True) == {
            "gate": gate.model_dump()
        }
