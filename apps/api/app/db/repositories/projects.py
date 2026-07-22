"""Repository for the projects collection."""

from app.constants.cache import PROJECT_CACHE_PREFIX
from app.db.repositories.base import UserScopedRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.todo_models import ProjectDocument, ProjectUpdate, ProjectWithCount


class ProjectsRepository(UserScopedRepository[ProjectDocument, ProjectUpdate]):
    collection_name = "projects"
    document_model = ProjectDocument
    update_model = ProjectUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix=PROJECT_CACHE_PREFIX)

    async def get_default_inbox(self, user_id: str) -> ProjectDocument | None:
        """The user's default Inbox project, or ``None`` if not created yet."""
        return await self._find_one({"user_id": user_id, "is_default": True})

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every project owned by ``user_id`` (dev-data reset); returns the count."""
        return await self._delete_many({"user_id": user_id}, scope=user_id)

    async def get_or_create_inbox(self, user_id: str) -> ProjectDocument:
        """Return the user's Inbox project, creating it on first access."""
        existing = await self.get_default_inbox(user_id)
        if existing is not None:
            return existing
        return await self.create(
            ProjectDocument(
                user_id=user_id,
                name="Inbox",
                description="Default project for new todos",
                color="#6B7280",
                is_default=True,
            )
        )

    @cached_query(list[ProjectWithCount])
    async def list_with_counts(self, *, user_id: str) -> list[ProjectWithCount]:
        """All of a user's projects, newest first, each with its todo count.

        The ``todo_count`` derives from the todos collection, so it is eventually
        consistent: this query cache is orphaned by *project* writes, not by todo
        writes, so a count can lag a todo move by at most ``REPO_QUERY_TTL`` (or
        until the next project mutation). The count is a secondary display value;
        the authoritative list of todos never comes from here.
        """
        pipeline: list[dict[str, object]] = [
            {"$match": {"user_id": user_id}},
            {"$sort": {"created_at": -1}},
            {
                "$lookup": {
                    "from": "todos",
                    "let": {"project_id": {"$toString": "$_id"}},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$user_id", user_id]},
                                        {"$eq": ["$project_id", "$$project_id"]},
                                    ]
                                }
                            }
                        },
                        {"$count": "count"},
                    ],
                    "as": "todo_stats",
                }
            },
            {"$addFields": {"todo_count": {"$ifNull": [{"$first": "$todo_stats.count"}, 0]}}},
            {"$addFields": {"id": {"$toString": "$_id"}}},
        ]
        return await self._aggregate(pipeline, ProjectWithCount)


project_repository = ProjectsRepository()
