"""The workflow journey waits for the worker's run of the workflow it started, and fails unless it succeeded."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from scripts.analytics_ops.e2e_journeys import JourneyError, await_execution

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
