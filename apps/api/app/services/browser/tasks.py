"""Browser task-history service: record a finished task and list a user's history.

A task's step screenshots already live in R2 (``services/browser/screenshots.py``)
keyed by session id, so a history row only stores ``session_id`` + ``steps`` and
rebuilds the recap image URLs on read — durable long after the live session ends.
"""

from app.config.settings import settings
from app.db.repositories.browser_tasks import browser_task_repository
from app.models.browser_task_models import BrowserTaskDocument
from app.schemas.browser import BrowserResultSnapshot, BrowserTaskFrame, BrowserTaskResponse


async def record_browser_task(
    *,
    user_id: str,
    conversation_id: str,
    task: str,
    session_id: str,
    result: BrowserResultSnapshot,
    step_goals: list[str] | None = None,
    step_screenshots: list[str] | None = None,
    source: str = "",
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
            step_goals=step_goals or [],
            step_screenshots=step_screenshots or [],
            source=source,
            replay_url=result.replay_url,
        )
    )


async def delete_browser_task(user_id: str, task_id: str) -> bool:
    """Delete one of the user's browser-task history records."""
    return await browser_task_repository.delete(task_id, user_id=user_id)


def _caption(step_goals: list[str], index: int) -> str | None:
    return (step_goals[index].strip() or None) if index < len(step_goals) else None


def _frames(doc: BrowserTaskDocument) -> list[BrowserTaskFrame]:
    """Recap frames (screenshot URL + step caption), in step order.

    Uses the screenshots the run actually uploaded. A step whose upload failed
    has no frame rather than a URL that 404s. Tasks recorded before those URLs
    were stored fall back to deriving them from the session id.
    """
    if doc.step_screenshots:
        return [
            BrowserTaskFrame(url=url, caption=_caption(doc.step_goals, i))
            for i, url in enumerate(doc.step_screenshots)
            if url
        ]

    base = settings.R2_PUBLIC_BASE_URL
    if not base or doc.steps < 1:
        return []
    root = base.rstrip("/")
    return [
        BrowserTaskFrame(
            url=f"{root}/browser_steps/{doc.session_id}/step_{i}.png",
            caption=_caption(doc.step_goals, i - 1),
        )
        for i in range(1, doc.steps + 1)
    ]


async def list_browser_tasks(user_id: str, *, limit: int = 20) -> list[BrowserTaskResponse]:
    """A user's browser-task history, newest first, each with its recap frames."""
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
            source=doc.source,
            frames=_frames(doc),
        )
        for doc in docs
    ]
