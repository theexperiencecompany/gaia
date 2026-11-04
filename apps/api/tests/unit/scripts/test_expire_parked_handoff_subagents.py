"""Which parked approvals the expiry script expires, and which it only reports."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.hil_models import HILApprovalStatus
from scripts import expire_parked_handoff_subagents as script


def _collection(counts: list[int]) -> MagicMock:
    collection = MagicMock()
    collection.count_documents = AsyncMock(side_effect=counts)
    return collection


@pytest.mark.unit
class TestUnclassifiedExecutorPauses:
    async def test_executor_pauses_are_counted_by_status_and_never_selected_for_expiry(
        self,
    ) -> None:
        """A foreground handoff paused the executor itself; its record cannot be told from an ordinary pause."""
        collection = _collection([3, 2])

        with patch.object(script, "get_async_collection", return_value=collection):
            pending, decided = await script.unclassified_executor_pauses()

        assert (pending, decided) == (3, 2)
        pending_query, decided_query = (
            call.args[0] for call in collection.count_documents.await_args_list
        )
        for query in (pending_query, decided_query):
            assert query["resumed_at"] is None
            assert query["resume_item"] == {"$ne": None}
            assert query["subagent_resume"] is None
        assert pending_query["status"] == HILApprovalStatus.PENDING.value
        assert decided_query["status"] == {"$ne": HILApprovalStatus.PENDING.value}

    async def test_the_report_names_the_check_that_classifies_them(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(script, "parked_handoff_records", new=AsyncMock(return_value=[])),
            patch.object(
                script, "unclassified_executor_pauses", new=AsyncMock(return_value=(3, 2))
            ),
        ):
            await script.main(apply=False)

        out = capsys.readouterr().out
        assert "3 pending and 2 decided" in out
        assert "not touched" in out
