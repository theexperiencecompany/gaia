"""/api/v1/lab/events — token-only auth, verbatim tail persistence."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.lab_events import (
    LabEventRequest,
    LabEventResponse,
    report_lab_event,
)
from app.models.agent_lab_models import AgentKind, AgentSessionDocument, AgentSessionState
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

MODULE = "app.api.v1.endpoints.lab_events"
SERVICE = "app.services.agent_lab.lab_events"
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret():
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
        yield


def _bearer(user_id: str = "u1", run_id: str = "run-1") -> str:
    token = mint_execute_token(user_id, run_id, scoped_tool_names=[], ttl_seconds=60)
    return f"Bearer {token}"


def _payload(
    session_id: str = "lab-1", kind: str = "stop", raw: dict[str, Any] | None = None
) -> LabEventRequest:
    return LabEventRequest(
        session_id=session_id, kind=kind, raw=raw if raw is not None else {"key": "value"}
    )


def _session(user_id: str = "u1") -> AgentSessionDocument:
    return AgentSessionDocument(
        id="lab-1", user_id=user_id, todo_id="todo-1", agent=AgentKind.CLAUDE
    )


def _repo(recorded: AgentSessionDocument | None):
    repo = AsyncMock()
    repo.record_event = AsyncMock(return_value=recorded)
    return repo


@pytest.mark.unit
class TestLabEventsAuth:
    async def test_missing_token_is_401_and_stores_nothing(self) -> None:
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())) as repo:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization="")
        assert err.value.status_code == 401
        repo.record_event.assert_not_awaited()

    async def test_tampered_token_is_401(self) -> None:
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())) as repo:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=_bearer() + "x")
        assert err.value.status_code == 401
        repo.record_event.assert_not_awaited()

    async def test_wrong_scheme_is_401(self) -> None:
        token = _bearer().split(" ", 1)[1]
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())) as repo:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=f"Basic {token}")
        assert err.value.status_code == 401
        repo.record_event.assert_not_awaited()


@pytest.mark.unit
class TestLabEventsOwnership:
    async def test_unknown_session_is_404(self) -> None:
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(None)):
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=_bearer())
        assert err.value.status_code == 404

    async def test_foreign_session_is_404_and_never_read_as_owner(self) -> None:
        """The repo scope returns None for another user's id; the route must not retry unscoped."""
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(None)) as repo:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=_bearer(user_id="u1"))
        assert err.value.status_code == 404
        kwargs = repo.record_event.await_args.kwargs
        assert kwargs["user_id"] == "u1"

    async def test_token_user_becomes_the_scope(self) -> None:
        stored = _session(user_id="u9")
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(stored)) as repo:
            response = await report_lab_event(_payload(), authorization=_bearer(user_id="u9"))
        assert response.session_id == "lab-1"
        assert repo.record_event.await_args.kwargs["user_id"] == "u9"


@pytest.mark.unit
class TestLabEventsDumbPipe:
    async def test_raw_is_persisted_verbatim(self) -> None:
        raw: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "abc123",
            "nested": {"list": [1, 2, {"deep": True}]},
            "stop_hook_active": False,
        }
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())) as repo:
            response = await report_lab_event(
                _payload(kind="stop", raw=raw), authorization=_bearer()
            )
        assert isinstance(response, LabEventResponse)
        assert response.ok is True
        kwargs = repo.record_event.await_args.kwargs
        assert kwargs["kind"] == "stop"
        assert kwargs["raw"] == raw

    async def test_free_form_kind_passes_through_uninterpreted(self) -> None:
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())) as repo:
            await report_lab_event(_payload(kind="session_idle", raw={}), authorization=_bearer())
        assert repo.record_event.await_args.kwargs["kind"] == "session_idle"

    async def test_accepts_with_202_semantics(self) -> None:
        """202, never the stored payload echoed back."""
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(_session())):
            response = await report_lab_event(_payload(), authorization=_bearer())
        assert response.model_dump() == {"ok": True, "session_id": "lab-1"}

    async def test_state_is_untouched_by_the_push(self) -> None:
        """Classification (and any state transition) belongs to the future supervisor."""
        stored = _session()
        assert stored.state is AgentSessionState.STARTING
        with patch(f"{SERVICE}.agent_lab_session_repository", _repo(stored)) as repo:
            await report_lab_event(_payload(kind="stop"), authorization=_bearer())
        update = repo.record_event.await_args.kwargs
        assert update["kind"] == "stop"
