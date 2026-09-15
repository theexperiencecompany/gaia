"""Repository for the playbooks collection — one active playbook per workflow.

Global, keyed by the business playbook_id. There is no version history: the
agent revises a playbook by writing the whole document again, so
upsert_for_workflow overwrites the workflow's single record in place and a
stale sequence can never be replayed by accident. The unique
(workflow_id, user_id) index (app.db.mongodb.indexes) is what makes "one
per workflow" a property of the data rather than of the callers' timing.

Uncached (cache_policy = None): a playbook is read once per run, and the
overwrite-on-revise shape is exactly what an entity cache would misrepresent.
"""

from pymongo.errors import DuplicateKeyError

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.playbook_models import (
    PlaybookDocument,
    PlaybookRunOutcome,
    PlaybookRunStatus,
    PlaybookUpdate,
)
from app.services.workflow.playbook.lifecycle import HEAL_STATUSES, grows_from_untrusted


class PlaybooksRepository(MongoRepository[PlaybookDocument, PlaybookUpdate]):
    collection_name = "playbooks"
    document_model = PlaybookDocument
    update_model = PlaybookUpdate
    uses_object_id = True
    identity_field = "playbook_id"
    cache_policy = None

    async def get_for_workflow(self, workflow_id: str, user_id: str) -> PlaybookDocument | None:
        """Return the workflow's active playbook, or None when it has never been written."""
        return await self._find_one({"workflow_id": workflow_id, "user_id": user_id})

    async def upsert_for_workflow(self, playbook: PlaybookDocument) -> PlaybookDocument:
        """Write the workflow's playbook, replacing whatever it had, in one round trip.

        A revision resets the run outcome (status, reason, suspect streak); playbook_id
        and created_at are only ever set on insert. Racing first authorings insert
        against the unique (workflow_id, user_id) index; the loser's DuplicateKeyError
        retry then matches and overwrites the winner.
        """
        body = PlaybookUpdate(
            description=playbook.description,
            steps=playbook.steps,
            result_brief=playbook.result_brief,
            workflow_hash=playbook.workflow_hash,
            authored_run=playbook.authored_run,
            last_run_status=PlaybookRunStatus.NOT_RUN,
            last_run_reason=None,
        ).model_dump(exclude_unset=True)
        key = {"workflow_id": playbook.workflow_id, "user_id": playbook.user_id}
        # A heal-run rewrite carries its attempt count (lifecycle.Rewritten),
        # matched on stored status so two writers cannot both read and rewrite
        # the count; a non-heal body falls through to the reset below.
        healed = await self._apply_raw_update(
            {**key, "last_run_status": {"$in": sorted(status.value for status in HEAL_STATUSES)}},
            {"$set": body, "$inc": {"revision": 1, "heal_attempts": 1}},
            scope=REPO_GLOBAL_SCOPE,
        )
        if healed is not None:
            return healed
        # A body never replayed (a second write in the same run) carries the
        # count unchanged: the body it replaces spent nothing, and the count is
        # the heal run's, not the body's. Seen live: the second write reset it.
        unreplayed = await self._apply_raw_update(
            {**key, "last_run_status": PlaybookRunStatus.NOT_RUN.value},
            {"$set": body, "$inc": {"revision": 1}},
            scope=REPO_GLOBAL_SCOPE,
        )
        if unreplayed is not None:
            return unreplayed
        # The streak survives a rewrite on purpose: a rewrite is how a heal run
        # answers a suspect replay, and a playbook that keeps coming back suspect
        # must still reach the limit. Only a trusted replay clears it.
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
            raise RuntimeError(f"playbook for workflow {playbook.workflow_id} vanished mid-upsert")
        return stored

    async def record_run_outcome(
        self,
        workflow_id: str,
        user_id: str,
        outcome: PlaybookRunOutcome,
        *,
        playbook_id: str | None = None,
        revision: int | None = None,
    ) -> PlaybookDocument | None:
        """Record how the replay that just finished went.

        A suspect outcome doesn't move the playbook toward deletion (only the
        deterministic record check does). suspect_streak grows on SUSPECT, resets on
        SUCCESS, untouched by FAILED. playbook_id/revision scope the write to the
        actual replayed body — a rewrite keeps the id but bumps the revision.
        """
        key: dict[str, object] = {"workflow_id": workflow_id, "user_id": user_id}
        if playbook_id is not None:
            key["playbook_id"] = playbook_id
        if revision is not None:
            key["revision"] = revision
        if not grows_from_untrusted(outcome):
            return await self._apply_raw_update(
                key, _outcome_update(outcome, grow_streak=False), scope=REPO_GLOBAL_SCOPE
            )
        # A plain $inc can't be conditional on stored status, so the growing
        # write is tried first against a not-yet-suspect document, falling back
        # to the plain write when that matches nothing.
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
        self, workflow_id: str, user_id: str, *, playbook_id: str, revision: int | None = None
    ) -> PlaybookDocument | None:
        """Count one completed heal run against the body it was healing.

        revision scopes the count to that body: a heal run that rewrote the
        playbook bumped the revision, and its attempt must not land on the new
        body. None when the body is no longer the workflow's.
        """
        key: dict[str, object] = {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "playbook_id": playbook_id,
        }
        if revision is not None:
            key["revision"] = revision
        return await self._apply_raw_update(
            key, {"$inc": {"heal_attempts": 1}}, scope=REPO_GLOBAL_SCOPE
        )

    async def delete_for_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Drop the workflow's playbook. False when there was none."""
        existing = await self.get_for_workflow(workflow_id, user_id)
        if existing is None:
            return False
        return await self.delete(existing.playbook_id)

    async def delete_revision(
        self, workflow_id: str, user_id: str, *, playbook_id: str, revision: int
    ) -> bool:
        """Drop one body the worker has given up on, and only that body.

        Keyed on the revision as well as the id: a heal run rewrites in place
        and bumps the revision, so a discard decided against the old body must
        not take the replacement with it. False when that body is already
        gone, replaced or not.
        """
        return await self._remove(
            playbook_id,
            REPO_GLOBAL_SCOPE,
            {"workflow_id": workflow_id, "user_id": user_id, "revision": revision},
        )


def _outcome_update(
    outcome: PlaybookRunOutcome, *, grow_streak: bool
) -> dict[str, dict[str, object]]:
    """Build the $set/$inc update a run outcome writes.

    Split into the part independent of stored state ($set) and the part that
    depends on it ($inc), which the caller settles by matching on status;
    test_playbooks_repository proves the two agree for every outcome/status pair.
    """
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


playbook_repository = PlaybooksRepository()
