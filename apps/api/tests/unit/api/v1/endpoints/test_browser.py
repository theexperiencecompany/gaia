"""Cover observability and contract details for app/api/v1/endpoints/browser.py.

test_browser_endpoints.py pins happy paths and HTTP status codes. This file pins
what those tests do not assert on: exact error text, wide-event context, audit
trail, and exact arguments passed to each service seam.

Wide-event fields are read back through a real boundary, captured_wide_event,
since log.set is discarded outside a boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from annotated_types import Ge, Le
import fakeredis.aioredis
from fastapi import HTTPException
from httpx import AsyncClient
import pytest
from tests.conftest import FAKE_USER
from tests.helpers import captured_wide_event

from app.api.v1.dependencies.oauth_dependencies import get_user_id
from app.api.v1.endpoints import browser as browser_ep, browser_live_view as live_view_ep
from app.constants.browser import (
    BROWSER_HANDOFF_ACK_CANCEL,
    BROWSER_HANDOFF_ACK_CONTINUE,
    BROWSER_HANDOFF_GONE_DETAIL,
    BROWSER_HANDOFF_NOT_OWNED_DETAIL,
    BROWSER_LIVE_VIEW_NOT_WAITING_DETAIL,
    BrowserSessionStatus,
    HandoffDecision,
    HandoffKind,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import (
    BrowserLoginResponse,
    BrowserTaskResponse,
    HandoffDecisionRequest,
    HandoffRecord,
    NewHandoff,
)
from app.services.browser import handoff_buttons
from app.services.browser.handoff import cancel_handoff, create_pending_handoff, get_handoff
from app.services.browser.live_code import mint_live_code

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _SinkRecorder:
    """Stand in for the loguru sink so real-time lines become assertable.

    log.info and log.audit write through the module-level _loguru global;
    patching it is the only way to see the info line, which never reaches
    the wide event.
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
        """Return the (message, bound fields) pairs emitted at level."""
        return [(msg, fields) for lvl, msg, fields in self.lines if lvl == level]


@asynccontextmanager
async def _recorded() -> AsyncIterator[tuple[dict[str, Any], _SinkRecorder]]:
    """Return a real wide-event boundary plus a capture of the real-time log lines."""
    recorder = _SinkRecorder()
    with patch("shared.py.wide_events._loguru", recorder):
        async with captured_wide_event() as event:
            yield event, recorder


def _make_login(domain: str) -> BrowserLoginResponse:
    return BrowserLoginResponse(
        domain=domain,
        updated_at=datetime.now(UTC),
        expires_at=None,
        source=None,
        source_browser=None,
        source_ip=None,
    )


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
    return HandoffRecord(status=status, user_id=user_id, conversation_id="c1", job_id="job-1")


# ---------------------------------------------------------------------------
# A handoff decided by a button: the web card's, or the bot live-view page's
# ---------------------------------------------------------------------------


@pytest.fixture
async def button_world(
    fake_redis: fakeredis.aioredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, str, str]]:
    """Open a pending login handoff in c1 over fakeredis; return what reaches the agent's thread."""
    recorded: list[tuple[str, str, str]] = []

    async def _record(conversation_id: str, user_message: str, reply: str) -> None:
        recorded.append((conversation_id, user_message, reply))

    monkeypatch.setattr(handoff_buttons, "record_exchange_in_thread", _record)
    await create_pending_handoff(
        "h1",
        NewHandoff(
            job_id="job-1", user_id="u1", conversation_id="c1", reason="Sign in", reply_to="c1"
        ),
    )
    return recorded


