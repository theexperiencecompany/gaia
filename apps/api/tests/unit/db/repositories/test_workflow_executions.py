"""Hermetic unit tests for ``WorkflowExecutionsRepository``.

The real-Mongo proof lives in ``tests/contracts/test_workflow_executions_repository.py``;
this tier pins the shape of the query the finder hands the driver. The driver is
mocked at ``app.db.repositories.base.get_async_collection``, the single seam
every read in the base repository goes through.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.repositories.workflow_executions import WorkflowExecutionsRepository


def _raw(execution_id: str, started_at: str) -> dict[str, object]:
    """A stored execution as the driver hands it back, before ``_to_model``."""
    return {
        "execution_id": execution_id,
        "workflow_id": "wf_1",
        "user_id": "u_1",
        "status": "success",
        "started_at": started_at,
        "trace": [{"tool_name": "send_email", "args": {}}],
    }


@pytest.fixture
def collection() -> Iterator[MagicMock]:
    mock = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=[])
    mock.find.return_value = cursor
    with patch("app.db.repositories.base.get_async_collection", return_value=mock):
        yield mock


@pytest.mark.unit
class TestFindLatestWithTrace:
    async def test_it_reads_finished_runs_success_or_failed_that_recorded_a_trace(
        self, collection: MagicMock
    ) -> None:
        """A failed fire that ran steps carries its trace; filtering it out showed
        the next run the fire before and the agent repeated the side effect. A
        running one is not history yet."""
        await WorkflowExecutionsRepository().find_latest_with_trace("wf_1", "u_1")

        (filter_,) = collection.find.call_args.args
        assert filter_["workflow_id"] == "wf_1"
        assert filter_["user_id"] == "u_1"
        assert filter_["trace.0"] == {"$exists": True}
        assert set(filter_["status"]["$in"]) == {"success", "failed"}

    async def test_it_asks_the_driver_for_the_newest_run_and_only_one(
        self, collection: MagicMock
    ) -> None:
        """Latest is entirely the sort direction plus the cap: an ascending sort
        hands the next run the FIRST fire it ever recorded, and an unbounded read
        drags the whole history back to throw all but one away."""
        await WorkflowExecutionsRepository().find_latest_with_trace("wf_1", "u_1")

        cursor = collection.find.return_value
        cursor.sort.assert_called_once_with([("started_at", -1)])
        cursor.limit.assert_called_once_with(1)

    async def test_it_returns_the_first_row_the_driver_yielded(self, collection: MagicMock) -> None:
        """The sort already put the newest first, so the finder must hand back
        that row — reading any other position silently returns an older run."""
        collection.find.return_value.to_list = AsyncMock(
            return_value=[
                _raw("ex_newest", "2026-01-02T09:00:00+00:00"),
                _raw("ex_older", "2026-01-01T09:00:00+00:00"),
            ]
        )

        found = await WorkflowExecutionsRepository().find_latest_with_trace("wf_1", "u_1")

        assert found is not None
        assert found.execution_id == "ex_newest"

    async def test_no_recorded_run_reads_as_none(self, collection: MagicMock) -> None:
        assert await WorkflowExecutionsRepository().find_latest_with_trace("wf_1", "u_1") is None
