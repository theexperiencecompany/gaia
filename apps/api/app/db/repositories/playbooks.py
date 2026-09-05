"""Repository for the ``playbooks`` collection — one active playbook per workflow.

Global, keyed by the business ``playbook_id``. There is no version history: the
agent revises a playbook by writing the whole document again, so
``upsert_for_workflow`` overwrites the workflow's single record in place and a
stale sequence can never be replayed by accident. The unique
``(workflow_id, user_id)`` index (``app.db.mongodb.indexes``) is what makes "one
per workflow" a property of the data rather than of the callers' timing.

Uncached (``cache_policy = None``): a playbook is read once per run, and the
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
        """The workflow's active playbook, or ``None`` when it has never been written."""
        return await self._find_one({"workflow_id": workflow_id, "user_id": user_id})

    async def upsert_for_workflow(self, playbook: PlaybookDocument) -> PlaybookDocument:
        """Write the workflow's playbook, replacing whatever it had, in one round trip.

        A revision resets the run outcome (status, reason and suspect streak):
        the previous run's verdict described the sequence that was just thrown
        away. ``playbook_id`` and ``created_at`` are only ever set on insert, so
        a rewrite keeps the id the worker may be replaying under.

        Two first authorings racing on the same workflow can both miss the match
        and both insert; the unique ``(workflow_id, user_id)`` index rejects the
        loser with ``DuplicateKeyError``, and the retry then matches the winner
        and overwrites it — the same result as if the two had run in sequence.
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
        # A rewrite out of a heal run spends one attempt and carries the count
        # (``lifecycle.Rewritten``): matched on the stored status, the same way
        # ``record_run_outcome`` grows the streak, so two writers cannot both
        # read a count and both write it back. A body that is not in a heal
        # status matches nothing here and takes the reset below.
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

        An outcome that does not count toward the streak records a suspect that
        must not move the playbook toward deletion: the narration's verdict is
        the model's opinion and sends the fire to the agent, but only the
        deterministic record check (empty where the previous replay had items)
        is trusted to delete.

        ``reason`` is why a run failed or was not trusted; a success clears it.
        ``suspect_streak`` counts consecutive suspect replays: it grows on
        ``SUSPECT``, resets on ``SUCCESS`` and is left alone by ``FAILED``, so
        the worker can disable a playbook that keeps completing with results
        nobody trusts. A suspect landing on a playbook already marked suspect
        does not grow it again: two replays of one body racing to the same
        verdict are one suspect, not two.

        ``playbook_id`` and ``revision`` scope the write to the body that was
        actually replayed. The id alone is not enough, since a rewrite keeps it;
        the revision is what changes. ``None`` when the workflow has no playbook
        (an agentic run has nothing to record) or when the replayed body has
        since been rewritten or deleted.
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
        # A plain ``$inc`` cannot be conditional on the stored status, so the
        # growing write is tried first against a not-yet-suspect document and
        # the plain one only when that matched nothing. Which outcomes may grow
        # at all is the lifecycle's rule, not this method's.
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

        ``revision`` scopes the count to that body: a heal run that rewrote the
        playbook bumped the revision, and its attempt must not land on the new
        body. ``None`` when the body is no longer the workflow's.
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
        """Drop the workflow's playbook. ``False`` when there was none."""
        existing = await self.get_for_workflow(workflow_id, user_id)
        if existing is None:
            return False
        return await self.delete(existing.playbook_id)


def _outcome_update(
    outcome: PlaybookRunOutcome, *, grow_streak: bool
) -> dict[str, dict[str, object]]:
    """The update a run outcome writes.

    The fields are what :func:`transition` produces for a replay, split into the
    part that does not depend on the stored state (``$set``) and the part that
    does (``$inc``), which the caller has already settled by matching on the
    stored status. ``test_playbooks_repository`` proves the two agree for every
    outcome from every prior status.
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
