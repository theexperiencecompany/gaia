"""Fill the task search index from the tasks collection, and prove every task has its entry.

Kept apart from the migration: the migration only moves Mongo documents and runs against
any copy by URI, while indexing embeds every task through the deployment's model. Both
steps are idempotent, keyed by task id, so a rerun after a failure finishes the job.
"""

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field

from langchain_chroma import Chroma
from motor.motor_asyncio import AsyncIOMotorDatabase
from scripts.tasks_migration.migrate import Document
from scripts.tasks_migration.parity import Diff, ParityReport

from app.constants.tasks import TASK_INDEX_BATCH
from app.models.task_models import TaskDocument
from app.services.tasks.search_index import indexed_ids, write_entries

INDEX = "tasks_index"


@dataclass
class ReindexReport:
    indexed: int = 0
    users: set[str] = field(default_factory=set)

    def summary(self) -> str:
        return f"task search index: {self.indexed} task(s) of {len(self.users)} user(s) indexed"


def _scope(user_ids: Iterable[str] | None) -> Document:
    return {} if user_ids is None else {"user_id": {"$in": sorted(user_ids)}}


async def _batches(
    db: AsyncIOMotorDatabase[Document], scope: Document
) -> AsyncIterator[list[TaskDocument]]:
    """Every task in scope, TASK_INDEX_BATCH at a time, in _id order."""
    after: str | None = None
    while True:
        page_filter = scope if after is None else {**scope, "_id": {"$gt": after}}
        raw = (
            await db["tasks"]
            .find(page_filter)
            .sort("_id", 1)
            .limit(TASK_INDEX_BATCH)
            .to_list(TASK_INDEX_BATCH)
        )
        if not raw:
            return
        after = raw[-1]["_id"]
        yield [TaskDocument.model_validate({**doc, "id": doc["_id"]}) for doc in raw]


async def reindex(
    db: AsyncIOMotorDatabase[Document], index: Chroma, *, user_ids: Iterable[str] | None = None
) -> ReindexReport:
    """Write every task's entry; an entry already there is replaced by the task as it is now."""
    report = ReindexReport()
    async for batch in _batches(db, _scope(user_ids)):
        await write_entries(index, batch)
        report.indexed += len(batch)
        report.users.update(task.user_id for task in batch)
    return report


def _entry_ids(index: Chroma, user_ids: Iterable[str] | None) -> set[str]:
    """Every entry id the index holds for the users in scope (all users when None)."""
    where = None if user_ids is None else {"user_id": {"$in": sorted(user_ids)}}
    found: set[str] = set()
    while True:
        page = index.get(where=where, include=[], limit=TASK_INDEX_BATCH, offset=len(found))
        if not page["ids"]:
            return found
        found.update(page["ids"])


async def check_index(
    db: AsyncIOMotorDatabase[Document], index: Chroma, *, user_ids: Iterable[str] | None = None
) -> ParityReport:
    """Count tasks against index entries: every task has one, and no entry outlives its task."""
    report = ParityReport()
    task_ids: set[str] = set()
    async for batch in _batches(db, _scope(user_ids)):
        ids = [task.id for task in batch]
        task_ids.update(ids)
        for missing in sorted(set(ids) - await indexed_ids(index, ids)):
            report.diffs.append(Diff(INDEX, missing, "entry", "indexed", "missing"))
    entries = _entry_ids(index, user_ids)
    for orphan in sorted(entries - task_ids):
        report.diffs.append(Diff(INDEX, orphan, "entry", "no entry (task gone)", "indexed"))
    report.counts["tasks_to_index"] = len(task_ids)
    report.counts["index_entries"] = len(entries)
    return report
