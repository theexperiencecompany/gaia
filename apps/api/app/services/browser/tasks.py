"""Browser task-history service: record a finished task and list a user's history.

A task's step screenshots already live in R2 (``services/browser/screenshots.py``)
keyed by session id, so a history row only stores ``session_id`` + ``steps`` and
rebuilds the recap image URLs on read — durable long after the live session ends.
"""

from app.config.settings import settings
from app.db.repositories.browser_tasks import browser_task_repository
from app.models.browser_task_models import BrowserTaskDocument
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskResponse


async def record_browser_task(
    *,
    user_id: str,
    conversation_id: str,
    task: str,
    session_id: str,
    result: BrowserResultSnapshot,
) -> None:
    """Persist a finished browser task (any outcome) so it appears in the user's history."""
    await browser_task_repository.create(
        BrowserTaskDocument(
            user_id=user_id,
            conversation_id=conversation_id,
            task=task,
            status=result.status,
            success=result.success,
            session_id=session_id,
            steps=result.steps,
            replay_url=result.replay_url,
        )
    )


def _screenshot_urls(session_id: str, steps: int) -> list[str]:
    """Public R2 URLs for a task's step screenshots (empty if R2 isn't configured)."""
    base = settings.R2_PUBLIC_BASE_URL
    if not base or steps < 1:
        return []
    root = base.rstrip("/")
    return [f"{root}/browser_steps/{session_id}/step_{i}.png" for i in range(1, steps + 1)]


async def list_browser_tasks(user_id: str, *, limit: int = 20) -> list[BrowserTaskResponse]:
    """A user's browser-task history, newest first, each with its recap screenshot URLs."""
    docs = await browser_task_repository.list_recent_for_user(user_id, limit=limit)
    return [
        BrowserTaskResponse(
            id=doc.id,
            task=doc.task,
            status=doc.status,
            success=doc.success,
            steps=doc.steps,
            created_at=doc.created_at,
            conversation_id=doc.conversation_id,
            screenshots=_screenshot_urls(doc.session_id, doc.steps),
        )
        for doc in docs
    ]
