"""/api/v1/lab/events — token-only auth, todo-native dumb-pipe receipt."""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request
import pytest

from app.api.v1.endpoints.lab_events import LabEventResponse, report_lab_event
from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.api.v1.middleware.entitlement_allowlist import is_free_path
from app.api.v1.routes import router as v1_router
from app.constants.execute import SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
from app.constants.todos import TodoActivityEvent
from app.models.todo_models import TodoDocument
from app.services.agent_lab import lab_events as service, sandbox_setup
from app.services.agent_lab.lab_events import (
    LabEventReceipt,
    parse_lab_event_body,
    record_lab_event,
)
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

MODULE = "app.api.v1.endpoints.lab_events"
SVC = "app.services.agent_lab.lab_events"
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret():
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
        yield


def _bearer(user_id: str = "u1", run_id: str = "run-1") -> str:
    token = mint_execute_token(user_id, run_id, scoped_tool_names=[], ttl_seconds=60)
    return f"Bearer {token}"


def _request(body: object) -> Request:
    """Build a bare POST request carrying body as its JSON payload."""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def _raw_request(payload: bytes) -> Request:
    """Build a bare POST request carrying payload as its raw body."""

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def _service(return_id: str = "run-1", todo_id: str = "t1"):
    return AsyncMock(return_value=LabEventReceipt(id=return_id, todo_id=todo_id))


def _redis() -> MagicMock:
    client = MagicMock()
    client.incr = AsyncMock(side_effect=[1, 1])
    client.expire = AsyncMock()
    redis = MagicMock()
    redis.client = client
    return redis


def _todo(**overrides: Any) -> TodoDocument:
    fields: dict[str, Any] = {"id": "t1", "user_id": "u1", "title": "Lab task"}
    fields.update(overrides)
    return TodoDocument(**fields)


def _svc_stack(**overrides: Any):
    """Patch every seam of record_lab_event; returns the (stack, mocks) pair."""
    repo = MagicMock()
    repo.find_by_reference = AsyncMock(return_value=_todo())
    repo.replace_note_fields = AsyncMock(return_value=_todo())
    defaults: dict[str, Any] = {
        f"{SVC}.is_paid": AsyncMock(return_value=True),
        f"{SVC}.is_agent_lab_enabled": AsyncMock(return_value=True),
        f"{SVC}.todo_repository": repo,
        f"{SVC}.record_activity": AsyncMock(return_value=True),
        f"{SVC}.load_user_context": AsyncMock(return_value=SimpleNamespace(id="u1")),
        f"{SVC}.deliver_result_to_platforms": AsyncMock(return_value=None),
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.unit
class TestLabEventsAuth:
    async def test_missing_token_is_401_and_stores_nothing(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
            patch(f"{MODULE}.log") as mocked_log,
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"session_id": "run-1", "kind": "stop"}))
        assert err.value.status_code == 401
        record.assert_not_awaited()
        mocked_log.warning.assert_called_once()

    async def test_tampered_token_is_401(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"session_id": "run-1", "kind": "stop"}),
                    authorization=_bearer() + "x",
                )
        assert err.value.status_code == 401
        record.assert_not_awaited()

    async def test_wrong_scheme_is_401(self) -> None:
        token = _bearer().split(" ", 1)[1]
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"session_id": "run-1", "kind": "stop"}),
                    authorization=f"Basic {token}",
                )
        assert err.value.status_code == 401
        record.assert_not_awaited()


