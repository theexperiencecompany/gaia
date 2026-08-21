"""Observability + contract coverage for app/api/v1/endpoints/browser.py

``tests/unit/api/v1/endpoints/test_browser_endpoints.py`` already pins the
happy paths and the HTTP status codes of every route in this module. What it
does not pin is everything *else* these thin handlers exist to do: the exact
error text the card shows the user, the wide-event context an operator greps
for, the audit trail a login deletion leaves behind, and the precise arguments
handed to each service seam. Those lines run in the existing tests but nothing
asserts on them, so they could all be wrong and the suite would stay green.

This file closes that gap. Wide-event fields are read back through a real
boundary (``captured_wide_event``) rather than by mocking ``log`` — outside a
boundary every ``log.set`` is discarded by design, so a mocked logger would
prove nothing about what actually reaches Loki.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from annotated_types import Ge, Le
from fastapi import HTTPException
import pytest
from tests.helpers import captured_wide_event

from app.api.v1.endpoints import browser as browser_ep
from app.constants.browser import BrowserSessionStatus, HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserLoginResponse,
    BrowserTaskResponse,
    HandoffDecisionRequest,
    HandoffRecord,
)
from app.services.browser.exceptions import BrowserHandoffNotOwned

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _SinkRecorder:
    """Stand-in for the loguru sink so real-time lines become assertable.

    ``log.info``/``log.audit`` write a real-time line through the module-level
    ``_loguru`` and (for audit) also append to the wide event. Patching that
    one global is the only way to see the message text and bound fields of the
    info line, which is otherwise deliberately absent from the event.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict[str, Any]]] = []
        self._bound: dict[str, Any] = {}

    def opt(self, **_kwargs: Any) -> _SinkRecorder:
        return self

    def bind(self, **kwargs: Any) -> _SinkRecorder:
        self._bound = kwargs
        return self

    def info(self, message: str) -> None:
        self.lines.append(("INFO", message, dict(self._bound)))

    def log(self, level: str, message: str) -> None:
        self.lines.append((level, message, dict(self._bound)))

    def __getattr__(self, name: str) -> Any:
        return lambda *_a, **_k: None

    def at(self, level: str) -> list[tuple[str, dict[str, Any]]]:
        """(message, bound fields) for every line emitted at ``level``."""
        return [(msg, fields) for lvl, msg, fields in self.lines if lvl == level]


@asynccontextmanager
async def _recorded() -> AsyncIterator[tuple[dict[str, Any], _SinkRecorder]]:
    """A real wide-event boundary plus a capture of the real-time log lines."""
    recorder = _SinkRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        async with captured_wide_event() as event:
            yield event, recorder


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


def _record(status: HandoffStatus = HandoffStatus.PENDING, user_id: str = "u1") -> HandoffRecord:
    return HandoffRecord(status=status, user_id=user_id, conversation_id="c1")


# ---------------------------------------------------------------------------
# GET /browser/handoffs/{handoff_id}
# ---------------------------------------------------------------------------


class TestGetBrowserHandoffContract:
    async def test_missing_user_id_explains_why(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {})
        assert exc.value.detail == "User id required"

    async def test_unknown_handoff_says_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock(return_value=None))
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {"user_id": "u1"})
        assert exc.value.detail == "Handoff not found"

    async def test_another_users_handoff_is_indistinguishable_from_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "get_handoff", AsyncMock(return_value=_record(user_id="owner"))
        )
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_browser_handoff("h1", {"user_id": "intruder"})
        assert exc.value.detail == "Handoff not found"

    async def test_looks_up_the_requested_handoff_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_handoff = AsyncMock(return_value=_record())
        monkeypatch.setattr(browser_ep, "get_handoff", get_handoff)
        await browser_ep.get_browser_handoff("handoff-42", {"user_id": "u1"})
        assert get_handoff.await_args == call("handoff-42")

    @pytest.mark.parametrize(
        "handoff_status",
        [HandoffStatus.PENDING, HandoffStatus.COMPLETED, HandoffStatus.CANCELLED],
    )
    async def test_reports_the_stored_status_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, handoff_status: HandoffStatus
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "get_handoff", AsyncMock(return_value=_record(status=handoff_status))
        )
        resp = await browser_ep.get_browser_handoff("h1", {"user_id": "u1"})
        assert (resp.handoff_id, resp.status) == ("h1", handoff_status)

    async def test_wide_event_carries_user_and_handoff(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "get_handoff", AsyncMock(return_value=_record()))
        async with _recorded() as (event, _recorder):
            await browser_ep.get_browser_handoff("h1", {"user_id": "u1"})
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"handoff_id": "h1"}

    async def test_rejected_request_never_reaches_the_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        get_handoff = AsyncMock(return_value=_record())
        monkeypatch.setattr(browser_ep, "get_handoff", get_handoff)
        with pytest.raises(HTTPException):
            await browser_ep.get_browser_handoff("h1", {"user_id": None})
        assert get_handoff.await_args is None


