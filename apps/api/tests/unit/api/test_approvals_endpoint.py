"""Unit tests for the HIL approval API endpoints.

Covers the decision relay (single + batch) and the per-user preferences
read/update routes. Service layer is mocked; HTTP status codes, response
shapes, payload forwarding, and the AppError status mapping are verified.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.models.hil_models import HILMode, HILPreferences
from app.schemas.hil_schemas import BatchDecisionOutcome
from app.services.hil.resolution import (
    ApprovalNotResumableError,
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)

APPROVALS_BASE = "/api/v1/approvals"
USER_ID = "507f1f77bcf86cd799439011"


def _prefs(
    mode: HILMode = "always_allow", tool_overrides: dict[str, bool] | None = None
) -> HILPreferences:
    return HILPreferences(mode=mode, tool_overrides=tool_overrides or {})


# ---------------------------------------------------------------------------
# POST /approvals/{approval_id}/decision
# ---------------------------------------------------------------------------


class TestPostApprovalDecision:
    """POST /api/v1/approvals/{id}/decision"""

    @patch("app.api.v1.endpoints.approvals.resolve_approval", new_callable=AsyncMock)
    async def test_decision_success(self, mock_resolve: AsyncMock, client: AsyncClient):
        resp = await client.post(
            f"{APPROVALS_BASE}/a1/decision",
            json={"decision": "approve", "feedback": "looks good", "scope": "always_tool"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
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
        assert resp.json() == {"success": True}
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
    """POST /api/v1/approvals/batch-decision"""

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
        assert outcomes[1] == {"approval_id": "a2", "resolved": False, "reason": "not_found"}

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
    """GET /api/v1/approvals/preferences"""

    @patch("app.api.v1.endpoints.approvals.get_hil_preferences", new_callable=AsyncMock)
    async def test_default_preferences(self, mock_get: AsyncMock, client: AsyncClient):
        mock_get.return_value = _prefs()
        resp = await client.get(f"{APPROVALS_BASE}/preferences")
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
    """PUT /api/v1/approvals/preferences"""

    @patch("app.api.v1.endpoints.approvals.update_hil_preferences", new_callable=AsyncMock)
    async def test_partial_update(self, mock_update: AsyncMock, client: AsyncClient):
        mock_update.return_value = _prefs(mode="always_ask")
        resp = await client.put(f"{APPROVALS_BASE}/preferences", json={"mode": "always_ask"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "always_ask"
        mock_update.assert_awaited_once_with(USER_ID, mode="always_ask", tool_overrides=None)

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
            USER_ID, mode=None, tool_overrides={"email_send": False}
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
    """PUT /api/v1/approvals/tools/{tool_name}"""

    @patch("app.api.v1.endpoints.approvals.set_tool_override", new_callable=AsyncMock)
    async def test_force_ask(self, mock_set: AsyncMock, client: AsyncClient):
        mock_set.return_value = _prefs(mode="auto", tool_overrides={"email_send": True})
        resp = await client.put(f"{APPROVALS_BASE}/tools/email_send", json={"ask": True})
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
