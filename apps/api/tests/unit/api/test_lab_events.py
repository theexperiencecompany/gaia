"""/api/v1/lab/events — token-only auth, verbatim dumb-pipe receipt."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.lab_events import (
    LabEventRequest,
    LabEventResponse,
    report_lab_event,
)
from app.services.agent_lab.lab_events import LabEventReceipt, record_lab_event
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

MODULE = "app.api.v1.endpoints.lab_events"
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


def _service(return_id: str = "lab-1"):
    return AsyncMock(return_value=LabEventReceipt(id=return_id))


@pytest.mark.unit
class TestLabEventsAuth:
    async def test_missing_token_is_401_and_stores_nothing(self) -> None:
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization="")
        assert err.value.status_code == 401
        record.assert_not_awaited()

    async def test_tampered_token_is_401(self) -> None:
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=_bearer() + "x")
        assert err.value.status_code == 401
        record.assert_not_awaited()

    async def test_wrong_scheme_is_401(self) -> None:
        token = _bearer().split(" ", 1)[1]
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            with pytest.raises(AppError) as err:
                await report_lab_event(_payload(), authorization=f"Basic {token}")
        assert err.value.status_code == 401
        record.assert_not_awaited()


@pytest.mark.unit
class TestLabEventsDumbPipe:
    async def test_raw_is_forwarded_verbatim(self) -> None:
        raw: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "abc123",
            "nested": {"list": [1, 2, {"deep": True}]},
            "stop_hook_active": False,
        }
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            response = await report_lab_event(
                _payload(kind="stop", raw=raw), authorization=_bearer()
            )
        assert isinstance(response, LabEventResponse)
        assert response.ok is True
        assert record.await_args.kwargs["kind"] == "stop"
        assert record.await_args.kwargs["raw"] == raw

    async def test_free_form_kind_passes_through_uninterpreted(self) -> None:
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            await report_lab_event(_payload(kind="session_idle", raw={}), authorization=_bearer())
        assert record.await_args.kwargs["kind"] == "session_idle"

    async def test_token_user_becomes_the_scope(self) -> None:
        with patch(f"{MODULE}.record_lab_event", _service()) as record:
            response = await report_lab_event(_payload(), authorization=_bearer(user_id="u9"))
        assert response.session_id == "lab-1"
        assert record.await_args.kwargs["user_id"] == "u9"

    async def test_accepts_with_202_semantics(self) -> None:
        """202, never the stored payload echoed back."""
        with patch(f"{MODULE}.record_lab_event", _service()):
            response = await report_lab_event(_payload(), authorization=_bearer())
        assert response.model_dump() == {"ok": True, "session_id": "lab-1"}


@pytest.mark.unit
class TestRecordLabEventStub:
    async def test_receipt_echoes_the_session_id(self) -> None:
        receipt = await record_lab_event("lab-1", user_id="u1", kind="stop", raw={})
        assert receipt.id == "lab-1"

    async def test_missing_identity_fails_loud(self) -> None:
        with pytest.raises(AppError) as err:
            await record_lab_event("", user_id="u1", kind="stop", raw={})
        assert err.value.status_code == 422
