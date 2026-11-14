"""The workflow journey waits for the worker's run of the workflow it started, and fails unless it succeeded."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from scripts.analytics_ops.e2e_journeys import (
    JourneyError,
    await_execution,
    await_reply,
)

from app.models.conversation_frame_models import EntryFrame
from app.models.conversation_log_models import ReplySettled
from app.models.conversation_send_models import ConversationEvent
from shared.py.conversation_wire import FailureReason, ReplyOutcome

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


def _settled(answers: tuple[str, ...], outcome: ReplyOutcome = ReplyOutcome.ANSWERED) -> str:
    entry = ReplySettled(
        id="r1:settled",
        reply_id="r1",
        outcome=outcome,
        answers=answers,
        through=1,
        quote_target=None,
        failure=FailureReason.MODEL_ERROR if outcome is ReplyOutcome.FAILED else None,
    )
    frame = EntryFrame(seq=2, at=datetime(2026, 11, 13, tzinfo=UTC), entry=entry)
    return f"data: {ConversationEvent(stream_id=None, frame=frame).model_dump_json()}"


def test_the_chat_journey_waits_for_the_reply_to_its_own_message() -> None:
    lines = [": keepalive", _settled(("someone-else",)), _settled(("m1",))]

    await_reply(iter(lines), "m1", deadline=float("inf"))


def test_a_reply_that_failed_fails_the_journey() -> None:
    with pytest.raises(JourneyError, match="failed"):
        await_reply(iter([_settled(("m1",), ReplyOutcome.FAILED)]), "m1", deadline=float("inf"))


def test_a_stream_that_ends_before_the_reply_fails_the_journey() -> None:
    with pytest.raises(JourneyError, match="ended"):
        await_reply(iter([_settled(("someone-else",))]), "m1", deadline=float("inf"))


def test_a_reply_past_the_deadline_fails_the_journey() -> None:
    with pytest.raises(JourneyError, match="in time"):
        await_reply(iter([": keepalive"]), "m1", deadline=0.0)
