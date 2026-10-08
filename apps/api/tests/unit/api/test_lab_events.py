"""/api/v1/lab/events: token-only identity, the body wakes the todo watching the run."""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException, Request
import pytest

from app.api.v1.endpoints.lab_events import LabEventResponse, report_lab_event
from app.api.v1.middleware.auth import WorkOSAuthMiddleware
from app.api.v1.middleware.entitlement_allowlist import is_free_path
from app.api.v1.routes import router as v1_router
from app.constants import execute
from app.constants.execute import SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS
from app.constants.todos import TodoActivityEvent
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerOrigin,
    TriggerSubscription,
)
from app.services.agent_lab import lab_events, lab_runs, sandbox_setup
from app.services.sandbox import execute_token
from app.services.sandbox.execute_token import mint_execute_token
from app.utils.errors import AppError

MODULE = "app.api.v1.endpoints.lab_events"
SVC = "app.services.agent_lab.lab_events"
DISPATCH = "app.services.triggers.subscription_dispatch"
BUDGET = "app.services.sandbox.token_budget"
SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _secret() -> Iterator[None]:
    with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
        yield


def _bearer(user_id: str = "u1", run_id: str = "run-1") -> str:
    token = mint_execute_token(user_id, run_id, scoped_tool_names=[], ttl_seconds=60)
    return f"Bearer {token}"


def _request(body: object) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def _raw_request(payload: bytes) -> Request:
    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def _receipt(todo_id: str = "t1", kind: str = "Stop") -> AsyncMock:
    return AsyncMock(return_value=lab_events.LabEventReceipt(todo_id=todo_id, kind=kind))


def _redis(*counts: int) -> MagicMock:
    client = MagicMock()
    client.incr = AsyncMock(side_effect=list(counts or (1, 1)))
    client.expire = AsyncMock()
    redis = MagicMock()
    redis.client = client
    return redis


def _run_subscription(run_id: str) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name=lab_runs.SANDBOX_RUN_TRIGGER,
        action=SubscriptionAction.EXECUTE,
        cooldown_seconds=0,
        resolution=SubscriptionResolution.ACCOUNT,
        trigger_data={lab_runs.RUN_ID_KEY: run_id},
    )


def _todo(todo_id: str = "t1", *run_ids: str) -> TodoDocument:
    return TodoDocument(
        id=todo_id,
        user_id="u1",
        title="Fix flaky test",
        trigger_subscriptions=[_run_subscription(r) for r in run_ids or ("run-1",)],
    )


class _Seams:
    def __init__(self) -> None:
        self.repo = MagicMock()
        self.activity = AsyncMock(return_value=True)
        self.enqueue = AsyncMock()
        self.capture = MagicMock()


@contextmanager
def _service_seams(
    todos: list[TodoDocument], *, paid: bool = True, lab_on: bool = True
) -> Iterator[_Seams]:
    """Mock the receiver's seams one layer down; fire_subscription itself runs for real."""
    seams = _Seams()
    seams.repo.find_active_by_user_and_trigger = AsyncMock(return_value=todos)
    with ExitStack() as stack:
        access_seams = "app.services.agent_lab.lab_runs"
        stack.enter_context(patch(f"{access_seams}.is_paid", AsyncMock(return_value=paid)))
        stack.enter_context(
            patch(f"{access_seams}.is_agent_lab_enabled", AsyncMock(return_value=lab_on))
        )
        stack.enter_context(patch(f"{SVC}.todo_repository", seams.repo))
        stack.enter_context(patch(f"{DISPATCH}.record_activity", seams.activity))
        stack.enter_context(patch(f"{DISPATCH}.enqueue_worker_job", seams.enqueue))
        stack.enter_context(patch(f"{DISPATCH}.capture_event", seams.capture))
        stack.enter_context(
            patch(f"{DISPATCH}.RedisPoolManager.get_pool", AsyncMock(return_value=MagicMock()))
        )
        yield seams


@pytest.mark.unit
class TestLabEventsAuth:
    async def test_missing_token_is_401_and_records_nothing(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
            patch(f"{MODULE}.log") as mocked_log,
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"kind": "idle"}))
        assert err.value.status_code == 401
        record.assert_not_awaited()
        mocked_log.warning.assert_called_once()

    async def test_tampered_token_is_401(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"kind": "idle"}), authorization=_bearer() + "x")
        assert err.value.status_code == 401
        record.assert_not_awaited()

    async def test_wrong_scheme_is_401(self) -> None:
        token = _bearer().split(" ", 1)[1]
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"kind": "idle"}), authorization=f"Basic {token}")
        assert err.value.status_code == 401
        record.assert_not_awaited()


