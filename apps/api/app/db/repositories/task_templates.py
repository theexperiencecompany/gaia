"""Repository for task_templates: the Explore page, the community list and public links.

Global (templates are public reads) and uncached here, so a publish or an unpublish is
visible on the next read; the community list's five-minute cache was the bug that hid them.
"""

from collections.abc import Sequence
import re

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.constants.tasks import TemplateOrigin
from app.db.repositories.base import MongoRepository
from app.models.task_template_models import TaskTemplateDocument

_SEARCHABLE = ("title", "summary", "source_integration")


class TaskTemplatesRepository(MongoRepository[TaskTemplateDocument, TaskTemplateDocument]):
    collection_name = "task_templates"
    document_model = TaskTemplateDocument
    update_model = TaskTemplateDocument
    uses_object_id = False
    cache_policy = None

    async def get_by_ref(self, ref: str) -> TaskTemplateDocument | None:
        """Return the template a public link names, by its slug or its id."""
        return await self._find_one({"$or": [{"slug": ref}, {"_id": ref}]})

    async def find_slug_holder(
        self, slug: str, *, exclude_id: str | None = None
    ) -> TaskTemplateDocument | None:
        """Return the template already holding slug, or None when it is free."""
        filt: dict[str, object] = {"slug": slug}
        if exclude_id is not None:
            filt["_id"] = {"$ne": exclude_id}
        return await self._find_one(filt)

    async def find_for_task(self, task_id: str) -> TaskTemplateDocument | None:
        """Return the template a task was published as."""
        return await self._find_one({"source_task_id": task_id})

    async def list_by_origin(
        self, origin: TemplateOrigin, *, limit: int, offset: int
    ) -> tuple[list[TaskTemplateDocument], int]:
        """Return a page of one origin's templates and their total.

        Community templates come newest first; curated ones most-run first.
        """
        sort = (
            [("created_at", -1)]
            if origin is TemplateOrigin.COMMUNITY
            else [("run_count", -1), ("updated_at", -1)]
        )
        filt = {"origin": origin.value}
        rows = await self._find(filt, sort=sort, limit=limit, skip=offset)
        return rows, await self._count(filt)

    async def search(self, patterns: Sequence[str], *, limit: int) -> list[TaskTemplateDocument]:
        """Return templates matching any pattern in title, summary or source app, curated first, then most-run."""
        if not patterns:
            return []
        filt = {
            "$or": [
                {field: {"$regex": re.escape(pattern), "$options": "i"}}
                for pattern in patterns
                for field in _SEARCHABLE
            ]
        }
        # "curated" sorts after "community", so descending puts the curated set first.
        return await self._find(
            filt, sort=[("origin", -1), ("run_count", -1), ("updated_at", -1)], limit=limit
        )

    async def list_by_tool_category(
        self, category: str, *, limit: int, offset: int
    ) -> tuple[list[TaskTemplateDocument], int]:
        """Return a page of templates whose cards show a tool category matching category, most-run first."""
        filt = {"tool_categories": {"$regex": re.escape(category), "$options": "i"}}
        rows = await self._find(
            filt, sort=[("run_count", -1), ("created_at", -1)], limit=limit, skip=offset
        )
        return rows, await self._count(filt)

    async def delete_for_task(self, task_id: str) -> bool:
        """Remove the template a task was published as: an unpublish."""
        return (await self._delete_many({"source_task_id": task_id}, scope=REPO_GLOBAL_SCOPE)) > 0


task_template_repository = TaskTemplatesRepository()
