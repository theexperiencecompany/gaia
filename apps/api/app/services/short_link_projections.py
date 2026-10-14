"""Per-target-type public projections for heygaia.link short links.

One registry, one rule: a resolver reads its target scoped to the link's OWNER
(never a viewer) and maps it onto that type's public view model in
app/models/short_link_models.py. The view models are extra="forbid", so
a field reaches a recipient only when a projector here names it explicitly —
nothing on the stored document leaks by default.

The same projector is the ownership check at mint time: a target the user does
not own projects to None, so no one can mint a link to someone else's work.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.agents.workspace.paths import is_inlineable_content_type
from app.db.repositories.briefings import briefing_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.short_link_models import (
    PublicBriefing,
    PublicBriefingEvent,
    PublicBriefingItem,
    PublicBriefingPayload,
    PublicBriefingSection,
    PublicSessionArtifact,
    PublicShortLinkView,
    PublicTodoDeliverable,
    PublicWorkflowRun,
    ShortLinkTargetType,
)
from app.services.canvas_markdown import deliverable_markdown
from app.services.storage import ArtifactInfo, resolve_session_path, stat_artifact

_DEFAULT_CONTENT_TYPE = "application/octet-stream"
# Text files up to this size ship in the public view so the page renders them
# directly — an HTML report as a live page in a sandboxed frame, not a download.
# Larger than the chat's inline cap: a shared report is opened on purpose.
PUBLIC_TEXT_MAX_BYTES = 2 * 1024 * 1024


def session_artifact_target_id(conversation_id: str, path: str) -> str:
    """Return the target id of the file at path under one conversation's artifacts/.

    A session artifact has no id of its own. Conversation ids are path-safe (no
    /), so the first / is always the separator _locate_session_artifact
    splits on.
    """
    return f"{conversation_id}/{path}"


async def _project_todo(user_id: str, target_id: str) -> PublicTodoDeliverable | None:
    todo = await todo_repository.get(target_id, user_id=user_id)
    if todo is None:
        return None
    return PublicTodoDeliverable(
        target_type=ShortLinkTargetType.TODO_DELIVERABLE,
        title=todo.title,
        completed=todo.completed,
        content=deliverable_markdown(todo.canvas_content or ""),
    )


async def _project_briefing(user_id: str, target_id: str) -> PublicBriefing | None:
    briefing = await briefing_repository.get(target_id, user_id=user_id)
    if briefing is None:
        return None
    payload = briefing.payload
    return PublicBriefing(
        target_type=ShortLinkTargetType.BRIEFING,
        kind=briefing.kind,
        edition_image_url=briefing.edition_image_url,
        payload=PublicBriefingPayload(
            kicker=payload.kicker,
            date=payload.date,
            headline=payload.headline,
            lede=payload.lede,
            stats=payload.stats,
            sections=[
                PublicBriefingSection(
                    numeral=section.numeral,
                    title=section.title,
                    items=[
                        PublicBriefingItem(text=item.text, kind=item.kind, link=item.link)
                        for item in section.items
                    ],
                )
                for section in payload.sections
            ],
            mood=payload.mood,
            caption=payload.caption,
            hue=payload.hue,
            calendar=[
                PublicBriefingEvent(date=event.date, start=event.start, title=event.title)
                for event in payload.calendar
            ],
        ),
    )


@dataclass(frozen=True)
class _SessionArtifactFile:
    host_path: Path
    info: ArtifactInfo


async def _locate_session_artifact(user_id: str, target_id: str) -> _SessionArtifactFile | None:
    """Return the owner's artifact file behind target_id, or None once it is gone.

    Raises JuiceFSUnavailable when workspace storage is offline — that is an
    outage, not a missing file, and the caller must say so. A target id whose
    conversation id is unsafe or whose path escapes the artifacts root names no
    artifact, so it is missing too.
    """
    conversation_id, _, path = target_id.partition("/")
    if not conversation_id or not path:
        return None
    try:
        info = await stat_artifact(user_id, conversation_id, path)
    except ValueError:
        return None
    if info is None:
        return None
    host_path = await resolve_session_path(user_id, conversation_id, "artifacts", path)
    return _SessionArtifactFile(host_path=host_path, info=info)


async def session_artifact_file(user_id: str, target_id: str) -> Path | None:
    """Return the host path the public file route streams, or None once it is gone."""
    located = await _locate_session_artifact(user_id, target_id)
    return located.host_path if located else None


async def _project_session_artifact(user_id: str, target_id: str) -> PublicSessionArtifact | None:
    located = await _locate_session_artifact(user_id, target_id)
    if located is None:
        return None
    info = located.info
    content: str | None = None
    if is_inlineable_content_type(info.content_type) and info.size_bytes <= PUBLIC_TEXT_MAX_BYTES:
        raw = await asyncio.to_thread(located.host_path.read_bytes)
        content = raw.decode(errors="replace")
    return PublicSessionArtifact(
        target_type=ShortLinkTargetType.SESSION_ARTIFACT,
        filename=located.host_path.name,
        content_type=info.content_type or _DEFAULT_CONTENT_TYPE,
        size_bytes=info.size_bytes,
        content=content,
    )


async def _project_workflow_run(user_id: str, target_id: str) -> PublicWorkflowRun | None:
    execution = await workflow_executions_repository.get_for_user(target_id, user_id)
    if execution is None:
        return None
    workflow = await workflow_repository.get_for_user(execution.workflow_id, user_id)
    if workflow is None:
        return None
    return PublicWorkflowRun(
        target_type=ShortLinkTargetType.WORKFLOW_RUN,
        workflow_title=workflow.title,
        status=execution.status,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        summary=execution.summary or "",
    )


Projector = Callable[[str, str], Awaitable[PublicShortLinkView | None]]

_PROJECTORS: dict[ShortLinkTargetType, Projector] = {
    ShortLinkTargetType.TODO_DELIVERABLE: _project_todo,
    ShortLinkTargetType.BRIEFING: _project_briefing,
    ShortLinkTargetType.SESSION_ARTIFACT: _project_session_artifact,
    ShortLinkTargetType.WORKFLOW_RUN: _project_workflow_run,
}


async def project_target(
    target_type: ShortLinkTargetType, user_id: str, target_id: str
) -> PublicShortLinkView | None:
    """Return the public view of target_id as user_id owns it.

    None when that owner has no such target.
    """
    return await _PROJECTORS[target_type](user_id, target_id)
