"""Contract tests for WorkflowExecutionsRepository (business-key id = execution_id)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid

import pytest

from app.db.repositories.workflow_executions import WorkflowExecutionsRepository
from app.models.workflow_execution_models import RecordedCall, WorkflowExecutionDocument


def _uid(prefix: str) -> str:
    # Per-run unique ids so a concurrent run against the shared test DB can't collide.
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _execution(**overrides: object) -> WorkflowExecutionDocument:
    data: dict[str, object] = {
        "execution_id": _uid("exec"),
        "workflow_id": _uid("wf"),
        "user_id": _uid("u"),
        "status": "running",
        "started_at": datetime.now(UTC) - timedelta(seconds=5),
    }
    data.update(overrides)
    return WorkflowExecutionDocument.model_validate(data)


@pytest.fixture
def repo(raw_collection) -> WorkflowExecutionsRepository:
    return WorkflowExecutionsRepository()


class TestWorkflowExecutionsRepository:
    async def test_create_preserves_execution_id_and_reads_by_it(self, repo, raw_collection):
        doc = _execution()
        created = await repo.create(doc)
        assert created.execution_id == doc.execution_id
        # The stored _id is a distinct ObjectId, not the business key.
        raw = await raw_collection.find_one({"execution_id": doc.execution_id})
        assert raw["_id"] != doc.execution_id
        fetched = await repo.get(doc.execution_id)
        assert fetched is not None and fetched.execution_id == doc.execution_id

    async def test_complete_sets_status_and_duration(self, repo):
        doc = await repo.create(_execution())
        updated = await repo.complete(
            doc.execution_id, status="success", summary="done", conversation_id="c1"
        )
        assert updated is not None
        assert updated.status == "success"
        assert updated.completed_at is not None
        assert updated.duration_seconds is not None and updated.duration_seconds > 0
        assert updated.summary == "done"
        assert updated.conversation_id == "c1"

    async def test_complete_failed_sets_error(self, repo):
        doc = await repo.create(_execution())
        updated = await repo.complete(doc.execution_id, status="failed", error_message="boom")
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error_message == "boom"

    async def test_complete_stores_the_runs_trace(self, repo):
        doc = await repo.create(_execution())
        trace = [
            RecordedCall(
                tool_name="GMAIL_FETCH",
                tool_category="mail",
                subagent_id="sa_gmail",
                args={"query": "is:unread"},
                result_digest="12 messages",
            )
        ]
        updated = await repo.complete(doc.execution_id, status="success", trace=trace)
        assert updated is not None
        assert updated.trace == trace

        # Round-trips through Mongo, not just the returned in-memory model.
        reread = await repo.get(doc.execution_id)
        assert reread is not None
        assert [c.tool_name for c in reread.trace] == ["GMAIL_FETCH"]
        assert reread.trace[0].args == {"query": "is:unread"}
        assert reread.trace[0].subagent_id == "sa_gmail"

    async def test_find_latest_with_trace_returns_the_newest_run_that_recorded_one(self, repo):
        wf = _uid("wf")
        owner = _uid("owner")

        async def _completed(started_at: datetime, trace: list[RecordedCall]) -> str:
            created = await repo.create(
                _execution(workflow_id=wf, user_id=owner, started_at=started_at)
            )
            await repo.complete(created.execution_id, status="success", trace=trace)
            return created.execution_id

        call = [RecordedCall(tool_name="GMAIL_FETCH")]
        now = datetime.now(UTC)
        older = await _completed(now - timedelta(hours=2), call)
        # Newer, but recorded nothing — it must not hide the run that has something to say.
        await _completed(now - timedelta(hours=1), [])
        # Another owner's run must not leak in.
        stranger = await repo.create(
            _execution(workflow_id=wf, user_id=_uid("other"), started_at=now)
        )
        await repo.complete(stranger.execution_id, status="success", trace=call)

        found = await repo.find_latest_with_trace(wf, owner)
        assert found is not None and found.execution_id == older

        newest = await _completed(now, call)
        found = await repo.find_latest_with_trace(wf, owner)
        assert found is not None and found.execution_id == newest

        assert await repo.find_latest_with_trace(_uid("missing"), owner) is None

    async def test_find_latest_with_trace_returns_a_failed_run_that_ran_steps(self, repo):
        """A fire that ran steps (with side effects) and then failed carries its
        trace on a FAILED record. Hiding it showed the next run the fire before,
        and the agent repeated the side effect. A run still in flight is not
        history yet and stays hidden."""
        wf = _uid("wf")
        owner = _uid("owner")
        call = [RecordedCall(tool_name="GMAIL_SEND", result_digest="sent")]
        now = datetime.now(UTC)
        succeeded = await repo.create(
            _execution(workflow_id=wf, user_id=owner, started_at=now - timedelta(hours=1))
        )
        await repo.complete(succeeded.execution_id, status="success", trace=call)
        failed = await repo.create(
            _execution(workflow_id=wf, user_id=owner, started_at=now - timedelta(minutes=30))
        )
        await repo.complete(failed.execution_id, status="failed", error_message="boom", trace=call)
        await repo.create(
            _execution(workflow_id=wf, user_id=owner, started_at=now, status="running", trace=call)
        )

        found = await repo.find_latest_with_trace(wf, owner)

        assert found is not None
        assert found.execution_id == failed.execution_id
        assert found.status == "failed"

    async def test_complete_missing_returns_none(self, repo):
        assert await repo.complete(_uid("missing"), status="success") is None

    async def test_list_for_workflow_scopes_and_paginates(self, repo):
        wf = _uid("wf")
        owner = _uid("owner")
        older = await repo.create(
            _execution(
                workflow_id=wf, user_id=owner, started_at=datetime.now(UTC) - timedelta(hours=1)
            )
        )
        newer = await repo.create(
            _execution(workflow_id=wf, user_id=owner, started_at=datetime.now(UTC))
        )
        # A different workflow and a different user must not leak in.
        await repo.create(_execution(workflow_id=_uid("other_wf"), user_id=owner))
        await repo.create(_execution(workflow_id=wf, user_id=_uid("attacker")))

        page, total = await repo.list_for_workflow(wf, owner, limit=10, offset=0)
        assert total == 2
        assert [e.execution_id for e in page] == [newer.execution_id, older.execution_id]

        first, total = await repo.list_for_workflow(wf, owner, limit=1, offset=0)
        assert total == 2 and [e.execution_id for e in first] == [newer.execution_id]
        second, _ = await repo.list_for_workflow(wf, owner, limit=1, offset=1)
        assert [e.execution_id for e in second] == [older.execution_id]
