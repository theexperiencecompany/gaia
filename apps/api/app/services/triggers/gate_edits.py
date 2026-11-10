"""A user's edit to a job's gate: the gate it stores, and the one event that says what changed."""

from typing import Final

from pydantic import TypeAdapter

from app.constants.trigger_gates import GateAuthor, GateEditAction, GateOwner
from app.models.trigger_gate_models import AuthoredGate, GateEdit, TriggerGate
from app.services.analytics_service import capture
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.triggers import TriggerGateEdited

# Re-reads a gate as its stored type, so a read view's display fields never reach a write.
_STORED_GATE: Final[TypeAdapter[TriggerGate]] = TypeAdapter(TriggerGate)


def apply_gate_edit(current: TriggerGate | None, edit: GateEdit) -> TriggerGate:
    """Return the gate an edit stores: a changed condition is the user's, an unchanged one only switches."""
    if edit.condition is not None and not (
        isinstance(current, AuthoredGate) and current.condition == edit.condition
    ):
        return AuthoredGate(condition=edit.condition, author=GateAuthor.USER, enabled=edit.enabled)
    if current is None:
        raise AppError(
            message="There is no gate to turn on or off",
            why="an edit with no condition switches the gate already there",
            fix="send a condition to add one",
            status_code=422,
        )
    return _STORED_GATE.validate_python({**current.model_dump(), "enabled": edit.enabled})


def gate_edit_action(
    before: TriggerGate | None, after: TriggerGate | None
) -> GateEditAction | None:
    """Name what a write did to a gate, or None when it left the gate as it was."""
    if before is None or after is None:
        if after is not None:
            return GateEditAction.ADDED
        return None if before is None else GateEditAction.REMOVED
    if (before.kind, before.display_condition) != (after.kind, after.display_condition):
        return GateEditAction.EDITED
    if before.enabled != after.enabled:
        return GateEditAction.ENABLED if after.enabled else GateEditAction.DISABLED
    return None


def report_gate_edit(
    user_id: str, owner: GateOwner, before: TriggerGate | None, after: TriggerGate | None
) -> None:
    """Send trigger:gate_edited for a stored write that changed the gate; call it after the write."""
    action = gate_edit_action(before, after)
    gate = after or before
    if action is None or gate is None:
        return
    capture(
        UserId(user_id),
        TriggerGateEdited(owner_type=owner.value, action=action.value, gate_kind=gate.kind.value),
    )
