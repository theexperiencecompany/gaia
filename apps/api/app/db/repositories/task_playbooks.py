"""Repository for task_playbooks: one active playbook per repeating task.

The playbooks collection keyed by task_id. A revision overwrites the task's one record in
place, and the unique (task_id, user_id) index makes "one per task" a property of the data.
Uncached: a playbook is read once per run.
"""

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.playbook_models import (
    PlaybookRunOutcome,
    PlaybookRunStatus,
    TaskPlaybookDocument,
    TaskPlaybookUpdate,
)
from app.services.workflow.playbook.lifecycle import HEAL_STATUSES, grows_from_untrusted


class TaskPlaybooksRepository(MongoRepository[TaskPlaybookDocument, TaskPlaybookUpdate]):
    collection_name = "task_playbooks"
    document_model = TaskPlaybookDocument
    update_model = TaskPlaybookUpdate
    uses_object_id = True
    identity_field = "playbook_id"
    cache_policy = None

    async def get_for_task(self, task_id: str, user_id: str) -> TaskPlaybookDocument | None:
        """Return the task's playbook, or None when none was ever written."""
        return await self._find_one({"task_id": task_id, "user_id": user_id})

    async def upsert_for_task(self, playbook: TaskPlaybookDocument) -> TaskPlaybookDocument:
        """Write the task's playbook over whatever it had, resetting the run outcome.

        A heal rewrite counts its attempt and a never-replayed body keeps the count; racing
        first writes meet the unique index and the loser overwrites the winner.
        """
        body = TaskPlaybookUpdate(
            description=playbook.description,
            steps=playbook.steps,
            result_brief=playbook.result_brief,
            body_hash=playbook.body_hash,
            authored_run=playbook.authored_run,
            last_run_status=PlaybookRunStatus.NOT_RUN,
            last_run_reason=None,
        ).model_dump(exclude_unset=True)
        key = {"task_id": playbook.task_id, "user_id": playbook.user_id}
        healed = await self._apply_raw_update(
            {**key, "last_run_status": {"$in": sorted(status.value for status in HEAL_STATUSES)}},
            {"$set": body, "$inc": {"revision": 1, "heal_attempts": 1}},
            scope=REPO_GLOBAL_SCOPE,
        )
        if healed is not None:
            return healed
        unreplayed = await self._apply_raw_update(
            {**key, "last_run_status": PlaybookRunStatus.NOT_RUN.value},
            {"$set": body, "$inc": {"revision": 1}},
            scope=REPO_GLOBAL_SCOPE,
        )
        if unreplayed is not None:
            return unreplayed
        update = {
            "$set": {**body, "heal_attempts": 0},
            "$inc": {"revision": 1},
            "$setOnInsert": {
                "playbook_id": playbook.playbook_id,
                "created_at": playbook.created_at,
                "suspect_streak": 0,
            },
        }
        try:
            stored = await self._apply_raw_update(key, update, scope=REPO_GLOBAL_SCOPE, upsert=True)
        except DuplicateKeyError:
            stored = await self._apply_raw_update(key, update, scope=REPO_GLOBAL_SCOPE, upsert=True)
        if stored is None:
            raise RuntimeError(f"playbook for task {playbook.task_id} vanished mid-upsert")
        return stored

    async def record_run_outcome(
        self,
        task_id: str,
        user_id: str,
        outcome: PlaybookRunOutcome,
        *,
        playbook_id: str | None = None,
        revision: int | None = None,
    ) -> TaskPlaybookDocument | None:
        """Record how the replay that just finished went, scoped to the body it replayed."""
        key: dict[str, object] = {"task_id": task_id, "user_id": user_id}
        if playbook_id is not None:
            key["playbook_id"] = playbook_id
        if revision is not None:
            key["revision"] = revision
        if not grows_from_untrusted(outcome):
            return await self._apply_raw_update(
                key, _outcome_update(outcome, grow_streak=False), scope=REPO_GLOBAL_SCOPE
            )
        grown = await self._apply_raw_update(
            {**key, "last_run_status": {"$ne": PlaybookRunStatus.SUSPECT.value}},
            _outcome_update(outcome, grow_streak=True),
            scope=REPO_GLOBAL_SCOPE,
        )
        if grown is not None:
            return grown
        return await self._apply_raw_update(
            key, _outcome_update(outcome, grow_streak=False), scope=REPO_GLOBAL_SCOPE
        )

    async def increment_heal_attempts(
        self, task_id: str, user_id: str, *, playbook_id: str, revision: int | None = None
    ) -> TaskPlaybookDocument | None:
        """Count one finished heal run against the body it healed; None when that body is gone."""
        key: dict[str, object] = {
            "task_id": task_id,
            "user_id": user_id,
            "playbook_id": playbook_id,
        }
        if revision is not None:
            key["revision"] = revision
        return await self._apply_raw_update(
            key, {"$inc": {"heal_attempts": 1}}, scope=REPO_GLOBAL_SCOPE
        )

    async def delete_for_task(self, task_id: str, user_id: str) -> bool:
        """Drop the task's playbook; False when it had none."""
        return (
            await self._delete_many(
                {"task_id": task_id, "user_id": user_id}, scope=REPO_GLOBAL_SCOPE
            )
        ) > 0

    async def delete_revision(
        self, task_id: str, user_id: str, *, playbook_id: str, revision: int
    ) -> bool:
        """Drop one body the worker gave up on, and only that revision of it."""
        return await self._remove(
            playbook_id,
            REPO_GLOBAL_SCOPE,
            {"task_id": task_id, "user_id": user_id, "revision": revision},
        )


def _outcome_update(
    outcome: PlaybookRunOutcome, *, grow_streak: bool
) -> dict[str, dict[str, object]]:
    fields: dict[str, object] = {
        "last_run_status": outcome.status,
        "last_run_reason": None if outcome.status is PlaybookRunStatus.SUCCESS else outcome.reason,
    }
    if outcome.status is PlaybookRunStatus.SUCCESS:
        fields["suspect_streak"] = 0
    update: dict[str, dict[str, object]] = {"$set": fields}
    if grow_streak:
        update["$inc"] = {"suspect_streak": 1}
    return update


task_playbook_repository = TaskPlaybooksRepository()
