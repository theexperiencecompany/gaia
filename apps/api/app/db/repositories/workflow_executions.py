"""Repository for the workflow_executions collection.

Identity is the business key execution_id (Mongo's _id is an incidental
ObjectId). A global repository: completion is keyed by execution_id alone
with no user in context, while history listing filters by workflow + user.
"""

from collections.abc import Sequence
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
        """Mark an execution finished, computing its duration from started_at; None if not found."""
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

    async def get_for_user(
        self, execution_id: str, user_id: str
    ) -> WorkflowExecutionDocument | None:
        """One execution, only when user_id owns it."""
        return await self._find_one({"execution_id": execution_id, "user_id": user_id})

    async def find_recent_with_trace(
        self, workflow_id: str, user_id: str, *, limit: int
    ) -> list[WorkflowExecutionDocument]:
        """Return the workflow's most recent finished runs that recorded a trace, newest first.

        Runs with no trace are skipped, since an empty one would hide the last
        run that had something to say. A FAILED run still counts: it ran steps
        with side effects, and hiding it would repeat them on the next fire.
        """
        rows = await self._find(
            {
                "workflow_id": workflow_id,
                "user_id": user_id,
                "status": {"$in": ["success", "failed"]},
                "trace.0": {"$exists": True},
            },
            sort=[("started_at", -1)],
            limit=limit,
        )
        return rows

    async def list_for_workflow(
        self, workflow_id: str, user_id: str, *, limit: int, offset: int
    ) -> tuple[list[WorkflowExecutionDocument], int]:
        """Return a page of a workflow's executions (most recent first) plus the total."""
        filter_: dict[str, object] = {"workflow_id": workflow_id, "user_id": user_id}
        total = await self._count(filter_)
        executions = await self._find(filter_, sort=[("started_at", -1)], limit=limit, skip=offset)
        return executions, total

    async def list_since(
        self,
        user_id: str,
        since: datetime,
        *,
        exclude_workflow_ids: Sequence[str],
        limit: int,
    ) -> list[WorkflowExecutionDocument]:
        """Return a user's executions started at/after since, newest first.

        Used as the briefing engine's look-back read, which leaves out the
        briefing workflows' own runs via exclude_workflow_ids.
        """
        return await self._find(
            {
                "user_id": user_id,
                "started_at": {"$gte": since},
                "workflow_id": {"$nin": list(exclude_workflow_ids)},
            },
            sort=[("started_at", -1)],
            limit=limit,
        )


workflow_executions_repository = WorkflowExecutionsRepository()
