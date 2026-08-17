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
            replay_url=result.replay_url,
        )
    )


def _frames(session_id: str, steps: int, step_goals: list[str]) -> list[BrowserTaskFrame]:
    """Recap frames (R2 screenshot URL + step caption) in order; empty if R2 is off."""
    base = settings.R2_PUBLIC_BASE_URL
    if not base or steps < 1:
        return []
    root = base.rstrip("/")
    return [
        BrowserTaskFrame(
            url=f"{root}/browser_steps/{session_id}/step_{i}.png",
            caption=(step_goals[i - 1].strip() or None) if i - 1 < len(step_goals) else None,
        )
        for i in range(1, steps + 1)
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
            frames=_frames(doc.session_id, doc.steps, doc.step_goals),
        )
        for doc in docs
    ]