# ---------------------------------------------------------------------------
# POST /browser/handoffs/{handoff_id}/decision
# ---------------------------------------------------------------------------


class TestDecideBrowserHandoffContract:
    async def test_missing_user_id_explains_why(self) -> None:
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": ""})
        assert exc.value.detail == "User id required"

    async def test_foreign_handoff_says_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep,
            "resolve_handoff",
            AsyncMock(side_effect=BrowserHandoffNotOwned("nope")),
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert exc.value.detail == "Not authorized to resolve this handoff"

    async def test_ownership_failure_keeps_the_cause_attached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cause = BrowserHandoffNotOwned("nope")
        monkeypatch.setattr(browser_ep, "resolve_handoff", AsyncMock(side_effect=cause))
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert exc.value.__cause__ is cause

    async def test_expired_handoff_explains_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_ep, "resolve_handoff", AsyncMock(return_value=None))
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert exc.value.detail == "Handoff not found or expired"

    async def test_omitted_note_reaches_the_service_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
        monkeypatch.setattr(browser_ep, "resolve_handoff", resolve)
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL)
        await browser_ep.decide_browser_handoff("h-9", payload, {"user_id": "u7"})
        assert resolve.await_args == call("h-9", HandoffDecision.CANCEL, "u7", None)

    async def test_service_outcome_wins_over_the_requested_decision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "resolve_handoff", AsyncMock(return_value=HandoffStatus.CANCELLED)
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        resp = await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
        assert (resp.handoff_id, resp.status) == ("h1", HandoffStatus.CANCELLED)

    @pytest.mark.parametrize(
        ("decision", "expected"),
        [(HandoffDecision.CONTINUE, "continue"), (HandoffDecision.CANCEL, "cancel")],
    )
    async def test_wide_event_carries_user_handoff_and_decision(
        self, monkeypatch: pytest.MonkeyPatch, decision: HandoffDecision, expected: str
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "resolve_handoff", AsyncMock(return_value=HandoffStatus.COMPLETED)
        )
        payload = HandoffDecisionRequest(decision=decision)
        async with _recorded() as (event, _recorder):
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"handoff_id": "h1", "decision": expected}

    async def test_resolution_is_announced_with_the_final_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "resolve_handoff", AsyncMock(return_value=HandoffStatus.CANCELLED)
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL)
        async with _recorded() as (_event, recorder):
            await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
            assert recorder.at("INFO") == [
                (
                    f"{LogTag.BROWSER} Browser handoff decided",
                    {"handoff_id": "h1", "status": "cancelled"},
                )
            ]

    async def test_expired_handoff_is_not_announced_as_decided(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "resolve_handoff", AsyncMock(return_value=None))
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
        async with _recorded() as (_event, recorder):
            with pytest.raises(HTTPException):
                await browser_ep.decide_browser_handoff("h1", payload, {"user_id": "u1"})
            assert recorder.at("INFO") == []


# ---------------------------------------------------------------------------
# GET /browser/sessions/{session_id}/live-view-token
# ---------------------------------------------------------------------------


