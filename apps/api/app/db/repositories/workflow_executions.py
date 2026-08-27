"""Repository for the workflow_executions collection.

Identity is the business key ``execution_id`` (Mongo's ``_id`` is an incidental
ObjectId). A global repository: completion is keyed by ``execution_id`` alone
with no user in context, while history listing filters by workflow + user.
"""

from datetime import UTC, datetime

from app.db.repositories.base import MongoRepository
from app.models.workflow_execution_models import (
    RecordedCall,
    WorkflowExecutionDocument,
    WorkflowExecutionStatus,
    WorkflowExecutionUpdate,
)


class WorkflowExecutionsRepository(
    MongoRepository[WorkflowExecutionDocument, WorkflowExecutionUpdate]
):
    collection_name = "workflow_executions"
    document_model = WorkflowExecutionDocument
    update_model = WorkflowExecutionUpdate
    uses_object_id = True
    identity_field = "execution_id"
    cache_policy = None

    async def complete(
        self,
        execution_id: str,
        *,
        status: WorkflowExecutionStatus,
        summary: str | None = None,
        error_message: str | None = None,
        conversation_id: str | None = None,
        trace: list[RecordedCall] | None = None,
    ) -> WorkflowExecutionDocument | None:
        """Mark an execution finished, computing its duration from ``started_at``.
        Returns the updated document, or ``None`` if the execution was not found."""
        execution = await self.get(execution_id)
        if execution is None:
            return None

        completed_at = datetime.now(UTC)
        fields: dict[str, object] = {
            "status": status,
            "completed_at": completed_at,
            "duration_seconds": (completed_at - execution.started_at).total_seconds(),
        }
        if summary:
            fields["summary"] = summary
        if error_message:
            fields["error_message"] = error_message
        if conversation_id:
            fields["conversation_id"] = conversation_id
        if trace:
            fields["trace"] = trace

        return await self.update(execution_id, WorkflowExecutionUpdate.model_validate(fields))

    async def find_latest_with_trace(
        self, workflow_id: str, user_id: str
    ) -> WorkflowExecutionDocument | None:
        """The workflow's most recent finished run that recorded a trace.

        What the next run reads to learn what the previous one did, now that its
        checkpoint threads are reset before every fire. Runs that recorded
        nothing are skipped: an empty trace would tell the next run nothing while
        hiding the last one that had something to say. A FAILED run counts: it
        ran steps with side effects before it stopped, and hiding it would show
        the next run the fire before, which then repeats them. The brief and
        ``$last_run`` both carry the status, so a reader can tell.
        """
        rows = await self._find(
            {
                "workflow_id": workflow_id,
                "user_id": user_id,
                "status": {"$in": ["success", "failed"]},
                "trace.0": {"$exists": True},
            },
            sort=[("started_at", -1)],
            limit=1,
        )
        return rows[0] if rows else None

    async def list_for_workflow(
        self, workflow_id: str, user_id: str, *, limit: int, offset: int
    ) -> tuple[list[WorkflowExecutionDocument], int]:
        """A page of a workflow's executions (most recent first) plus the total."""
        filter_: dict[str, object] = {"workflow_id": workflow_id, "user_id": user_id}
        total = await self._count(filter_)
        executions = await self._find(filter_, sort=[("started_at", -1)], limit=limit, skip=offset)
        return executions, total


workflow_executions_repository = WorkflowExecutionsRepository()