@pytest.mark.unit
class TestLabEventsShapes:
    async def test_canonical_shape_is_forwarded_verbatim(self) -> None:
        raw: dict[str, Any] = {
            "hook_event_name": "Stop",
            "session_id": "abc123",
            "nested": {"list": [1, 2, {"deep": True}]},
            "stop_hook_active": False,
        }
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            response = await report_lab_event(
                _request({"session_id": "run-1", "kind": "stop", "raw": raw}),
                authorization=_bearer(),
            )
        assert isinstance(response, LabEventResponse)
        assert response.ok is True
        assert record.await_args.kwargs["kind"] == "stop"
        assert record.await_args.kwargs["raw"] == raw
        assert record.await_args.kwargs["user_id"] == "u1"

    async def test_free_form_kind_passes_through_uninterpreted(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            await report_lab_event(
                _request({"session_id": "run-1", "kind": "session_idle", "raw": {}}),
                authorization=_bearer(),
            )
        assert record.await_args.kwargs["kind"] == "session_idle"

    async def test_hook_stop_post_maps_kind_and_stashes_whole_body(self) -> None:
        body = {
            "session_id": "run-1",
            "hook_event_name": "Stop",
            "transcript_path": "/tmp/t.jsonl",
            "stop_hook_active": False,
        }
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            response = await report_lab_event(_request(body), authorization=_bearer())
        assert response.ok is True
        assert record.await_args.kwargs["kind"] == "stop"
        assert record.await_args.kwargs["raw"] == body

    async def test_hook_notification_post_maps_kind(self) -> None:
        body = {
            "session_id": "run-1",
            "hook_event_name": "Notification",
            "message": "Task needs your input",
        }
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            await report_lab_event(_request(body), authorization=_bearer())
        assert record.await_args.kwargs["kind"] == "notification"
        assert record.await_args.kwargs["raw"] == body

    async def test_unknown_hook_event_is_stored_lowercased_never_422(self) -> None:
        body = {"session_id": "run-1", "hook_event_name": "SomethingNew"}
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            await report_lab_event(_request(body), authorization=_bearer())
        assert record.await_args.kwargs["kind"] == "somethingnew"

    async def test_body_without_session_id_is_422(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"hook_event_name": "Stop"}), authorization=_bearer()
                )
        assert err.value.status_code == 422
        record.assert_not_awaited()

    async def test_non_object_json_is_422(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request(["not", "an", "object"]), authorization=_bearer())
        assert err.value.status_code == 422
        record.assert_not_awaited()

    async def test_unparseable_body_is_422(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_raw_request(b"{nope"), authorization=_bearer())
        assert err.value.status_code == 422
        record.assert_not_awaited()

    async def test_accepts_with_202_semantics(self) -> None:
        """202, never the stored payload echoed back."""
        with (
            patch(f"{MODULE}.record_lab_event", _service()),
            patch(f"{MODULE}.redis_cache", _redis()),
        ):
            response = await report_lab_event(
                _request({"session_id": "run-1", "kind": "stop"}), authorization=_bearer()
            )
        assert response.model_dump() == {"ok": True, "session_id": "run-1"}


@pytest.mark.unit
class TestLabEventsOwnership:
    async def test_cross_session_write_is_rejected(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", _redis()) as redis,
            patch(f"{MODULE}.log") as mocked_log,
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"session_id": "run-2", "kind": "stop", "raw": {}}),
                    authorization=_bearer(run_id="run-1"),
                )
        assert err.value.status_code == 403
        record.assert_not_awaited()
        redis.client.incr.assert_not_awaited()
        mocked_log.warning.assert_called_once()


