"""Unit tests for the HIL approval API endpoints.

Covers the decision relay (single + batch) and the per-user preferences
read/update routes. Service layer is mocked; HTTP status codes, response
shapes, payload forwarding, and the AppError status mapping are verified.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
import pytest

from app.models.hil_models import HILMode, HILPreferences
from app.schemas.hil_schemas import (
    ApprovalDecisionRequest,
    BatchDecisionItem,
    BatchDecisionOutcome,
)
from app.services.hil.errors import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
    ToolAlwaysAsksError,
)
from app.services.hil.ledger_decide import LedgerDecision
from shared.py.analytics.catalog.hil import ActionResult, ApprovalOutcome
from tests.helpers import ledger_facts

APPROVALS_BASE = "/api/v1/approvals"
USER_ID = "507f1f77bcf86cd799439011"
DECIDE = "app.api.v1.endpoints.approvals.decide_ledger_card"
BATCH = "app.api.v1.endpoints.approvals.decide_ledger_batch"


def _prefs(
    mode: HILMode = "always_allow", tool_overrides: dict[str, bool] | None = None
) -> HILPreferences:
    return HILPreferences(mode=mode, tool_overrides=tool_overrides or {})


def _decision(
    state: ApprovalOutcome | ActionResult | None, *, committed: bool = True
) -> LedgerDecision:
    return LedgerDecision(committed=committed, approval_id="ap_1", **ledger_facts(state))


class TestPostApprovalDecision:
    """POST /api/v1/approvals/{id}/decision: every tap commits in the log through the ledger decide."""

    @patch(DECIDE, new_callable=AsyncMock)
    async def test_a_committed_tap_reports_what_it_committed(
        self, mock_decide: AsyncMock, client: AsyncClient
    ) -> None:
        mock_decide.return_value = _decision(ApprovalOutcome.APPROVED)
        resp = await client.post(
            f"{APPROVALS_BASE}/ap_1/decision",
            json={"decision": "approve", "scope": "always_tool"},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "success": True,
            "reason": None,
            "outcome": "approved",
            "action": None,
        }
        mock_decide.assert_awaited_once_with(
            "ap_1",
            user_id=USER_ID,
            tap=ApprovalDecisionRequest(decision="approve", feedback=None, scope="always_tool"),
        )

    @patch(DECIDE, new_callable=AsyncMock)
    async def test_an_already_decided_approval_says_how_it_ended(
        self, mock_decide: AsyncMock, client: AsyncClient
    ) -> None:
        mock_decide.return_value = _decision(ApprovalOutcome.EXPIRED, committed=False)
        resp = await client.post(f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve"})
        assert resp.status_code == 200
        assert resp.json() == {
            "success": False,
            "reason": "not_found",
            "outcome": "expired",
            "action": None,
        }

    async def test_invalid_decision_is_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "maybe"})
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        ("error", "status"),
        [(ApprovalRequestNotFoundError(), 410), (ApprovalRequestForbiddenError(), 403)],
    )
    async def test_a_refused_tap_maps_to_its_status(
        self, error: Exception, status: int, client: AsyncClient
    ) -> None:
        with patch(DECIDE, new=AsyncMock(side_effect=error)):
            resp = await client.post(
                f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve"}
            )
        assert resp.status_code == status

    async def test_a_call_that_always_asks_refuses_the_scope_with_422(
        self, client: AsyncClient
    ) -> None:
        with patch(DECIDE, new=AsyncMock(side_effect=ToolAlwaysAsksError())):
            resp = await client.post(
                f"{APPROVALS_BASE}/ap_1/decision",
                json={"decision": "approve", "scope": "always_tool"},
            )
        assert resp.status_code == 422
        assert resp.json()["message"] == (
            "This action always asks for approval and can't be set to always allow"
        )

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{APPROVALS_BASE}/ap_1/decision", json={"decision": "approve"}
        )
        assert resp.status_code == 401


class TestPostBatchDecision:
    """POST /api/v1/approvals/batch-decision."""

    @patch(BATCH, new_callable=AsyncMock)
    async def test_each_item_is_decided_and_reported(
        self, mock_batch: AsyncMock, client: AsyncClient
    ) -> None:
        mock_batch.return_value = [
            BatchDecisionOutcome(approval_id="ap_1", resolved=True),
            BatchDecisionOutcome(
                approval_id="ap_2", resolved=False, reason="not_found", outcome="expired"
            ),
        ]
        resp = await client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={
                "decisions": [
                    {"approval_id": "ap_1", "decision": "approve"},
                    {"approval_id": "ap_2", "decision": "deny", "feedback": "no"},
                ]
            },
        )
        assert resp.status_code == 200
        assert [o["resolved"] for o in resp.json()["outcomes"]] == [True, False]
        assert resp.json()["outcomes"][1]["outcome"] == "expired"
        mock_batch.assert_awaited_once_with(
            USER_ID,
            [
                BatchDecisionItem(approval_id="ap_1", decision="approve"),
                BatchDecisionItem(approval_id="ap_2", decision="deny", feedback="no"),
            ],
        )

    async def test_empty_decisions_is_rejected(self, client: AsyncClient) -> None:
        resp = await client.post(f"{APPROVALS_BASE}/batch-decision", json={"decisions": []})
        assert resp.status_code == 422

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{APPROVALS_BASE}/batch-decision",
            json={"decisions": [{"approval_id": "ap_1", "decision": "approve"}]},
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
    async def test_a_tool_name_that_is_not_an_id_is_refused_before_the_override(
        self, mock_set: AsyncMock, client: AsyncClient
    ):
        resp = await client.put(f"{APPROVALS_BASE}/tools/send email", json={"ask": True})
        assert resp.status_code == 422
        mock_set.assert_not_awaited()

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
    async def test_a_server_scoped_key_is_stored_exactly_as_sent(
        self, mock_set: AsyncMock, client: AsyncClient
    ):
        mock_set.return_value = _prefs(tool_overrides={"mcp:posthog:delete_item": False})
        resp = await client.put(
            f"{APPROVALS_BASE}/tools/mcp:posthog:delete_item", json={"ask": False}
        )
        assert resp.status_code == 200
        assert resp.json()["tool_overrides"] == {"mcp:posthog:delete_item": False}
        mock_set.assert_awaited_once_with(USER_ID, "mcp:posthog:delete_item", False)

    async def test_a_malformed_server_scoped_key_is_a_422_not_a_stored_bomb(
        self, client: AsyncClient
    ):
        with patch("app.services.hil.preferences.user_repository") as repo:
            repo.set_hil_tool_override = AsyncMock()
            resp = await client.put(f"{APPROVALS_BASE}/tools/mcp:posthog", json={"ask": False})
        assert resp.status_code == 422
        repo.set_hil_tool_override.assert_not_awaited()

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