@pytest.mark.unit
class TestLabEventsIdentityFromToken:
    async def test_claude_hook_with_its_own_session_id_is_accepted_for_the_token_run(
        self,
    ) -> None:
        """Claude's hook body carries Claude's session id, never GAIA's run id: the token decides."""
        body = {
            "session_id": "6f1c2b9e-4d1a-4a8e-9c2f-1b7e3d5a9c10",
            "hook_event_name": "Stop",
            "transcript_path": "/root/.claude/projects/x/6f1c.jsonl",
        }
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            await report_lab_event(_request(body), authorization=_bearer(run_id="run-1"))
        assert record.await_args.args[0] == "run-1"

    async def test_body_is_forwarded_verbatim_with_the_token_user(self) -> None:
        body = {"kind": "permission", "raw": {"nested": {"list": [1, {"deep": True}]}}}
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            response = await report_lab_event(_request(body), authorization=_bearer(user_id="u7"))
        assert record.await_args.kwargs == {"user_id": "u7", "body": body}
        assert response == LabEventResponse(ok=True, run_id="run-1")

    async def test_non_object_json_is_422(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request(["not", "an", "object"]), authorization=_bearer())
        assert err.value.status_code == 422
        record.assert_not_awaited()

    async def test_unparseable_body_is_422(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis()),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_raw_request(b"{nope"), authorization=_bearer())
        assert err.value.status_code == 422
        record.assert_not_awaited()


@pytest.mark.unit
class TestLabEventsBudgetAndAudit:
    async def test_exhausted_budget_is_429_and_never_records(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis(10_000, 1)),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"kind": "idle"}), authorization=_bearer())
        assert err.value.status_code == 429
        record.assert_not_awaited()

    async def test_a_long_run_is_not_cut_off_by_the_one_hour_execute_budget(
        self, fake_redis: Any
    ) -> None:
        # the receiver reused /sandbox/execute's 300-call budget, sized
        # for a 1h token, on a 13h run token; a long run with many turns hit 429
        # and gaia-hook swallowed it, so the todo silently stopped hearing.
        await fake_redis.set("lab_events:calls:run-1", 300)
        with patch(f"{MODULE}.record_lab_event", _receipt()) as record:
            await report_lab_event(_request({"kind": "idle"}), authorization=_bearer())
        record.assert_awaited_once()

    async def test_per_minute_rate_limit_is_429_and_never_records(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()) as record,
            patch(f"{BUDGET}.redis_cache", _redis(5, 61)),
        ):
            with pytest.raises(AppError) as err:
                await report_lab_event(_request({"kind": "idle"}), authorization=_bearer())
        assert err.value.status_code == 429
        record.assert_not_awaited()

    async def test_every_accepted_call_is_audited(self) -> None:
        with (
            patch(f"{MODULE}.record_lab_event", _receipt(todo_id="t9", kind="Stop")),
            patch(f"{BUDGET}.redis_cache", _redis()),
            patch(f"{MODULE}.log") as mocked_log,
        ):
            await report_lab_event(
                _request({"hook_event_name": "Stop"}), authorization=_bearer(user_id="u1")
            )
        audit_kwargs = mocked_log.audit.call_args.kwargs
        assert audit_kwargs["actor"] == "u1"
        assert audit_kwargs["kind"] == "Stop"
        assert audit_kwargs["run_id"] == "run-1"
        assert audit_kwargs["todo_id"] == "t9"

    async def test_budget_counters_are_namespaced_per_run(self) -> None:
        seen: list[str] = []

        async def _incr(key: str) -> int:
            seen.append(key)
            return 1

        redis = _redis()
        redis.client.incr = AsyncMock(side_effect=_incr)
        with (
            patch(f"{MODULE}.record_lab_event", _receipt()),
            patch(f"{BUDGET}.redis_cache", redis),
        ):
            await report_lab_event(
                _request({"kind": "idle"}), authorization=_bearer(run_id="run-7")
            )
        assert seen[0] == "lab_events:calls:run-7"
        assert seen[1].startswith("lab_events:rate:run-7:")