class TestDecideBrowserHandoff:
    async def test_the_cards_decision_settles_it_and_reaches_the_agents_thread(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        """No turn runs for a tap: without the thread entry the agent's reply called the user's own note a mistake."""
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE, message="skip it")

        async with captured_wide_event() as event:
            resp = await browser_ep.decide_browser_handoff("h1", payload, "u1")

        assert (resp.handoff_id, resp.status) == ("h1", HandoffStatus.COMPLETED)
        assert event["user"] == {"id": "u1"}
        assert event["browser"] == {
            "handoff_id": "h1",
            "decision": "continue",
            "handoff_status": "completed",
        }
        record = await get_handoff("h1")
        assert record is not None
        assert record.message == "skip it"
        assert button_world == [
            (
                "c1",
                "[From the browser handoff card] continue: skip it",
                BROWSER_HANDOFF_ACK_CONTINUE,
            )
        ]

    async def test_a_tap_after_it_was_settled_another_way_decided_nothing(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        await cancel_handoff("h1")
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)

        resp = await browser_ep.decide_browser_handoff("h1", payload, "u1")

        assert resp.status is HandoffStatus.CANCELLED
        assert button_world == []

    async def test_a_pause_for_the_agent_is_never_written_as_the_users_words(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        await create_pending_handoff(
            "h-agent",
            NewHandoff(
                job_id="job-1",
                user_id="u1",
                conversation_id="c1",
                reason="stuck",
                kind=HandoffKind.AGENT,
            ),
        )
        payload = HandoffDecisionRequest(decision=HandoffDecision.CONTINUE, message="go")

        await browser_ep.decide_browser_handoff("h-agent", payload, "u1")

        assert button_world == []

    @pytest.mark.parametrize(
        ("handoff_id", "user_id", "code", "detail"),
        [
            ("h1", "intruder", 403, BROWSER_HANDOFF_NOT_OWNED_DETAIL),
            ("gone", "u1", 410, BROWSER_HANDOFF_GONE_DETAIL),
        ],
    )
    async def test_another_users_or_a_gone_handoff_is_refused(
        self,
        button_world: list[tuple[str, str, str]],
        handoff_id: str,
        user_id: str,
        code: int,
        detail: str,
    ) -> None:
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL)

        with pytest.raises(HTTPException) as exc:
            await browser_ep.decide_browser_handoff(handoff_id, payload, user_id)

        assert (exc.value.status_code, exc.value.detail) == (code, detail)
        assert button_world == []

    async def test_the_live_pages_stop_decides_the_handoff_its_link_was_sent_for(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        """A bot user has no web session: the code that opened the page is the authority, and only for its own handoff."""
        code = await mint_live_code("sess-1", "u1", "h1")
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL)

        async with captured_wide_event() as event:
            resp = await live_view_ep.decide_live_view_handoff(code, payload)

        assert (resp.handoff_id, resp.status) == ("h1", HandoffStatus.CANCELLED)
        assert event["user"] == {"id": "u1"}
        assert event["browser"] == {
            "operation": "live_view_decision",
            "decision": "cancel",
            "handoff_id": "h1",
            "handoff_status": "cancelled",
        }
        record = await get_handoff("h1")
        assert record is not None
        assert record.message is None
        assert button_world == [
            ("c1", "[From the browser handoff card] cancel", BROWSER_HANDOFF_ACK_CANCEL)
        ]
        # Settled, the link no longer opens anything.
        with pytest.raises(HTTPException) as exc:
            await live_view_ep.decide_live_view_handoff(code, payload)
        assert (exc.value.status_code, exc.value.detail) == (
            404,
            BROWSER_LIVE_VIEW_NOT_WAITING_DETAIL,
        )

    async def test_the_live_pages_note_reaches_the_handoff_and_the_thread(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        """What the user types on the live page travels with the decision, as a chat reply's note does."""
        code = await mint_live_code("sess-1", "u1", "h1")
        payload = HandoffDecisionRequest(decision=HandoffDecision.CANCEL, message="wrong account")

        await live_view_ep.decide_live_view_handoff(code, payload)

        record = await get_handoff("h1")
        assert record is not None
        assert record.message == "wrong account"
        assert button_world == [
            (
                "c1",
                "[From the browser handoff card] cancel: wrong account",
                BROWSER_HANDOFF_ACK_CANCEL,
            )
        ]

    async def test_a_live_page_whose_handoff_expired_says_it_is_gone(
        self, button_world: list[tuple[str, str, str]]
    ) -> None:
        code = await mint_live_code("sess-1", "u1", "expired")

        with pytest.raises(HTTPException) as exc:
            await live_view_ep.decide_live_view_handoff(
                code, HandoffDecisionRequest(decision=HandoffDecision.CONTINUE)
            )

        assert (exc.value.status_code, exc.value.detail) == (410, BROWSER_HANDOFF_GONE_DETAIL)


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
    async def test_foreign_session_says_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner="someone-else")
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", "u1")
        assert exc.value.detail == "Not authorized for this session"

    async def test_unregistered_session_says_not_authorized(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner=None)
        with pytest.raises(HTTPException) as exc:
            await browser_ep.get_live_view_token("sess-1", "u1")
        assert exc.value.detail == "Not authorized for this session"

    async def test_no_token_is_minted_for_a_foreign_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create, _verify, _ttl = _patch_token_seams(monkeypatch, owner="someone-else")
        with pytest.raises(HTTPException):
            await browser_ep.get_live_view_token("sess-1", "u1")
        assert create.call_args is None

    async def test_token_is_scoped_to_the_session_and_its_owner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        create, _verify, _ttl = _patch_token_seams(monkeypatch, owner="user-9")
        await browser_ep.get_live_view_token("sess-abc", "user-9")
        assert create.call_args == call("sess-abc", "user-9")

    async def test_expiry_is_read_back_from_the_token_that_was_minted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        claims = {"exp": 123.0, "session_id": "sess-1"}
        _create, verify, ttl_fn = _patch_token_seams(
            monkeypatch, token="minted-tok", claims=claims, ttl=42.0
        )
        resp = await browser_ep.get_live_view_token("sess-1", "u1")
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
        await browser_ep.get_live_view_token("sess-xyz", "u1")
        assert owner_lookup.await_args == call("sess-xyz")

    async def test_fractional_ttl_is_truncated_to_whole_seconds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, ttl=899.9)
        resp = await browser_ep.get_live_view_token("sess-1", "u1")
        assert resp.expires_in == 899

    async def test_already_expired_token_reports_zero_not_a_negative(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, ttl=-0.5)
        resp = await browser_ep.get_live_view_token("sess-1", "u1")
        assert resp.expires_in == 0

    async def test_wide_event_carries_session_and_operation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch)
        async with _recorded() as (event, recorder):
            await browser_ep.get_live_view_token("sess-1", "u1")
            assert event["user"] == {"id": "u1"}
            assert event["browser"] == {"session_id": "sess-1", "operation": "live_view_token"}
            assert recorder.at("INFO") == [(f"{LogTag.BROWSER} browser live view token issued", {})]

    async def test_denied_request_is_not_logged_as_an_issued_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_token_seams(monkeypatch, owner=None)
        async with _recorded() as (_event, recorder):
            with pytest.raises(HTTPException):
                await browser_ep.get_live_view_token("sess-1", "u1")
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


