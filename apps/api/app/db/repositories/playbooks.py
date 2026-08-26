"""Repository for the ``playbooks`` collection — one active playbook per workflow.

Global, keyed by the business ``playbook_id``. There is no version history: the
agent revises a playbook by writing the whole document again, so
``upsert_for_workflow`` overwrites the workflow's single record in place and a
stale sequence can never be replayed by accident.

Uncached (``cache_policy = None``): a playbook is read once per run, and the
overwrite-on-revise shape is exactly what an entity cache would misrepresent.
"""

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
        """Write the workflow's playbook, replacing whatever it had.

        A revision resets ``last_run_status``: the previous run's outcome
        described the sequence that was just thrown away.
        """
        existing = await self.get_for_workflow(playbook.workflow_id, playbook.user_id)
        if existing is None:
            return await self.create(playbook)

        replaced = await self.update(
            existing.playbook_id,
            PlaybookUpdate(
                description=playbook.description,
                steps=playbook.steps,
                ask=playbook.ask,
                synthesize=playbook.synthesize,
                workflow_hash=playbook.workflow_hash,
                raw_yaml=playbook.raw_yaml,
                last_run_status=PlaybookRunStatus.NOT_RUN,
            ),
        )
        if replaced is None:
            raise RuntimeError(f"playbook {existing.playbook_id} vanished mid-overwrite")
        return replaced

    async def record_run_outcome(
        self, workflow_id: str, user_id: str, status: PlaybookRunStatus
    ) -> PlaybookDocument | None:
        """Record how the replay that just finished went. ``None`` if the
        workflow has no playbook (an agentic run has nothing to record)."""
        existing = await self.get_for_workflow(workflow_id, user_id)
        if existing is None:
            return None
        return await self.update(existing.playbook_id, PlaybookUpdate(last_run_status=status))

    async def delete_for_workflow(self, workflow_id: str, user_id: str) -> bool:
        """Drop the workflow's playbook. ``False`` when there was none."""
        existing = await self.get_for_workflow(workflow_id, user_id)
        if existing is None:
            return False
        return await self.delete(existing.playbook_id)


playbook_repository = PlaybooksRepository()
