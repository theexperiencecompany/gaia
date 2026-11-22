"""The task search index: one Chroma entry per task, its title, details and GAIA's notes.

Kept in sync by the task writes that change what is indexed (create, edit, notes, close,
reopen, delete). An index write that fails is logged and the task write stands: the
index is a search aid, and scripts/reindex_tasks.py rebuilds any entry it lacks.
"""

from collections.abc import Sequence

from langchain_chroma import Chroma
from pydantic import BaseModel, ConfigDict

from app.constants.chroma import CHROMA_TASKS_COLLECTION
from app.constants.log_tags import LogTag
from app.constants.tasks import TASK_SEARCH_LIMIT, Assignee
from app.db.chroma.chromadb import ChromaClient
from app.models.task_models import DateWhen, TaskDocument
from app.services.canvas_markdown import written_lines
from shared.py.wide_events import log


class TaskIndexMetadata(BaseModel):
    """What a search filters on; Chroma keeps no nulls, so a top-level task's parent is ""."""

    model_config = ConfigDict(extra="ignore")

    user_id: str
    task_id: str
    assignee: Assignee
    completed: bool
    parent_id: str = ""
    when_kind: str
    #: A dated task's due time as a POSIX timestamp; 0 for every other task.
    due_at: float = 0


class TaskMatch(BaseModel):
    """One task a search found, nearest first, with the indexed text it matched on."""

    task_id: str
    distance: float
    text: str


async def task_index() -> Chroma:
    return await ChromaClient.get_langchain_client(collection_name=CHROMA_TASKS_COLLECTION)


def indexed_text(task: TaskDocument) -> str:
    notes = written_lines(task.notes)
    return "\n\n".join(part for part in (task.title, task.body, notes) if part.strip())


def _metadata(task: TaskDocument) -> TaskIndexMetadata:
    return TaskIndexMetadata(
        user_id=task.user_id,
        task_id=task.id,
        assignee=task.assignee,
        completed=task.completed,
        parent_id=task.parent_id or "",
        when_kind=task.when.kind.value,
        due_at=task.when.at.timestamp() if isinstance(task.when, DateWhen) else 0,
    )


async def write_entries(index: Chroma, tasks: Sequence[TaskDocument]) -> None:
    """Upsert tasks' entries, keyed by task id, so a rewrite replaces the old text."""
    await index.aadd_texts(
        texts=[indexed_text(task) for task in tasks],
        metadatas=[_metadata(task).model_dump(mode="json") for task in tasks],
        ids=[task.id for task in tasks],
    )


async def index_task(task: TaskDocument) -> None:
    try:
        await write_entries(await task_index(), [task])
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} task index write failed",
            task_id=task.id,
            user_id=task.user_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def drop_from_index(user_id: str, task_ids: Sequence[str]) -> None:
    if not task_ids:
        return
    try:
        await (await task_index()).adelete(ids=list(task_ids))
    except Exception as e:
        log.error(
            f"{LogTag.CHROMA} task index delete failed",
            user_id=user_id,
            task_count=len(task_ids),
            error=str(e),
            error_type=type(e).__name__,
        )


def _filter(
    user_id: str, assignee: Assignee | None, include_done: bool, parent_id: str | None
) -> dict[str, object]:
    clauses: list[dict[str, object]] = [{"user_id": user_id}]
    if assignee is not None:
        clauses.append({"assignee": assignee.value})
    if not include_done:
        clauses.append({"completed": False})
    if parent_id is not None:
        clauses.append({"parent_id": parent_id})
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


async def search_tasks(
    user_id: str,
    query: str,
    *,
    assignee: Assignee | None = None,
    include_done: bool = True,
    parent_id: str | None = None,
    limit: int = TASK_SEARCH_LIMIT,
) -> list[TaskMatch]:
    """Return the user's tasks nearest in meaning to query, nearest first."""
    found = await (await task_index()).asimilarity_search_with_score(
        query, k=limit, filter=_filter(user_id, assignee, include_done, parent_id)
    )
    return [
        TaskMatch(
            task_id=TaskIndexMetadata.model_validate(doc.metadata).task_id,
            distance=distance,
            text=doc.page_content,
        )
        for doc, distance in found
    ]


async def indexed_ids(index: Chroma, task_ids: Sequence[str]) -> set[str]:
    """Return which of task_ids have an index entry."""
    stored = index.get(ids=list(task_ids), include=[])
    return set(stored["ids"])
