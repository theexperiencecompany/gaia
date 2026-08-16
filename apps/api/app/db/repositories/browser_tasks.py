"""Repository for the ``browser_tasks`` collection — one record per finished browser task.

Written once when a browser task ends (any outcome) and read back for the user's
browser history in settings. No cache: the history view is read on demand, not hot.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.browser_task_models import BrowserTaskDocument, BrowserTaskUpdate


class BrowserTasksRepository(UserScopedRepository[BrowserTaskDocument, BrowserTaskUpdate]):
    collection_name = "browser_tasks"
    document_model = BrowserTaskDocument
    update_model = BrowserTaskUpdate
    uses_object_id = True
    cache_policy = None

    async def list_recent_for_user(
        self, user_id: str, *, limit: int = 20
    ) -> list[BrowserTaskDocument]:
        """A user's finished browser tasks, most recent first."""
        return await self.list_for_user(user_id, sort=[("created_at", -1)], limit=limit)


browser_task_repository = BrowserTasksRepository()
