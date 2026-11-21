"""Repository for task_runs: one record per GAIA task run.

Global and keyed by the business id run_id: a run completes in a worker with only its
id in hand, while history reads filter by task and user. Uncached, as workflow
executions were: a record is written twice and read a page at a time.
"""

from datetime import UTC, datetime

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.constants.tasks import TaskRunKind, TaskRunStatus
from app.db.repositories.base import MongoRepository
from app.models.task_run_models import TaskRunDocument, TaskRunUpdate

#: A finished run whose calls happened; a skipped one did nothing to remember.
_TRACED_STATUSES = [TaskRunStatus.SUCCESS.value, TaskRunStatus.FAILED.value]


class TaskRunsRepository(MongoRepository[TaskRunDocument, TaskRunUpdate]):
    collection_name = "task_runs"
    document_model = TaskRunDocument
    update_model = TaskRunUpdate
    uses_object_id = True
    identity_field = "run_id"
    cache_policy = None

    async def complete(self, run_id: str, ending: TaskRunUpdate) -> TaskRunDocument | None:
        """Write a run's one terminal state (ending), its duration taken from started_at.

        None when no such run is still running, so a replayed finish never overwrites one.
        """
        if ending.status in (None, TaskRunStatus.RUNNING):
            raise ValueError(f"run {run_id} cannot end in status {ending.status}")
        run = await self.get(run_id)
        if run is None or run.status is not TaskRunStatus.RUNNING:
            return None
        completed_at = datetime.now(UTC)
        return await self._apply_update(
            run_id,
            REPO_GLOBAL_SCOPE,
            {"status": TaskRunStatus.RUNNING.value},
            ending.model_copy(
                update={
                    "completed_at": completed_at,
                    "duration_seconds": (completed_at - run.started_at).total_seconds(),
                }
            ),
        )

    async def find_recent_with_trace(
        self, task_id: str, user_id: str, *, limit: int
    ) -> list[TaskRunDocument]:
        """Return the task's latest finished runs that recorded calls, newest first.

        A failed run counts: its calls had side effects the next run must not repeat.
        """
        return await self._find(
            {
                "task_id": task_id,
                "user_id": user_id,
                "status": {"$in": _TRACED_STATUSES},
                "trace.0": {"$exists": True},
            },
            sort=[("started_at", -1)],
            limit=limit,
        )

    async def list_for_task(
        self,
        task_id: str,
        user_id: str,
        *,
        limit: int,
        offset: int,
        kind: TaskRunKind | None = None,
    ) -> tuple[list[TaskRunDocument], int]:
        """Return a page of the task's records, newest first, and the total; kind narrows to runs or history."""
        filt: dict[str, object] = {"task_id": task_id, "user_id": user_id}
        if kind is not None:
            filt["kind"] = kind.value
        total = await self._count(filt)
        rows = await self._find(filt, sort=[("started_at", -1)], limit=limit, skip=offset)
        return rows, total

    async def latest_finished(
        self, task_id: str, user_id: str, *, limit: int
    ) -> list[TaskRunDocument]:
        """Return the task's latest finished runs, newest first: what came of its recent runs."""
        return await self._find(
            {
                "task_id": task_id,
                "user_id": user_id,
                "kind": TaskRunKind.RUN.value,
                "status": {"$nin": [TaskRunStatus.RUNNING.value]},
            },
            sort=[("started_at", -1)],
            limit=limit,
        )

    async def delete_for_tasks(self, user_id: str, task_ids: list[str]) -> int:
        """Delete every record of these tasks, as deleting a task does."""
        if not task_ids:
            return 0
        return await self._delete_many(
            {"user_id": user_id, "task_id": {"$in": task_ids}}, scope=user_id
        )


task_run_repository = TaskRunsRepository()