# ---------------------------------------------------------------------------
# The authenticated user through the real dependency (not a hand-made dict)
# ---------------------------------------------------------------------------


class TestAuthenticatedUserThroughTheApp:
    """get_current_user yields an AuthenticatedUser, never a dict.

    These go through the mounted app so the real dependency result reaches the
    handler; a handler that treats it as a mapping 500s here and nowhere else.
    """

    async def test_decision_with_a_note_returns_200_and_forwards_the_note(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resolve = AsyncMock(return_value=HandoffStatus.COMPLETED)
        monkeypatch.setattr(browser_ep, "decide_handoff_by_button", resolve)

        resp = await client.post(
            "/api/v1/browser/handoffs/h-1/decision",
            json={"decision": "continue", "message": "skip the login"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"handoff_id": "h-1", "status": "completed"}
        assert resolve.await_args == call(
            "h-1", HandoffDecision.CONTINUE, FAKE_USER.user_id, "skip the login"
        )

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/browser/handoffs/{handoff_id}/decision", "POST"),
            ("/browser/sessions/{session_id}/live-view-token", "GET"),
            ("/browser/import/token", "POST"),
        ],
    )
    def test_user_id_comes_from_the_auth_dependency(self, path: str, method: str) -> None:
        """A route resolving its own id from request.state is how the 500s got in."""
        route = next(r for r in browser_ep.router.routes if r.path == path and method in r.methods)
        assert [d.call for d in route.dependant.dependencies] == [get_user_id]
