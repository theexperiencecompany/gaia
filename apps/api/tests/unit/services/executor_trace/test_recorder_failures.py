"""A trace store that is down is loud (error log, failure counter) and never fails the run."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from prometheus_client import REGISTRY
from pymongo.errors import PyMongoError

from app.models.run_trace_models import RunState
from app.services.executor_trace.recorder import RunOwner, begin_run, end_run

OWNER = RunOwner(user_id="u1", conversation_id="conv-1", run_id="run-1")
RECORDER = "app.services.executor_trace.recorder"


def _failures(write: str) -> float:
    return (
        REGISTRY.get_sample_value("gaia_executor_trace_write_failed_total", {"write": write}) or 0.0
    )


async def test_a_run_start_the_store_refuses_is_logged_at_error_and_counted() -> None:
    before = _failures("run_start")
    with (
        patch(f"{RECORDER}.run_repository.open_run", AsyncMock(side_effect=PyMongoError("down"))),
        patch(f"{RECORDER}.log") as log,
    ):
        await begin_run(OWNER)

    assert _failures("run_start") == before + 1
    assert log.error.call_args.kwargs["change"] == "run_start"


async def test_a_run_end_the_store_refuses_is_logged_at_error_and_counted() -> None:
    before = _failures("run_end")
    with (
        patch(f"{RECORDER}.run_repository.update", AsyncMock(side_effect=PyMongoError("down"))),
        patch(f"{RECORDER}.log") as log,
    ):
        await end_run(OWNER, RunState.FINISHED)

    assert _failures("run_end") == before + 1
    assert log.error.call_args.kwargs["change"] == "run_end"