@pytest.mark.unit
class TestLabEventsBudgetAndAudit:
    def _exhausted_redis(self) -> MagicMock:
        client = MagicMock()
        client.incr = AsyncMock(side_effect=[10_000, 1])
        client.expire = AsyncMock()
        redis = MagicMock()
        redis.client = client
        return redis

    async def test_exhausted_budget_is_429_and_never_records(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", self._exhausted_redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"session_id": "run-1", "kind": "stop"}), authorization=_bearer()
                )
        assert err.value.status_code == 429
        record.assert_not_awaited()

    async def test_per_minute_rate_limit_is_429_and_never_records(self) -> None:
        client = MagicMock()
        client.incr = AsyncMock(side_effect=[5, 61])
        client.expire = AsyncMock()
        redis = MagicMock()
        redis.client = client
        with (
            patch(f"{MODULE}.record_lab_event", _service()) as record,
            patch(f"{MODULE}.redis_cache", redis),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(
                    _request({"session_id": "run-1", "kind": "stop"}), authorization=_bearer()
                )
        assert err.value.status_code == 429
        record.assert_not_awaited()

    async def test_every_accepted_call_is_audited(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _service(todo_id="t9")),
            patch(f"{MODULE}.redis_cache", _redis()),
            patch(f"{MODULE}.log") as mocked_log,
        ):
            await report_lab_event(
                _request({"session_id": "run-1", "kind": "stop"}), authorization=_bearer()
            )
        audit_kwargs = mocked_log.audit.call_args.kwargs
        assert audit_kwargs["actor"] == "u1"
        assert audit_kwargs["kind"] == "stop"
        assert audit_kwargs["run_id"] == "run-1"
        assert audit_kwargs["todo_id"] == "t9"

    async def test_budget_counters_are_namespaced_per_run(self) -> None:
        seen: list[str] = []
        client = MagicMock()

        async def _incr(key: str) -> int:
            seen.append(key)
            return 1

        client.incr = AsyncMock(side_effect=_incr)
        client.expire = AsyncMock()
        redis = MagicMock()
        redis.client = client
        with (
            patch(f"{MODULE}.record_lab_event", _service()),
            patch(f"{MODULE}.redis_cache", redis),
        ):
            await report_lab_event(
                _request({"session_id": "run-7", "kind": "stop"}),
                authorization=_bearer(run_id="run-7"),
            )
        assert seen[0] == "lab_events:calls:run-7"
        assert seen[1].startswith("lab_events:rate:run-7:")


@pytest.mark.unit
class TestParseLabEventBody:
    def test_canonical_shape(self) -> None:
        parsed = parse_lab_event_body({"session_id": "s", "kind": "k", "raw": {"a": 1}})
        assert (parsed.session_id, parsed.kind, parsed.raw) == ("s", "k", {"a": 1})

    def test_canonical_shape_defaults_empty_raw(self) -> None:
        assert parse_lab_event_body({"session_id": "s", "kind": "k"}).raw == {}

    def test_hook_shape_stashes_whole_body(self) -> None:
        body = {"session_id": "s", "hook_event_name": "Stop", "extra": 1}
        parsed = parse_lab_event_body(body)
        assert parsed.kind == "stop"
        assert parsed.raw == body


@pytest.mark.unit
class TestRecordLabEventEntitlements:
    async def test_oversize_raw_is_rejected_before_any_check(self) -> None:
        patches = _svc_stack()
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]) as paid,
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]),
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ),
        ):
            with pytest.raises(AppError) as err:
                await record_lab_event(
                    "run-1", user_id="u1", kind="stop", raw={"blob": "x" * (64 * 1024)}
                )
        assert err.value.status_code == 413
        paid.assert_not_awaited()

    async def test_lapsed_subscription_is_402(self) -> None:
        patches = _svc_stack(**{f"{SVC}.is_paid": AsyncMock(return_value=False)})
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]) as flag,
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
        ):
            with pytest.raises(HTTPException) as err:
                await record_lab_event("run-1", user_id="u1", kind="stop", raw={})
        assert err.value.status_code == 402
        flag.assert_not_awaited()
        repo.find_by_reference.assert_not_awaited()

    async def test_revoked_flag_is_403(self) -> None:
        patches = _svc_stack(**{f"{SVC}.is_agent_lab_enabled": AsyncMock(return_value=False)})
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
        ):
            with pytest.raises(AppError) as err:
                await record_lab_event("run-1", user_id="u1", kind="stop", raw={})
        assert err.value.status_code == 403
        repo.find_by_reference.assert_not_awaited()

    async def test_unknown_run_is_404(self) -> None:
        repo = MagicMock()
        repo.find_by_reference = AsyncMock(return_value=None)
        patches = _svc_stack(**{f"{SVC}.todo_repository": repo})
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", repo),
        ):
            with pytest.raises(AppError) as err:
                await record_lab_event("run-9", user_id="u1", kind="stop", raw={})
        assert err.value.status_code == 404


