"""Repositories for the executor run trace: runs, the calls they made, and each call's payload.

Three collections, one repository each. A call's full input and output sit in their
own collection behind payload_ref so no todo or run document ever carries them (Mongo's
16 MB limit, and search noise). All three expire together on a TTL over created_at.
"""

from datetime import UTC, datetime

from app.db.repositories.base import UserScopedRepository
from app.models.run_trace_models import (
    CallPayloadDocument,
    RunCallDocument,
    RunDocument,
    RunState,
    RunUpdate,
)


class RunsRepository(UserScopedRepository[RunDocument, RunUpdate]):
    """Persistence for executor runs, keyed by run_id (the run's stream id)."""

    collection_name = "executor_runs"
    document_model = RunDocument
    update_model = RunUpdate
    uses_object_id = True
    identity_field = "run_id"
    cache_policy = None

    async def open_run(self, run: RunDocument, *, state: RunState | None = None) -> None:
        """Create the run if it is new and stamp its liveness; state forces a state onto an existing run.

        A call stamps the heartbeat and keeps the run's state. Opening a run, or
        resuming a paused one, passes RUNNING, which also clears an earlier finish.
        """
        created = run.model_dump(
            exclude={"id", "state", "last_activity_at", "finished_at", "activity_logged_through"},
            exclude_none=True,
        )
        sets: dict[str, object] = {"last_activity_at": run.last_activity_at}
        # created_at is the TTL anchor; an upsert does not get the base's insert stamp.
        on_insert: dict[str, object] = {**created, "created_at": datetime.now(UTC)}
        update: dict[str, dict[str, object]] = {"$setOnInsert": on_insert, "$set": sets}
        if state is None:
            on_insert["state"] = RunState.RUNNING.value
        else:
            sets["state"] = state.value
            update["$unset"] = {"finished_at": ""}
        await self._apply_raw_update_unfetched(
            {"run_id": run.run_id, "user_id": run.user_id},
            update,
            scope=run.user_id,
            doc_id=run.run_id,
            upsert=True,
        )

    async def list_for_conversation(
        self, user_id: str, conversation_id: str, *, limit: int
    ) -> list[RunDocument]:
        """Return a conversation's runs, newest first."""
        return await self._find(
            {"user_id": user_id, "conversation_id": conversation_id},
            sort=[("started_at", -1)],
            limit=limit,
        )

    async def list_stale_running(
        self, last_active_before: datetime, *, limit: int
    ) -> list[RunDocument]:
        """Return runs still marked running whose last call or heartbeat is older than the cutoff, oldest first."""
        return await self._find(
            {"state": RunState.RUNNING.value, "last_activity_at": {"$lt": last_active_before}},
            sort=[("last_activity_at", 1)],
            limit=limit,
        )

    async def abandon_if_stale(
        self, run_id: str, user_id: str, last_active_before: datetime, *, at: datetime
    ) -> RunDocument | None:
        """Mark one run abandoned only while it is still running and still stale; None when it moved."""
        return await self._apply_raw_update(
            {"run_id": run_id, "user_id": user_id},
            {"$set": {"state": RunState.ABANDONED.value, "finished_at": at}},
            scope=user_id,
            extra_filter={
                "state": RunState.RUNNING.value,
                "last_activity_at": {"$lt": last_active_before},
            },
        )


class RunCallsRepository(UserScopedRepository[RunCallDocument, RunCallDocument]):
    """Persistence for the one-record-per-call trace, keyed by call_id."""

    collection_name = "executor_run_calls"
    document_model = RunCallDocument
    update_model = RunCallDocument
    uses_object_id = True
    identity_field = "call_id"
    cache_policy = None

    async def list_for_run(self, user_id: str, run_id: str, *, limit: int) -> list[RunCallDocument]:
        """Return a run's calls in the order they started."""
        return await self._find(
            {"user_id": user_id, "run_id": run_id}, sort=[("started_at", 1)], limit=limit
        )

    async def get_in_run(self, user_id: str, run_id: str, call_id: str) -> RunCallDocument | None:
        """Return one call of a run, or None when the run has no such call for this user."""
        return await self._find_one({"user_id": user_id, "run_id": run_id, "call_id": call_id})

    async def list_finished_after(
        self, user_id: str, run_id: str, after: datetime | None
    ) -> list[RunCallDocument]:
        """Return a run's calls that finished after the cutoff (all of them when None), oldest first."""
        filter_: dict[str, object] = {"user_id": user_id, "run_id": run_id}
        if after is not None:
            filter_["finished_at"] = {"$gt": after}
        return await self._find(filter_, sort=[("finished_at", 1)])


class CallPayloadsRepository(UserScopedRepository[CallPayloadDocument, CallPayloadDocument]):
    """Persistence for the full input and output of each call; read only through a call's payload_ref."""

    collection_name = "executor_call_payloads"
    document_model = CallPayloadDocument
    update_model = CallPayloadDocument
    uses_object_id = True
    cache_policy = None


run_repository = RunsRepository()
run_call_repository = RunCallsRepository()
call_payload_repository = CallPayloadsRepository()
