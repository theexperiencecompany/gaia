"""Attacks on the approval bridge (app/services/hil/bridge.py)."""

from app.constants.hil import APPROVAL_REQUEST_TOOL_NAME
from app.models.hil_models import ApprovalLedgerDocument
from shared.py.approvals import ActionResult, ApprovalOutcome
from tests.helpers import ledger_facts

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.bridge"


def _card_frame(approval_id: str, *, held: bool = False, **data: object) -> dict[str, object]:
    frame: dict[str, object] = {
        "tool_data": {
            "tool_name": APPROVAL_REQUEST_TOOL_NAME,
            "data": {"approval_id": approval_id, "outcome": None, **data},
        }
    }
    if held:
        frame["_held_approval"] = True
    return frame


def _ledger_row(
    approval_id: str, state: ApprovalOutcome | ActionResult | None = None
) -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id=approval_id,
        conversation_id=CONVERSATION_ID,
        user_id=USER_ID,
        fingerprint=f"fp-{approval_id}",
        tool_name="send_email",
        summary=f"summary {approval_id}",
        **ledger_facts(state),
    )
