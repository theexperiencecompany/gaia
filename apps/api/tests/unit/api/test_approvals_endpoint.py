"""Unit tests for the HIL approval API endpoints.

Covers the decision relay (single + batch) and the per-user preferences
read/update routes. Service layer is mocked; HTTP status codes, response
shapes, payload forwarding, and the AppError status mapping are verified.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.hil_models import ApprovalLedgerDocument, HILMode, HILPreferences, LedgerState
from app.schemas.hil_schemas import BatchDecisionOutcome
from app.services.hil.ledger_decide import LedgerDecision
from app.services.hil.resolution import (
    ApprovalNotResumableError,
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)

APPROVALS_BASE = "/api/v1/approvals"
USER_ID = "507f1f77bcf86cd799439011"

pytestmark = pytest.mark.usefixtures("hil_barrier_mode")


def _prefs(
    mode: HILMode = "always_allow", tool_overrides: dict[str, bool] | None = None
) -> HILPreferences:
    return HILPreferences(mode=mode, tool_overrides=tool_overrides or {})


# ---------------------------------------------------------------------------
# POST /approvals/{approval_id}/decision
# ---------------------------------------------------------------------------


class TestPostApprovalDecision:
    """POST /api/v1/approvals/{id}/decision."""

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_decision_success(self, mock_resolve: AsyncMock, client: AsyncClient):
        resp = await client.post(
            f"{APPROVALS_BASE}/a1/decision",
            json={"decision": "approve", "feedback": "looks good", "scope": "always_tool"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "reason": None, "status": None}
        mock_resolve.assert_awaited_once_with(
            approval_id="a1",
            user_id=USER_ID,
            kind="approve",
            feedback="looks good",
            scope="always_tool",
        )

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_deny_decision_is_relayed(self, mock_resolve: AsyncMock, client: AsyncClient):
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "deny"})
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "reason": None, "status": None}
        mock_resolve.assert_awaited_once_with(
            approval_id="a1",
            user_id=USER_ID,
            kind="deny",
            feedback=None,
            scope="once",
        )

    async def test_invalid_decision_is_rejected(self, client: AsyncClient):
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "maybe"})
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_late_or_duplicate_decision_is_410(
        self, mock_resolve: AsyncMock, client: AsyncClient
    ):
        mock_resolve.side_effect = ApprovalRequestNotFoundError()
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "approve"})
        assert resp.status_code == 410
        assert "expired or already resolved" in resp.json()["message"]

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_cross_user_decision_is_403(self, mock_resolve: AsyncMock, client: AsyncClient):
        mock_resolve.side_effect = ApprovalRequestForbiddenError()
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "approve"})
        assert resp.status_code == 403
        assert "another user" in resp.json()["message"]

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_unresumable_approval_is_503(self, mock_resolve: AsyncMock, client: AsyncClient):
        mock_resolve.side_effect = ApprovalNotResumableError()
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "approve"})
        assert resp.status_code == 503

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_resolve: AsyncMock, client: AsyncClient):
        mock_resolve.side_effect = Exception("mongo down")
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "approve"})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            f"{APPROVALS_BASE}/a1/decision", json={"decision": "approve"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /approvals/batch-decision
# ---------------------------------------------------------------------------


class TestPostBatchDecision:
    """POST /api/v1/approvals/batch-decision."""

    @patch("app.api.v1.endpoints.approvals.resolve_approvals_batch", new_callable=AsyncMock)
    async def test_batch_success(self, mock_batch: AsyncMock, client: AsyncClient):
        mock_batch.return_value = [
            BatchDecisionOutcome(approval_id="a1", resolved=True),
            BatchDecisionOutcome(approval_id="a2", resolved=True),
        ]
        resp = await client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={
                "decisions": [
                    {"approval_id": "a1", "decision": "approve"},
                    {"approval_id": "a2", "decision": "deny", "feedback": "no"},
                ]
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [o["approval_id"] for o in body["outcomes"]] == ["a1", "a2"]
        assert all(o["resolved"] for o in body["outcomes"])
        mock_batch.assert_awaited_once_with(
            USER_ID,
            [("a1", "approve", None), ("a2", "deny", "no")],
        )

    @patch("app.api.v1.endpoints.approvals.resolve_approvals_batch", new_callable=AsyncMock)
    async def test_batch_reports_unresolved_items_with_reason(
        self, mock_batch: AsyncMock, client: AsyncClient
    ):
        mock_batch.return_value = [
            BatchDecisionOutcome(approval_id="a1", resolved=True),
            BatchDecisionOutcome(approval_id="a2", resolved=False, reason="not_found"),
        ]
        resp = await client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={
                "decisions": [
                    {"approval_id": "a1", "decision": "approve"},
                    {"approval_id": "a2", "decision": "approve"},
                ]
            },
        )
        assert resp.status_code == 200
        outcomes = resp.json()["outcomes"]
        assert outcomes[0]["resolved"] is True
        assert outcomes[1] == {
            "approval_id": "a2",
            "resolved": False,
            "reason": "not_found",
            "status": None,
        }

    async def test_empty_decisions_is_rejected(self, client: AsyncClient):
        resp = await client.post(f"{APPROVALS_BASE}/batch-decision", json={"decisions": []})
        assert resp.status_code == 422

    async def test_over_max_decisions_is_rejected(self, client: AsyncClient):
        resp = await client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={
                "decisions": [{"approval_id": f"a{i}", "decision": "approve"} for i in range(26)]
            },
        )
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.approvals.resolve_approvals_batch", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_batch: AsyncMock, client: AsyncClient):
        mock_batch.side_effect = Exception("mongo down")
        resp = await client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={"decisions": [{"approval_id": "a1", "decision": "approve"}]},
        )
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={"decisions": [{"approval_id": "a1", "decision": "approve"}]},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /approvals/preferences
# ---------------------------------------------------------------------------


class TestGetPreferences:
    """GET /api/v1/approvals/preferences."""

    @patch("app.api.v1.endpoints.approvals.get_hil_preferences", new_callable=AsyncMock)
    async def test_default_preferences(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = _prefs()
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.get(f"{APPROVALS_BASE}/preferences")
        log.set.assert_called_once_with(user={"id": USER_ID}, hil={"operation": "get_preferences"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "always_allow"
        assert body["tool_overrides"] == {}
        mock_get.assert_awaited_once_with(USER_ID)

    @patch("app.api.v1.endpoints.approvals.get_hil_preferences", new_callable=AsyncMock)
    async def test_custom_preferences(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = _prefs(mode="always_ask", tool_overrides={"email_send": True})
        resp = await client.get(f"{APPROVALS_BASE}/preferences")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "always_ask"
        assert body["tool_overrides"] == {"email_send": True}

    @patch("app.api.v1.endpoints.approvals.get_hil_preferences", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.side_effect = Exception("mongo down")
        resp = await client.get(f"{APPROVALS_BASE}/preferences")
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.get(f"{APPROVALS_BASE}/preferences")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /approvals/preferences
# ---------------------------------------------------------------------------


class TestPutPreferences:
    """PUT /api/v1/approvals/preferences."""

    @patch("app.api.v1.endpoints.approvals.update_hil_preferences", new_callable=AsyncMock)
    async def test_partial_update(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = _prefs(mode="always_ask")
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.put(f"{APPROVALS_BASE}/preferences", json={"mode": "always_ask"})
        log.set.assert_called_once_with(
            user={"id": USER_ID}, hil={"operation": "update_preferences"}
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "always_ask"
        mock_update.assert_awaited_once_with(
            USER_ID, mode="always_ask", tool_overrides=None, never_auto_tools=None
        )

    @patch("app.api.v1.endpoints.approvals.update_hil_preferences", new_callable=AsyncMock)
    async def test_tool_overrides_update(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = _prefs(tool_overrides={"email_send": False})
        resp = await client.put(
            f"{APPROVALS_BASE}/preferences",
            json={"tool_overrides": {"email_send": False}},
        )
        assert resp.status_code == 200
        assert resp.json()["tool_overrides"] == {"email_send": False}
        mock_update.assert_awaited_once_with(
            USER_ID, mode=None, tool_overrides={"email_send": False}, never_auto_tools=None
        )

    async def test_invalid_mode_is_rejected(self, client: AsyncClient):
        resp = await client.put(f"{APPROVALS_BASE}/preferences", json={"mode": "sometimes"})
        assert resp.status_code == 422

    @patch("app.api.v1.endpoints.approvals.update_hil_preferences", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.side_effect = Exception("mongo down")
        resp = await client.put(f"{APPROVALS_BASE}/preferences", json={"mode": "auto"})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.put(f"{APPROVALS_BASE}/preferences", json={"mode": "auto"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# PUT /approvals/tools/{tool_name}
# ---------------------------------------------------------------------------


class TestSetToolOverride:
    """PUT /api/v1/approvals/tools/{tool_name}."""

    @patch("app.api.v1.endpoints.approvals.set_tool_override", new_callable=AsyncMock)
    async def test_force_ask(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = _prefs(mode="auto", tool_overrides={"email_send": True})
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.put(f"{APPROVALS_BASE}/tools/email_send", json={"ask": True})
        log.set.assert_called_once_with(
            user={"id": USER_ID},
            hil={"operation": "set_tool_override", "tool": "email_send", "ask": True},
        )
        assert resp.status_code == 200
        assert resp.json()["tool_overrides"] == {"email_send": True}
        mock_set.assert_awaited_once_with(USER_ID, "email_send", True)

    @patch("app.api.v1.endpoints.approvals.set_tool_override", new_callable=AsyncMock)
    async def test_clear_override(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = _prefs(mode="auto")
        resp = await client.put(f"{APPROVALS_BASE}/tools/email_send", json={"ask": None})
        assert resp.status_code == 200
        assert resp.json()["tool_overrides"] == {}
        mock_set.assert_awaited_once_with(USER_ID, "email_send", None)

    @patch("app.api.v1.endpoints.approvals.set_tool_override", new_callable=AsyncMock)
    async def test_service_error_is_500(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.side_effect = Exception("mongo down")
        resp = await client.put(f"{APPROVALS_BASE}/tools/email_send", json={"ask": False})
        assert resp.status_code == 500

    async def test_requires_auth(self, unauthed_client: AsyncClient):
        resp = await unauthed_client.put(f"{APPROVALS_BASE}/tools/email_send", json={"ask": True})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Ledger flag routing (executor-free HIL)
# ---------------------------------------------------------------------------


class TestLedgerDecisionRouting:
    """Flag on routes both decision endpoints to decide_ledger; flag off keeps the interrupt-barrier path.

    Same URLs, same status codes, one truth.
    """

    @patch("app.api.v1.endpoints.approvals.decide_ledger", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.is_hil_ledger_enabled", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_single_decision_routes_to_ledger_with_v(
        self,
        mock_resolve: AsyncMock,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        client: AsyncClient,
    ):
        mock_flag.return_value = True
        mock_decide.return_value = LedgerDecision(
            committed=True,
            approval_id="ap_1",
            prior_state=LedgerState.PENDING,
            state=LedgerState.APPROVED,
        )
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.post(
                f"{APPROVALS_BASE}/ap_1/decision",
                json={"decision": "approve", "feedback": "go ahead", "v": 3},
            )
        assert resp.status_code == 200
        assert resp.json() == {"success": True, "reason": None, "status": "approved"}
        mock_flag.assert_awaited_once_with(USER_ID)
        mock_decide.assert_awaited_once_with(
            "ap_1",
            user_id=USER_ID,
            kind="approve",
            feedback="go ahead",
            v=3,
        )
        log.set.assert_any_call(hil={"resolved": True})
        mock_resolve.assert_not_awaited()

    @patch("app.api.v1.endpoints.approvals.decide_ledger", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.is_hil_ledger_enabled", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_single_decision_stays_on_old_path_when_flag_off(
        self,
        mock_resolve: AsyncMock,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        client: AsyncClient,
    ):
        mock_flag.return_value = False
        resp = await client.post(f"{APPROVALS_BASE}/a1/decision", json={"decision": "deny"})
        assert resp.status_code == 200
        mock_resolve.assert_awaited_once()
        mock_decide.assert_not_awaited()

    # The batch loop lives in ledger_decide.decide_ledger_batch, so decide_ledger is patched there.
    @patch("app.services.hil.ledger_decide.decide_ledger", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.is_hil_ledger_enabled", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.resolve_approvals_batch", new_callable=AsyncMock)
    async def test_batch_decision_routes_each_item_to_ledger(
        self,
        mock_batch: AsyncMock,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        client: AsyncClient,
    ):
        mock_flag.return_value = True
        mock_decide.side_effect = [
            LedgerDecision(
                committed=True,
                approval_id="ap_1",
                prior_state=LedgerState.PENDING,
                state=LedgerState.APPROVED,
            ),
            LedgerDecision(
                committed=False,
                approval_id="ap_2",
                prior_state=LedgerState.APPROVED,
                state=LedgerState.APPROVED,
            ),
        ]
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.post(
                f"{APPROVALS_BASE}/batch-decision",
                json={
                    "decisions": [
                        {"approval_id": "ap_1", "decision": "approve", "v": 1},
                        {"approval_id": "ap_2", "decision": "approve", "v": 0},
                    ]
                },
            )
        assert resp.status_code == 200
        outcomes = resp.json()["outcomes"]
        assert outcomes[0]["approval_id"] == "ap_1"
        assert outcomes[0]["resolved"] is True
        assert outcomes[1]["resolved"] is False
        mock_batch.assert_not_awaited()
        mock_flag.assert_awaited_once_with(USER_ID)
        assert [c.kwargs["user_id"] for c in mock_decide.await_args_list] == [USER_ID, USER_ID]
        log.set.assert_any_call(hil={"resolved": 1})


class TestLedgerAutoPolicyParity:
    """Auto-aligned calls run cardless on both paths: the flag flip must never change what gets asked."""

    @patch("app.api.v1.endpoints.approvals.decide_ledger", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.is_hil_ledger_enabled", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_stale_single_carries_reason_and_status(
        self,
        mock_resolve: AsyncMock,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        client: AsyncClient,
    ):
        mock_flag.return_value = True
        mock_decide.return_value = LedgerDecision(
            committed=False,
            approval_id="ap_1",
            prior_state=LedgerState.APPROVED,
            state=LedgerState.APPROVED,
            stale=True,
        )
        resp = await client.post(
            f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve", "v": 0}
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "reason": "stale", "status": "approved"}
        mock_resolve.assert_not_awaited()


class TestLedgerStaleVersionHonesty:
    """A stale-v tap must not report success: the client refreshes the row instead of believing its tap committed."""

    @patch("app.api.v1.endpoints.approvals.decide_ledger", new_callable=AsyncMock)
    @patch("app.api.v1.endpoints.approvals.is_hil_ledger_enabled", new_callable=AsyncMock)
    async def test_stale_version_returns_success_false(
        self, mock_flag: AsyncMock, mock_decide: AsyncMock, client: AsyncClient
    ):
        mock_flag.return_value = True
        mock_decide.return_value = LedgerDecision(
            committed=False,
            approval_id="ap_1",
            prior_state=LedgerState.APPROVED,
            state=LedgerState.APPROVED,
        )
        resp = await client.post(
            f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve", "v": 0}
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": False, "reason": "not_found", "status": "approved"}


def _ledger_row(tool_name: str = "gmail_send") -> ApprovalLedgerDocument:
    return ApprovalLedgerDocument(
        approval_id="ap_1", conversation_id="c1", fingerprint="fp", tool_name=tool_name
    )


def _decision(state: LedgerState, *, committed: bool = True) -> LedgerDecision:
    return LedgerDecision(
        committed=committed, approval_id="ap_1", prior_state=LedgerState.PENDING, state=state
    )


@patch("app.api.v1.endpoints.approvals.set_tool_override", new_callable=AsyncMock)
@patch(
    "app.api.v1.endpoints.approvals.approval_ledger_repository.get_by_approval_id",
    new_callable=AsyncMock,
)
@patch("app.api.v1.endpoints.approvals.decide_ledger", new_callable=AsyncMock)
@patch(
    "app.api.v1.endpoints.approvals.is_hil_ledger_enabled",
    new_callable=AsyncMock,
    return_value=True,
)
class TestLedgerAlwaysToolScope:
    """On the ledger path, an approved "always" tap stops future asks for that row's tool."""

    async def test_committed_approval_turns_the_tool_override_off(
        self,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        mock_get_row: AsyncMock,
        mock_set_override: AsyncMock,
        client: AsyncClient,
    ):
        mock_decide.return_value = _decision(LedgerState.APPROVED)
        mock_get_row.return_value = _ledger_row("gmail_send")
        resp = await client.post(
            f"{APPROVALS_BASE}/ap_1/decision",
            json={"decision": "approve", "scope": "always_tool", "v": 0},
        )
        assert resp.json() == {"success": True, "reason": None, "status": "approved"}
        mock_get_row.assert_awaited_once_with("ap_1")
        mock_set_override.assert_awaited_once_with(USER_ID, "gmail_send", False)

    async def test_denial_never_touches_the_override(
        self,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        mock_get_row: AsyncMock,
        mock_set_override: AsyncMock,
        client: AsyncClient,
    ):
        mock_decide.return_value = _decision(LedgerState.DENIED)
        mock_get_row.return_value = _ledger_row()
        resp = await client.post(
            f"{APPROVALS_BASE}/ap_1/decision",
            json={"decision": "deny", "scope": "always_tool", "v": 0},
        )
        assert resp.json()["success"] is True
        mock_set_override.assert_not_awaited()

    async def test_once_scope_never_touches_the_override(
        self,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        mock_get_row: AsyncMock,
        mock_set_override: AsyncMock,
        client: AsyncClient,
    ):
        mock_decide.return_value = _decision(LedgerState.APPROVED)
        mock_get_row.return_value = _ledger_row()
        await client.post(f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve", "v": 0})
        mock_set_override.assert_not_awaited()

    async def test_vanished_row_skips_the_override_and_logs_an_error(
        self,
        mock_flag: AsyncMock,
        mock_decide: AsyncMock,
        mock_get_row: AsyncMock,
        mock_set_override: AsyncMock,
        client: AsyncClient,
    ):
        mock_decide.return_value = _decision(LedgerState.APPROVED)
        mock_get_row.return_value = None
        with patch("app.api.v1.endpoints.approvals.log") as log:
            resp = await client.post(
                f"{APPROVALS_BASE}/ap_1/decision",
                json={"decision": "approve", "scope": "always_tool", "v": 0},
            )
        assert resp.json()["success"] is True
        mock_set_override.assert_not_awaited()
        log.error.assert_called_once()
        message = log.error.call_args.args[0]
        assert "tool override skipped" in message
        assert log.error.call_args.kwargs == {"approval_id": "ap_1"}
