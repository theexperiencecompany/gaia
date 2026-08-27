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
    PlaybookRunStatus,
    PlaybookUpdate,
)


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

        A revision resets ``last_run_status``: the previous run's outcome
        described the sequence that was just thrown away. ``playbook_id`` and
        ``created_at`` are only ever set on insert, so a rewrite keeps the id the
        worker may be replaying under.

        Two first authorings racing on the same workflow can both miss the match
        and both insert; the unique ``(workflow_id, user_id)`` index rejects the
        loser with ``DuplicateKeyError``, and the retry then matches the winner
        and overwrites it — the same result as if the two had run in sequence.
        """
        body = PlaybookUpdate(
            description=playbook.description,
            steps=playbook.steps,
            ask=playbook.ask,
            synthesize=playbook.synthesize,
            workflow_hash=playbook.workflow_hash,
            last_run_status=PlaybookRunStatus.NOT_RUN,
        ).model_dump(exclude_unset=True)
        update = {
            "$set": body,
            "$setOnInsert": {
                "playbook_id": playbook.playbook_id,
                "created_at": playbook.created_at,
            },
        }
        key = {"workflow_id": playbook.workflow_id, "user_id": playbook.user_id}
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
        status: PlaybookRunStatus,
        *,
        playbook_id: str | None = None,
    ) -> PlaybookDocument | None:
        """Record how the replay that just finished went.

        With ``playbook_id`` — the id of the playbook that was actually replayed —
        the write lands only while that playbook is still the workflow's, so a
        replay finishing after the agent re-authored it cannot stamp the old
        run's verdict on the new sequence. ``None`` when the workflow has no
        playbook (an agentic run has nothing to record) or when the replayed one
        has since been replaced.
        """
        if playbook_id is None:
            existing = await self.get_for_workflow(workflow_id, user_id)
            if existing is None:
                return None
            return await self.update(existing.playbook_id, PlaybookUpdate(last_run_status=status))
        return await self._apply_update(
            playbook_id,
            REPO_GLOBAL_SCOPE,
            {"workflow_id": workflow_id, "user_id": user_id},
            PlaybookUpdate(last_run_status=status),
        )

    async def delete_for_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Drop the workflow's playbook. ``False`` when there was none."""
        existing = await self.get_for_workflow(workflow_id, user_id)
        if existing is None:
            return False
        return await self.delete(existing.playbook_id)


playbook_repository = PlaybooksRepository()