@pytest.mark.unit
class TestRecordLabEventPersist:
    async def test_happy_path_files_tail_and_returns_receipt(self) -> None:
        patches = _svc_stack()
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ),
        ):
            receipt = await record_lab_event("run-1", user_id="u1", kind="stop", raw={"answer": 42})
        assert receipt.id == "run-1"
        assert receipt.todo_id == "t1"
        repo.find_by_reference.assert_awaited_once_with("u1", "run-1")
        written = repo.replace_note_fields.await_args.kwargs["update"].log_content
        assert service.LAB_TAIL_MARKER in written
        assert '"answer": 42' in written
        assert activity.await_args.args[2] is TodoActivityEvent.LAB_EVENT_RECEIVED

    async def test_tail_is_overwritten_never_appended(self) -> None:
        patches = _svc_stack()
        first_raw = {"answer": "FIRST-TAIL-UNIQUE"}
        second_raw = {"answer": "SECOND-TAIL-UNIQUE"}
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]),
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ),
        ):
            await record_lab_event("run-1", user_id="u1", kind="stop", raw=first_raw)
            first_written: str = repo.replace_note_fields.await_args.kwargs["update"].log_content
            assert "FIRST-TAIL-UNIQUE" in first_written
            repo.find_by_reference = AsyncMock(return_value=_todo(log_content=first_written))
            await record_lab_event("run-1", user_id="u1", kind="stop", raw=second_raw)
            second_written: str = repo.replace_note_fields.await_args.kwargs["update"].log_content
        assert "SECOND-TAIL-UNIQUE" in second_written
        assert "FIRST-TAIL-UNIQUE" not in second_written
        assert second_written.count(service.LAB_TAIL_MARKER) == 1

    async def test_identical_repost_suppresses_second_wake(self) -> None:
        patches = _svc_stack()
        raw = {"hook_event_name": "Notification", "message": "SAME-DUPE-UNIQUE"}
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event("run-1", user_id="u1", kind="notification", raw=raw)
            first_written: str = repo.replace_note_fields.await_args.kwargs["update"].log_content
            assert "SAME-DUPE-UNIQUE" in first_written
            repo.find_by_reference = AsyncMock(return_value=_todo(log_content=first_written))
            await record_lab_event("run-1", user_id="u1", kind="notification", raw=raw)
        deliver.assert_awaited_once()
        assert "duplicate suppressed" in activity.await_args.args[3]

    async def test_repost_with_different_case_kind_suppresses_second_wake(self) -> None:
        """Fingerprint lowercases kind, so the marker must too — or a recased re-POST wakes twice."""
        patches = _svc_stack()
        raw = {"hook_event_name": "Notification", "message": "CASE-DUPE-UNIQUE"}
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]) as repo,
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event("run-1", user_id="u1", kind="Notification", raw=raw)
            first_written: str = repo.replace_note_fields.await_args.kwargs["update"].log_content
            assert "CASE-DUPE-UNIQUE" in first_written
            repo.find_by_reference = AsyncMock(return_value=_todo(log_content=first_written))
            await record_lab_event("run-1", user_id="u1", kind="notification", raw=raw)
        deliver.assert_awaited_once()
        assert "duplicate suppressed" in activity.await_args.args[3]

    async def test_system_trail_outside_the_tail_survives(self) -> None:
        repo = MagicMock()
        repo.find_by_reference = AsyncMock(
            return_value=_todo(log_content="# System Log: t\n- old entry")
        )
        repo.replace_note_fields = AsyncMock(return_value=_todo())
        patches = _svc_stack(**{f"{SVC}.todo_repository": repo})
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", repo),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]),
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ),
        ):
            await record_lab_event("run-1", user_id="u1", kind="stop", raw={})
        written: str = repo.replace_note_fields.await_args.kwargs["update"].log_content
        assert "- old entry" in written