def _patch_token_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: str | None = "u1",
    ttl: float = 900.0,
    token: str = "tok123",
    claims: dict[str, Any] | None = None,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Mock the registry + token seams; return (create, verify, ttl) mocks."""
    resolved_claims = claims if claims is not None else {"exp": 9999999999.0}
    create = MagicMock(return_value=token)
    verify = MagicMock(return_value=resolved_claims)
    ttl_fn = MagicMock(return_value=ttl)
    monkeypatch.setattr(browser_ep.registry, "session_owner", AsyncMock(return_value=owner))
    monkeypatch.setattr(browser_ep, "create_takeover_token", create)
    monkeypatch.setattr(browser_ep, "verify_takeover_token", verify)
    monkeypatch.setattr(browser_ep, "takeover_token_ttl_seconds", ttl_fn)
    return create, verify, ttl_fn


class TestGetLiveViewTokenContract:
    async def test_missing_user_id_explains_why(self) -> None:
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {})
        assert exc.value.detail == "User id required"

    async def test_foreign_session_says_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner="someone-else")
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert exc.value.detail == "Not authorized for this session"

    async def test_unregistered_session_says_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner=None)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert exc.value.detail == "Not authorized for this session"

    async def test_no_token_is_minted_for_a_foreign_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create, _verify, _ttl = _patch_token_seams(monkeypatch, owner="someone-else")
        with pytest.raises(HTTPException):
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert create.call_args is None

    async def test_token_is_scoped_to_the_session_and_its_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create, _verify, _ttl = _patch_token_seams(monkeypatch, owner="user-9")
        await browser_ep.get_live_view_token("sess-abc", {"user_id": "user-9"})
        assert create.call_args == call("sess-abc", "user-9")

    async def test_expiry_is_read_back_from_the_token_that_was_minted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        claims = {"exp": 123.0, "session_id": "sess-1"}
        _create, verify, ttl_fn = _patch_token_seams(
            monkeypatch, token="minted-tok", claims=claims, ttl=42.0
        )
        resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert verify.call_args == call("minted-tok")
        assert ttl_fn.call_args == call(claims)
        assert (resp.token, resp.expires_in) == ("minted-tok", 42)

    async def test_ownership_is_checked_against_the_requested_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner_lookup = AsyncMock(return_value="u1")
        monkeypatch.setattr(browser_ep.registry, "session_owner", owner_lookup)
        monkeypatch.setattr(browser_ep, "create_takeover_token", MagicMock(return_value="tok"))
        monkeypatch.setattr(browser_ep, "verify_takeover_token", MagicMock(return_value={}))
        monkeypatch.setattr(browser_ep, "takeover_token_ttl_seconds", MagicMock(return_value=1.0))
        await browser_ep.get_live_view_token("sess-xyz", {"user_id": "u1"})
        assert owner_lookup.await_args == call("sess-xyz")

    async def test_fractional_ttl_is_truncated_to_whole_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, ttl=899.9)
        resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert resp.expires_in == 899

    async def test_already_expired_token_reports_zero_not_a_negative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, ttl=-0.5)
        resp = await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
        assert resp.expires_in == 0

    async def test_wide_event_carries_session_and_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch)
        async with _recorded() as (event, recorder):
            await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"session_id": "sess-1", "operation": "live_view_token"}
            assert recorder.at("INFO") == [(f"{LogTag.BROWSER} browser live view token issued", {})]

    async def test_denied_request_is_not_logged_as_an_issued_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner=None)
        async with _recorded() as (_event, recorder):
            with pytest.raises(HTTPException):
                await browser_ep.get_live_view_token("sess-1", {"user_id": "u1"})
            assert recorder.at("INFO") == []


# ---------------------------------------------------------------------------
# GET /browser/tasks
# ---------------------------------------------------------------------------


class TestListBrowserTasksContract:
    async def test_default_limit_is_twenty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        list_tasks = AsyncMock(return_value=[])
        monkeypatch.setattr(browser_ep, "list_browser_tasks", list_tasks)
        await browser_ep.list_browser_tasks_endpoint("u1")
        assert list_tasks.await_args == call("u1", limit=20)

    async def test_returns_the_service_result_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tasks = [_make_task("t1"), _make_task("t2")]
        monkeypatch.setattr(browser_ep, "list_browser_tasks", AsyncMock(return_value=tasks))
        result = await browser_ep.list_browser_tasks_endpoint("u1", limit=20)
        assert [task.id for task in result] == ["t1", "t2"]

    async def test_wide_event_records_operation_and_result_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tasks = [_make_task("t1"), _make_task("t2"), _make_task("t3")]
        monkeypatch.setattr(browser_ep, "list_browser_tasks", AsyncMock(return_value=tasks))
        async with _recorded() as (event, _recorder):
            await browser_ep.list_browser_tasks_endpoint("u1", limit=20)
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"operation": "list_tasks", "result_count": 3}

    async def test_empty_history_records_a_zero_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "list_browser_tasks", AsyncMock(return_value=[]))
        async with _recorded() as (event, _recorder):
            await browser_ep.list_browser_tasks_endpoint("u1")
            assert event["browser"]["result_count"] == 0


# ---------------------------------------------------------------------------
# DELETE /browser/tasks/{task_id}
# ---------------------------------------------------------------------------


class TestDeleteBrowserTaskContract:
    async def test_wide_event_records_operation_and_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "delete_browser_task", AsyncMock())
        async with _recorded() as (event, _recorder):
            await browser_ep.delete_browser_task_endpoint("task-7", "u1")
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"operation": "delete_task", "task_id": "task-7"}

    async def test_service_failure_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            browser_ep, "delete_browser_task", AsyncMock(side_effect=RuntimeError("mongo down"))
        )
        with pytest.raises(RuntimeError, match="mongo down"):
            await browser_ep.delete_browser_task_endpoint("t1", "u1")


# ---------------------------------------------------------------------------
# GET /browser/logins
# ---------------------------------------------------------------------------


class TestListBrowserLoginsContract:
    async def test_wide_event_records_the_operation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=[]))
        async with _recorded() as (event, _recorder):
            await browser_ep.list_browser_logins_endpoint("u1")
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"operation": "list_logins"}

    async def test_listing_leaves_an_audit_entry_with_the_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logins = [_make_login("example.com"), _make_login("google.com")]
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=logins))
        async with _recorded() as (event, recorder):
            await browser_ep.list_browser_logins_endpoint("u1")
            assert event["audit"] == [
                {
                    "msg": "browser logins listed",
                    "actor": "u1",
                    "resource": "browser/logins",
                    "count": 2,
                }
            ]
            assert recorder.at("AUDIT")[0][0] == "browser logins listed"

    async def test_audit_count_tracks_an_empty_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=[]))
        async with _recorded() as (event, _recorder):
            await browser_ep.list_browser_logins_endpoint("u1")
            assert event["audit"][0]["count"] == 0

    async def test_returns_the_domains_the_service_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        logins = [_make_login("example.com"), _make_login("google.com")]
        monkeypatch.setattr(browser_ep, "list_saved_logins", AsyncMock(return_value=logins))
        result = await browser_ep.list_browser_logins_endpoint("u1")
        assert [login.domain for login in result] == ["example.com", "google.com"]


# ---------------------------------------------------------------------------
# DELETE /browser/logins/{domain}
# ---------------------------------------------------------------------------


class TestForgetBrowserLoginContract:
    async def test_wide_event_records_operation_and_domain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "forget_saved_login", AsyncMock())
        async with _recorded() as (event, _recorder):
            await browser_ep.forget_browser_login_endpoint("example.com", "u1")
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"operation": "forget_login", "domain": "example.com"}

    async def test_audit_entry_names_the_domain_as_the_resource(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "forget_saved_login", AsyncMock())
        async with _recorded() as (event, recorder):
            await browser_ep.forget_browser_login_endpoint("github.com", "u1")
            assert event["audit"] == [
                {"msg": "browser login forgotten", "actor": "u1", "resource": "github.com"}
            ]
            assert recorder.at("AUDIT")[0][0] == "browser login forgotten"

    async def test_failed_deletion_is_not_audited_as_done(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "forget_saved_login", AsyncMock(side_effect=RuntimeError("mongo down"))
        )
        async with _recorded() as (event, _recorder):
            with pytest.raises(RuntimeError, match="mongo down"):
                await browser_ep.forget_browser_login_endpoint("github.com", "u1")
            assert "audit" not in event


# ---------------------------------------------------------------------------
# DELETE /browser/logins
# ---------------------------------------------------------------------------


class TestClearBrowserLoginsContract:
    async def test_wide_event_records_the_operation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(browser_ep, "forget_saved_login", AsyncMock())
        async with _recorded() as (event, _recorder):
            await browser_ep.clear_browser_logins_endpoint("u1")
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"operation": "clear_logins"}

    async def test_clearing_leaves_a_collection_scoped_audit_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(browser_ep, "forget_saved_login", AsyncMock())
        async with _recorded() as (event, recorder):
            await browser_ep.clear_browser_logins_endpoint("user-abc")
            assert event["audit"] == [
                {"msg": "browser logins cleared", "actor": "user-abc", "resource": "browser/logins"}
            ]
            assert recorder.at("AUDIT")[0][0] == "browser logins cleared"

    async def test_failed_clear_is_not_audited_as_done(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            browser_ep, "forget_saved_login", AsyncMock(side_effect=RuntimeError("mongo down"))
        )
        async with _recorded() as (event, _recorder):
            with pytest.raises(RuntimeError, match="mongo down"):
                await browser_ep.clear_browser_logins_endpoint("u1")
            assert "audit" not in event


# ---------------------------------------------------------------------------
# Route metadata — the decorators are part of the contract the web app sees
# ---------------------------------------------------------------------------


class TestRouteMetadata:
    def _route(self, path: str, method: str) -> Any:
        for route in browser_ep.router.routes:
            if route.path == path and method in route.methods:
                return route
        raise AssertionError(f"no {method} route for {path}")

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/browser/tasks/{task_id}", "DELETE"),
            ("/browser/logins/{domain}", "DELETE"),
            ("/browser/logins", "DELETE"),
        ],
    )
    def test_deletions_answer_204(self, path: str, method: str) -> None:
        assert self._route(path, method).status_code == 204

    def test_reads_and_writes_use_the_expected_methods(self) -> None:
        assert self._route("/browser/handoffs/{handoff_id}", "GET") is not None
        assert self._route("/browser/handoffs/{handoff_id}/decision", "POST") is not None
        assert self._route("/browser/sessions/{session_id}/live-view-token", "GET") is not None
        assert self._route("/browser/tasks", "GET") is not None
        assert self._route("/browser/logins", "GET") is not None

    def test_task_limit_is_bounded_between_one_and_a_hundred(self) -> None:
        limit = self._route("/browser/tasks", "GET").dependant.query_params[0]
        assert limit.name == "limit"
        assert limit.default == 20
        constraints = {type(m): m for m in limit.field_info.metadata}
        assert constraints[Ge].ge == 1
        assert constraints[Le].le == 100
