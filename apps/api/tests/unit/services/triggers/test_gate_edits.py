"""A user's edit to a gate: what it stores, what it refuses, and the event that names it."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.constants.trigger_gates import GateAuthor, GateEditAction, GateOwner, SystemGatePreset
from app.models.trigger_gate_models import (
    AuthoredGate,
    GateEdit,
    GateSkipRecord,
    SystemGate,
    SystemGateView,
    TriggerGate,
)
from app.services.triggers.gate_edits import apply_gate_edit, gate_edit_action, report_gate_edit
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.triggers import TriggerGateEdited

pytestmark = pytest.mark.unit

USER_ID = "507f1f77bcf86cd799439011"
AUTHORED = AuthoredGate(condition="the email is from a customer", author=GateAuthor.GAIA)
DESK = SystemGate(preset=SystemGatePreset.INBOX_DESK)
SKIP = GateSkipRecord(event="Substack · Weekly digest", at=datetime(2026, 11, 5, 9, tzinfo=UTC))


class TestApplyGateEdit:
    def test_an_unchanged_condition_keeps_its_author(self) -> None:
        edit = GateEdit(condition=AUTHORED.condition, enabled=False)

        assert apply_gate_edit(AUTHORED, edit) == AUTHORED.model_copy(update={"enabled": False})

    @pytest.mark.parametrize("current", [AUTHORED, DESK, None], ids=["authored", "system", "none"])
    def test_a_new_condition_is_the_users(self, current: TriggerGate | None) -> None:
        edit = GateEdit.model_validate(
            {"condition": "the email is about an invoice", "author": "gaia"}
        )

        assert apply_gate_edit(current, edit) == AuthoredGate(
            condition="the email is about an invoice", author=GateAuthor.USER
        )

    @pytest.mark.parametrize("current", [AUTHORED, DESK], ids=["authored", "system"])
    def test_turning_a_gate_off_keeps_its_text_and_author(self, current: TriggerGate) -> None:
        assert apply_gate_edit(current, GateEdit(enabled=False)) == current.model_copy(
            update={"enabled": False}
        )

    def test_switching_a_gate_keeps_its_recent_skips(self) -> None:
        skipped = AUTHORED.model_copy(update={"recent_skips": [SKIP]})

        for edit in (GateEdit(enabled=False), GateEdit(condition=AUTHORED.condition)):
            assert apply_gate_edit(skipped, edit).recent_skips == [SKIP]

    def test_a_new_condition_starts_with_no_skips(self) -> None:
        skipped = AUTHORED.model_copy(update={"recent_skips": [SKIP]})

        edited = apply_gate_edit(skipped, GateEdit(condition="the email is about an invoice"))

        assert edited.recent_skips == []

    def test_a_gate_read_through_the_view_is_stored_as_its_own_type(self) -> None:
        shown = SystemGateView(preset=SystemGatePreset.INBOX_DESK)

        assert type(apply_gate_edit(shown, GateEdit(enabled=False))) is SystemGate

    def test_switching_a_gate_that_is_not_there_is_refused(self) -> None:
        with pytest.raises(AppError) as refused:
            apply_gate_edit(None, GateEdit(enabled=False))

        assert refused.value == AppError(
            message="There is no gate to turn on or off",
            why="an edit with no condition switches the gate already there",
            fix="send a condition to add one",
            status_code=422,
        )


OFF = AUTHORED.model_copy(update={"enabled": False})
REWORDED = AuthoredGate(condition="the email is about an invoice", author=GateAuthor.USER)


class TestGateEditAction:
    @pytest.mark.parametrize(
        ("before", "after", "action"),
        [
            (None, AUTHORED, GateEditAction.ADDED),
            (AUTHORED, REWORDED, GateEditAction.EDITED),
            (DESK, REWORDED, GateEditAction.EDITED),
            (AUTHORED, OFF, GateEditAction.DISABLED),
            (OFF, AUTHORED, GateEditAction.ENABLED),
            (AUTHORED, None, GateEditAction.REMOVED),
            (AUTHORED, AUTHORED, None),
            (None, None, None),
        ],
        ids=[
            "added",
            "edited",
            "replaced_preset",
            "disabled",
            "enabled",
            "removed",
            "same",
            "none",
        ],
    )
    def test_names_what_the_write_did(
        self, before: TriggerGate | None, after: TriggerGate | None, action: GateEditAction | None
    ) -> None:
        assert gate_edit_action(before, after) == action

    def test_a_change_sends_one_event_for_the_owner(self) -> None:
        with patch("app.services.triggers.gate_edits.capture") as capture:
            report_gate_edit(
                USER_ID, GateOwner.TODO, DESK, DESK.model_copy(update={"enabled": False})
            )

        capture.assert_called_once_with(
            UserId(USER_ID),
            TriggerGateEdited(owner_type="todo", action="disabled", gate_kind="system"),
        )

    @pytest.mark.parametrize(
        ("before", "after", "action", "gate_kind"),
        [(AUTHORED, None, "removed", "authored"), (DESK, REWORDED, "edited", "authored")],
        ids=["removed", "rewritten_from_a_preset"],
    )
    def test_the_event_names_the_gate_the_write_left(
        self, before: TriggerGate, after: TriggerGate | None, action: str, gate_kind: str
    ) -> None:
        with patch("app.services.triggers.gate_edits.capture") as capture:
            report_gate_edit(USER_ID, GateOwner.TODO, before, after)

        capture.assert_called_once_with(
            UserId(USER_ID),
            TriggerGateEdited(owner_type="todo", action=action, gate_kind=gate_kind),
        )

    def test_a_write_that_changed_nothing_sends_none(self) -> None:
        with patch("app.services.triggers.gate_edits.capture") as capture:
            report_gate_edit(USER_ID, GateOwner.WORKFLOW, AUTHORED, AUTHORED)

        capture.assert_not_called()