@pytest.mark.unit
class TestRecordLabEventWake:
    async def test_question_wakes_the_user(self) -> None:
        patches = _svc_stack()
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event(
                "run-1", user_id="u1", kind="question", raw={"message": "Which table?"}
            )
        deliver.assert_awaited_once()
        assert deliver.await_args.kwargs["user_id"] == "u1"
        assert "Which table?" in deliver.await_args.kwargs["notification_text"]
        assert (
            "result sent" in activity.await_args.args[3]
            or "result not sent" in activity.await_args.args[3]
        )

    async def test_completion_wakes_the_user(self) -> None:
        patches = _svc_stack()
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]),
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event("run-1", user_id="u1", kind="completion", raw={})
        deliver.assert_awaited_once()

    async def test_progress_kind_stays_quiet_but_is_recorded(self) -> None:
        patches = _svc_stack()
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event("run-1", user_id="u1", kind="heartbeat", raw={})
        deliver.assert_not_awaited()
        assert "kept quiet" in activity.await_args.args[3]

    async def test_notify_off_stays_quiet(self) -> None:
        repo = MagicMock()
        repo.find_by_reference = AsyncMock(return_value=_todo(notify_on_run=False))
        repo.replace_note_fields = AsyncMock(return_value=_todo(notify_on_run=False))
        patches = _svc_stack(**{f"{SVC}.todo_repository": repo})
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", repo),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]) as loader,
            patch(
                f"{SVC}.deliver_result_to_platforms",
                patches[f"{SVC}.deliver_result_to_platforms"],
            ) as deliver,
        ):
            await record_lab_event("run-1", user_id="u1", kind="question", raw={})
        deliver.assert_not_awaited()
        loader.assert_not_awaited()
        assert "delivery is off" in activity.await_args.args[3]

    async def test_delivery_failure_still_files_the_event(self) -> None:
        patches = _svc_stack(
            **{f"{SVC}.deliver_result_to_platforms": AsyncMock(side_effect=RuntimeError("down"))}
        )
        with (
            patch(f"{SVC}.is_paid", patches[f"{SVC}.is_paid"]),
            patch(f"{SVC}.is_agent_lab_enabled", patches[f"{SVC}.is_agent_lab_enabled"]),
            patch(f"{SVC}.todo_repository", patches[f"{SVC}.todo_repository"]),
            patch(f"{SVC}.record_activity", patches[f"{SVC}.record_activity"]) as activity,
            patch(f"{SVC}.load_user_context", patches[f"{SVC}.load_user_context"]),
            patch(
                f"{SVC}.deliver_result_to_platforms", patches[f"{SVC}.deliver_result_to_platforms"]
            ),
        ):
            receipt = await record_lab_event("run-1", user_id="u1", kind="stop", raw={})
        assert receipt.todo_id == "t1"
        activity.assert_awaited_once()


@pytest.mark.unit
class TestLabTokenTtl:
    def test_lab_events_token_lives_six_hours(self) -> None:
        assert SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS == 21600

    def test_hooks_mint_uses_the_six_hour_constant(self) -> None:
        with patch.object(sandbox_setup, "mint_execute_token", return_value="tok") as mint:
            sandbox_setup.mint_lab_hooks_token("u1", "lab-1")
        assert mint.call_args.kwargs["ttl_seconds"] == SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
        assert mint.call_args.kwargs["scoped_tool_names"] == []


@pytest.mark.unit
class TestLabMountAndAllowlist:
    def test_route_is_mounted_next_to_sandbox_execute(self) -> None:
        def _paths(entry: Any) -> Any:
            if hasattr(entry, "original_router"):
                for route in entry.original_router.routes:
                    yield from _paths(route)
            elif hasattr(entry, "path"):
                yield entry.path

        paths = {path for included in v1_router.routes for path in _paths(included)}
        assert "/lab/events" in paths
        assert "/sandbox/execute" in paths

    def test_auth_middleware_excludes_the_token_only_path(self) -> None:
        from fastapi import FastAPI

        middleware = WorkOSAuthMiddleware(FastAPI(), workos_client=MagicMock())
        assert "/api/v1/lab/events" in middleware.exclude_paths

    def test_machine_to_machine_paths_stay_off_the_free_allowlist(self) -> None:
        assert not is_free_path("/api/v1/lab/events")
        assert not is_free_path("/api/v1/sandbox/execute")
