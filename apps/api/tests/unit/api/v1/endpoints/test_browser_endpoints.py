"""Tests for browser endpoints — logins, tasks, handoffs, live-view token."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from app.api.v1.endpoints import browser as browser_ep
from app.constants.browser import BrowserSessionStatus, HandoffDecision, HandoffStatus
from app.schemas.browser import (
    BrowserLoginResponse,
    BrowserTaskResponse,
    HandoffDecisionRequest,
    HandoffRecord,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_login(domain: str) -> BrowserLoginResponse:
    return BrowserLoginResponse(domain=domain, updated_at=datetime.now(UTC), expires_at=None)


def _make_task(task_id: str = "t1") -> BrowserTaskResponse:
    return BrowserTaskResponse(
        id=task_id,
        task="do thing",
        status=BrowserSessionStatus.COMPLETED,
        success=True,
        steps=2,
        created_at=datetime.now(UTC),
        conversation_id="c1",
        source="web",
        frames=[],
    )


# ---------------------------------------------------------------------------
# GET /browser/handoffs/{handoff_id}
# ---------------------------------------------------------------------------


class TestGetBrowserHandoff:
    async def test_success(self, monkeypatch):
        record = HandoffRecord(status=HandoffStatus.PENDING, user_id="u1", conversation_id="c1")
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock(return_value=record))
        resp = await browser_ep.get_browser_handoff("h1", {"user_id": "u1"})
        assert resp.handoff_id == "h1"
        assert resp.status == HandoffStatus.PENDING

    async def test_missing_user_id_400(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {})
        assert exc.value.status_code == 400

    async def test_none_user_id_400(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {"user_id": None})
        assert exc.value.status_code == 400

    async def test_not_found_returns_404(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {"user_id": "u1"})
        assert exc.value.status_code == 404

    async def test_wrong_owner_returns_404(self, monkeypatch):
        record = HandoffRecord(status=HandoffStatus.PENDING, user_id="owner", conversation_id="c1")
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock(return_value=record))
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {"user_id": "intruder"})
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# POST /browser/handoffs/{handoff_id}/decision
# ---------------------------------------------------------------------------


class TestDecideBrowserHandoff:
    async def test_continue_success(self, monkeypatch):
        monkeypatch.setattr(
            browser_ep, "resolve_handoff", AsyncMock(return_value=HandoffStatus.COMPLETED)
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        resp = await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert resp.status == HandoffStatus.COMPLETED
        assert resp.handoff_id == "h1"

    async def test_cancel_success(self, monkeypatch):
        monkeypatch.setattr(
            browser_ep, "resolve_handoff", AsyncMock(return_value=HandoffStatus.CANCELLED)
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL)
        resp = await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert resp.status == HandoffStatus.CANCELLED

    async def test_with_message_passed_through(self, monkeypatch):
        mock_resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
        monkeypatch.setattr(browser_ep, "resolve_handoff", mock_resolve)
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE, message="grab photo")
        await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        mock_resolve.assert_awaited_once_with("h1", HandoffDecision.CONTINUE, "u1", "grab photo")

    async def test_missing_user_id_400(self, monkeypatch):
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {})
        assert exc.value.status_code == 400

    async def test_not_owned_403(self, monkeypatch):
        from app.services.browser.exceptions import BrowserHandoffNotOwned

        async def _raise(*args, **kwargs):
            raise BrowserHandoffNotOwned("nope")

        monkeypatch.setattr(browser_ep, "resolve_handoff", _raise)
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert exc.value.status_code == 403

    async def test_expired_returns_410(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "resolve_handoff", AsyncMock(return_value=None))
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert exc.value.status_code == 410


# ---------------------------------------------------------------------------
# GET /browser/sessions/{session_id}/live-view-token
# ---------------------------------------------------------------------------


class TestGetLiveViewToken:
    async def test_owner_gets_token(self, monkeypatch):
        monkeypatch.setattr(browser_ep.registry, "session_owner", AsyncMock(return_value="u1"))
        monkeypatch.setattr(browser_ep, "create_takeover_token", lambda sid, uid: "tok123")
        monkeypatch.setattr(browser_ep, "verify_takeover_token", lambda tok: {"exp": 9999999999.0})
        monkeypatch.setattr(browser_ep, "takeover_token_ttl_seconds", lambda claims: 900)
        resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert resp.token == "tok123"
        assert resp.expires_in == 900

    async def test_negative_ttl_clamped_to_zero(self, monkeypatch):
        monkeypatch.setattr(browser_ep.registry, "session_owner", AsyncMock(return_value="u1"))
        monkeypatch.setattr(browser_ep, "create_takeover_token", lambda sid, uid: "tok")
        monkeypatch.setattr(browser_ep, "verify_takeover_token", lambda tok: {"exp": 0})
        monkeypatch.setattr(browser_ep, "takeover_token_ttl_seconds", lambda claims: -10)
        resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert resp.expires_in == 0

    async def test_non_owner_403(self, monkeypatch):
        monkeypatch.setattr(browser_ep.registry, "session_owner", AsyncMock(return_value="other"))
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert exc.value.status_code == 403

    async def test_unregistered_403(self, monkeypatch):
        monkeypatch.setattr(browser_ep.registry, "session_owner", AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert exc.value.status_code == 403

    async def test_missing_user_id_400(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {})
        assert exc.value.status_code == 400

    async def test_empty_user_id_400(self, monkeypatch):
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {"user_id": ""})
        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# GET /browser/tasks
# ---------------------------------------------------------------------------


class TestListBrowserTasksEndpoint:
    async def test_returns_tasks(self, monkeypatch):
        tasks = [_make_task("t1"), _make_task("t2")]
        monkeypatch.setattr(browser_ep, "list_browser_tasks", AsyncMock(return_value=tasks))
        result = await browser_ep.list_browser_tasks_endpoint("u1", limit=20)
        assert len(result) == 2
        assert result[0].id == "t1"

    async def test_empty(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "list_browser_tasks", AsyncMock(return_value=[]))
        result = await browser_ep.list_browser_tasks_endpoint("u1")
        assert result == []

    async def test_custom_limit(self, monkeypatch):
        mock_list = AsyncMock(return_value=[])
        monkeypatch.setattr(browser_ep, "list_browser_tasks", mock_list)
        await browser_ep.list_browser_tasks_endpoint("u1", limit=5)
        mock_list.assert_awaited_once_with("u1", limit=5)


# ---------------------------------------------------------------------------
# DELETE /browser/tasks/{task_id}
# ---------------------------------------------------------------------------


class TestDeleteBrowserTaskEndpoint:
    async def test_deletes(self, monkeypatch):
        mock_del = AsyncMock(return_value=True)
        monkeypatch.setattr(browser_ep, "delete_browser_task", mock_del)
        result = await browser_ep.delete_browser_task_endpoint("t1", "u1")
        assert result is None
        mock_del.assert_awaited_once_with("u1", "t1")

    async def test_calls_with_correct_ids(self, monkeypatch):
        mock_del = AsyncMock()
        monkeypatch.setattr(browser_ep, "delete_browser_task", mock_del)
        await browser_ep.delete_browser_task_endpoint("my-task", "my-user")
        mock_del.assert_awaited_once_with("my-user", "my-task")


# ---------------------------------------------------------------------------
# GET /browser/logins
# ---------------------------------------------------------------------------


class TestListBrowserLoginsEndpoint:
    async def test_returns_logins(self, monkeypatch):
        logins = [_make_login("example.com"), _make_login("google.com")]
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=logins))
        result = await browser_ep.list_browser_logins_endpoint("u1")
        assert len(result) == 2
        assert result[0].domain == "example.com"

    async def test_empty(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=[]))
        result = await browser_ep.list_browser_logins_endpoint("u1")
        assert result == []

    async def test_delegates_to_service(self, monkeypatch):
        mock_list = AsyncMock(return_value=[])
        monkeypatch.setattr(browser_ep, "list_saved_logins", mock_list)
        await browser_ep.list_browser_logins_endpoint("user-xyz")
        mock_list.assert_awaited_once_with("user-xyz")


# ---------------------------------------------------------------------------
# DELETE /browser/logins/{domain}
# ---------------------------------------------------------------------------


class TestForgetBrowserLoginEndpoint:
    async def test_forgets_domain(self, monkeypatch):
        mock_forget = AsyncMock(return_value=1)
        monkeypatch.setattr(browser_ep, "forget_saved_login", mock_forget)
        result = await browser_ep.forget_browser_login_endpoint("example.com", "u1")
        assert result is None
        mock_forget.assert_awaited_once_with("u1", "example.com")

    async def test_different_domain(self, monkeypatch):
        mock_forget = AsyncMock(return_value=1)
        monkeypatch.setattr(browser_ep, "forget_saved_login", mock_forget)
        await browser_ep.forget_browser_login_endpoint("google.com", "u1")
        mock_forget.assert_awaited_once_with("u1", "google.com")


# ---------------------------------------------------------------------------
# DELETE /browser/logins
# ---------------------------------------------------------------------------


class TestClearBrowserLoginsEndpoint:
    async def test_clears_all(self, monkeypatch):
        mock_forget = AsyncMock(return_value=3)
        monkeypatch.setattr(browser_ep, "forget_saved_login", mock_forget)
        result = await browser_ep.clear_browser_logins_endpoint("u1")
        assert result is None
        mock_forget.assert_awaited_once_with("u1", None)

    async def test_calls_with_none_domain(self, monkeypatch):
        mock_forget = AsyncMock(return_value=0)
        monkeypatch.setattr(browser_ep, "forget_saved_login", mock_forget)
        await browser_ep.clear_browser_logins_endpoint("user-abc")
        mock_forget.assert_awaited_once_with("user-abc", None)


# ---------------------------------------------------------------------------
# Router integration smoke — verify routes are registered
# ---------------------------------------------------------------------------


class TestRouterRegistration:
    def test_prefix_and_tags(self):
        assert browser_ep.router.prefix == "/browser"
        assert "Browser" in browser_ep.router.tags

    def test_routes_exist(self):
        paths = {route.path for route in browser_ep.router.routes}
        assert "/browser/handoffs/{handoff_id}" in paths
        assert "/browser/handoffs/{handoff_id}/decision" in paths
        assert "/browser/sessions/{session_id}/live-view-token" in paths
        assert "/browser/tasks" in paths
        assert "/browser/tasks/{task_id}" in paths
        assert "/browser/logins" in paths
        assert "/browser/logins/{domain}" in paths


class TestMintBrowserImportToken:
    async def test_owner_gets_a_token(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "mint_import_token", AsyncMock(return_value="tok-123"))
        resp = await browser_ep.mint_browser_import_token({"user_id": "u1"})
        assert resp.token == "tok-123"
        assert resp.expires_in_seconds > 0

    async def test_missing_user_id_400(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "mint_import_token", AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await browser_ep.mint_browser_import_token({})
        assert exc.value.status_code == 400


class TestImportBrowserSessions:
    def _payload(self, token="tok"):
        from app.schemas.browser import BrowserImportRequest

        return BrowserImportRequest(
            token=token,
            cookies=[{"name": "s", "value": "1", "domain": ".github.com"}],
        )

    async def test_valid_token_imports_and_reports_hosts(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value="u1"))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", True)
        imp = AsyncMock(return_value=[("github.com", 1)])
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)

        resp = await browser_ep.import_browser_sessions(self._payload())

        assert resp.host_count == 1
        assert resp.imported[0].domain == "github.com"
        # The route must hand the service a real user id from the consumed token.
        assert imp.await_args.args[0] == "u1"

    async def test_bad_token_401(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value=None))
        imp = AsyncMock()
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.import_browser_sessions(self._payload("expired"))
        assert exc.value.status_code == 401
        imp.assert_not_awaited()  # never touch storage on a bad code

    async def test_persistence_disabled_409(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "consume_import_token", AsyncMock(return_value="u1"))
        monkeypatch.setattr(browser_ep.settings, "BROWSER_PERSIST_LOGINS", False)
        imp = AsyncMock()
        monkeypatch.setattr(browser_ep, "import_browser_profile", imp)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.import_browser_sessions(self._payload())
        assert exc.value.status_code == 409
        imp.assert_not_awaited()


class TestForgetAllBrowserLogins:
    async def test_returns_the_count_forgotten(self, monkeypatch):
        monkeypatch.setattr(browser_ep, "forget_saved_login", AsyncMock(return_value=7))
        resp = await browser_ep.forget_all_browser_logins_endpoint("u1")
        assert resp.forgotten == 7

    async def test_forgets_everything_not_one_domain(self, monkeypatch):
        forget = AsyncMock(return_value=0)
        monkeypatch.setattr(browser_ep, "forget_saved_login", forget)
        await browser_ep.forget_all_browser_logins_endpoint("u1")
        # domain=None is what makes it clear ALL, not a single site.
        assert forget.await_args.args == ("u1", None)