@pytest.mark.unit
class TestRecordLabEventGates:
    async def test_lapsed_subscription_is_402(self) -> None:
        with _service_seams([_todo()], paid=False) as seams:
            with pytest.raises(HTTPException) as err:
                await lab_events.record_lab_event("run-1", user_id="u1", body={})
        assert err.value.status_code == 402
        seams.enqueue.assert_not_awaited()

    async def test_revoked_flag_is_403(self) -> None:
        with _service_seams([_todo()], lab_on=False) as seams:
            with pytest.raises(AppError) as err:
                await lab_events.record_lab_event("run-1", user_id="u1", body={})
        assert err.value.status_code == 403
        seams.enqueue.assert_not_awaited()

    async def test_run_no_open_todo_watches_is_404(self) -> None:
        with _service_seams([_todo("t1", "run-other")]) as seams:
            with pytest.raises(AppError) as err:
                await lab_events.record_lab_event("run-9", user_id="u1", body={})
        assert err.value.status_code == 404
        seams.enqueue.assert_not_awaited()


@pytest.mark.unit
class TestRecordLabEventWakesTheTodo:
    async def test_event_queues_the_watching_todo_with_the_raw_body(self) -> None:
        body = {"session_id": "claude-uuid", "hook_event_name": "Stop"}
        todos = [_todo("t1", "run-other"), _todo("t2", "run-1")]
        with _service_seams(todos) as seams:
            receipt = await lab_events.record_lab_event("run-1", user_id="u1", body=body)

        assert receipt == lab_events.LabEventReceipt(todo_id="t2", kind="Stop")
        _, job, todo_id, origin = seams.enqueue.await_args.args
        assert (job, todo_id) == ("execute_tracked_todo", "t2")
        assert isinstance(origin, TriggerOrigin)
        assert origin.trigger_name == lab_runs.SANDBOX_RUN_TRIGGER
        assert origin.subscription_id == todos[1].trigger_subscriptions[0].id
        assert origin.payload == {"kind": "Stop", "event": body}

    async def test_event_lands_on_the_todo_timeline(self) -> None:
        with _service_seams([_todo()]) as seams:
            await lab_events.record_lab_event("run-1", user_id="u1", body={"kind": "idle"})
        todo_id, user_id, event, _ = seams.activity.await_args.args
        assert (todo_id, user_id, event) == ("t1", "u1", TodoActivityEvent.TRIGGER_FIRED)

    async def test_fire_is_counted_for_the_owning_user(self) -> None:
        with _service_seams([_todo()]) as seams:
            await lab_events.record_lab_event("run-1", user_id="u1", body={"kind": "idle"})
        distinct_id, _, props = seams.capture.call_args.args
        assert distinct_id == "u1"
        assert props["trigger_name"] == lab_runs.SANDBOX_RUN_TRIGGER

    async def test_oversize_body_still_wakes_the_todo_cut_down_with_a_marker(self) -> None:
        """A long final answer must not cost the completion wake; the cut is explicit."""
        body = {"hook_event_name": "Stop", "last_assistant_message": "x" * (200 * 1024)}
        with _service_seams([_todo()]) as seams:
            await lab_events.record_lab_event("run-1", user_id="u1", body=body)

        payload = seams.enqueue.await_args.args[3].payload
        assert payload["kind"] == "Stop"
        event = payload["event"]
        assert event["truncated_from_bytes"] > lab_events.LAB_EVENT_MAX_RAW_BYTES
        assert len(event["head"].encode()) <= lab_events.LAB_EVENT_MAX_RAW_BYTES
        assert event["head"].startswith('{"hook_event_name": "Stop"')

    def test_kind_falls_back_from_plugin_kind_to_hook_name_to_generic(self) -> None:
        assert lab_events.lab_event_kind({"kind": "idle", "hook_event_name": "Stop"}) == "idle"
        assert lab_events.lab_event_kind({"hook_event_name": "Stop"}) == "Stop"
        assert lab_events.lab_event_kind({"kind": ""}) == lab_events.UNNAMED_EVENT_KIND


@pytest.mark.unit
class TestLabTokenTtl:
    def test_token_outlives_the_longest_allowed_run(self) -> None:
        """A running CLI keeps the token it launched with; re-seeding files never reaches it."""
        assert SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS > execute.SANDBOX_LAB_MAX_RUN_SECONDS

    def test_budget_window_outlives_the_token(self) -> None:
        window = execute.SANDBOX_LAB_EVENTS_BUDGET_WINDOW_SECONDS
        assert window >= SANDBOX_LAB_EVENTS_TOKEN_TTL_SECONDS

    def test_hooks_mint_uses_the_run_token_ttl(self) -> None:
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
        middleware = WorkOSAuthMiddleware(FastAPI(), workos_client=MagicMock())
        assert "/api/v1/lab/events" in middleware.exclude_paths

    def test_machine_to_machine_paths_stay_off_the_free_allowlist(self) -> None:
        assert not is_free_path("/api/v1/lab/events")
        assert not is_free_path("/api/v1/sandbox/execute")
