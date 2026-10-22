"""The journeys send requests the API accepts; the workflow one waits for the worker's run and fails unless it succeeded."""

from __future__ import annotations

from collections.abc import Iterator
import json

import httpx
import pytest
from scripts.analytics_ops.e2e_journeys import (
    BRIEFING_SCHEDULE,
    JourneyError,
    Stack,
    await_execution,
    briefing_schedule,
    workflow,
)

from app.constants.analytics import POSTHOG_SESSION_HEADER
from app.constants.workflows import WorkflowDelivery
from app.models.briefing_models import BriefingSchedule
from app.models.workflow_models import CreateWorkflowRequest

WORKFLOW = "wf_1"
EXECUTIONS_PATH = f"/api/v1/workflows/{WORKFLOW}/executions"


def _execution(status: str, error: str | None = None) -> dict[str, object]:
    return {
        "execution_id": "ex_1",
        "workflow_id": WORKFLOW,
        "user_id": "6ac7cdb30f37f2c418eeaeeb",
        "status": status,
        "started_at": "2026-10-08T17:07:08Z",
        "error_message": error,
    }


def _api(*pages: list[dict[str, object]]) -> httpx.Client:
    """Answer each executions read with the next page, repeating the last one."""
    replies: Iterator[list[dict[str, object]]] = iter(pages)
    last: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal last
        assert request.url.path == EXECUTIONS_PATH
        last = next(replies, last)
        return httpx.Response(200, json={"executions": last, "total": len(last), "has_more": False})

    return httpx.Client(base_url="http://api.test/api/v1", transport=httpx.MockTransport(handle))


def test_a_run_the_worker_finishes_returns() -> None:
    await_execution(
        _api([], [_execution("running")], [_execution("success")]),
        WORKFLOW,
        timeout_s=5,
        poll_s=0,
    )


@pytest.mark.parametrize("status", ["failed", "skipped"])
def test_a_run_that_did_not_succeed_fails_the_journey(status: str) -> None:
    with pytest.raises(JourneyError, match=f"{status}: boom"):
        await_execution(_api([_execution(status, "boom")]), WORKFLOW, timeout_s=5, poll_s=0)


def test_a_run_no_worker_picks_up_fails_at_the_deadline() -> None:
    with pytest.raises(JourneyError, match="no ARQ worker"):
        await_execution(_api([]), WORKFLOW, timeout_s=0, poll_s=0)


def test_a_run_still_going_at_the_deadline_fails() -> None:
    with pytest.raises(JourneyError, match="running"):
        await_execution(_api([_execution("running")]), WORKFLOW, timeout_s=0, poll_s=0)


def test_a_workflow_executed_once_that_ran_twice_fails_the_journey() -> None:
    twice = [_execution("success"), _execution("success")]
    with pytest.raises(JourneyError, match="2 finished runs"):
        await_execution(_api(twice), WORKFLOW, timeout_s=5, poll_s=0)


class _RecordingStack(Stack):
    """A Stack whose client answers the workflow journey in-process and records the create body."""

    created: dict[str, object] | None = None

    def client(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/v1/workflows":
                self.created = json.loads(request.content)
                return httpx.Response(200, json={"workflow": {"id": WORKFLOW}})
            if request.url.path == f"/api/v1/workflows/{WORKFLOW}/execute":
                return httpx.Response(200, json={})
            assert request.url.path == EXECUTIONS_PATH
            done = [_execution("success")]
            return httpx.Response(200, json={"executions": done, "total": 1, "has_more": False})

        return httpx.Client(
            base_url="http://api.test/api/v1", transport=httpx.MockTransport(handle)
        )


def test_the_workflow_journey_creates_a_workflow_the_api_accepts() -> None:
    stack = _RecordingStack(api_url="http://api.test", email="e2e@example.com")

    workflow(stack)

    assert stack.created is not None
    assert CreateWorkflowRequest.model_validate(stack.created).delivery is WorkflowDelivery.NOW


class _BriefingStack(Stack):
    """A Stack whose client accepts the settings PUT and records its path, session and body."""

    sent: httpx.Request | None = None

    def client(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.sent = request
            return httpx.Response(200, content=request.content)

        return httpx.Client(
            base_url="http://api.test/api/v1", transport=httpx.MockTransport(handle)
        )


def test_the_briefing_journey_puts_a_non_default_schedule_from_the_browser() -> None:
    stack = _BriefingStack(api_url="http://api.test", email="e2e@example.com")

    briefing_schedule(stack)

    assert stack.sent is not None
    assert stack.sent.method == "PUT"
    assert stack.sent.url.path == "/api/v1/notifications/preferences/briefing-schedule"
    assert stack.sent.headers[POSTHOG_SESSION_HEADER] == stack.session_id
    sent = BriefingSchedule.model_validate_json(stack.sent.content)
    assert sent == BRIEFING_SCHEDULE
    assert sent != BriefingSchedule()
