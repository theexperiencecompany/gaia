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
