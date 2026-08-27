"""The last-run brief is enrichment for the executor, never a reason a run fails."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow.execution_service import get_last_run_brief

MODULE = "app.services.workflow.execution_service"


@pytest.mark.unit
class TestLastRunBriefFailsOpen:
    async def test_a_first_run_has_no_brief(self) -> None:
        lookup = AsyncMock(return_value=None)
        with patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup):
            assert await get_last_run_brief("wf_1", "u_1") == ""
        lookup.assert_awaited_once_with("wf_1", "u_1")

    async def test_a_failed_lookup_yields_no_brief_and_a_warning(self) -> None:
        """The brief is read before the executor is dispatched. A store hiccup
        here must cost the run its history, not the run itself."""
        lookup = AsyncMock(side_effect=RuntimeError("mongo unavailable"))
        with (
            patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup),
            patch(f"{MODULE}.log") as log,
        ):
            assert await get_last_run_brief("wf_1", "u_1") == ""

        assert log.warning.call_count == 1
        assert log.warning.call_args.kwargs["error_type"] == "RuntimeError"
