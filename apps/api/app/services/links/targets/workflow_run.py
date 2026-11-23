"""One workflow execution's outcome."""

from app.db.repositories.workflow_executions import workflow_executions_repository
from app.db.repositories.workflows import workflow_repository
from app.models.short_link_models import (
    LinkSnapshot,
    LinkViewerKind,
    PublicWorkflowRun,
    RecordTarget,
    ShortLink,
    ShortLinkTargetType,
)
from app.services.links.spec import LinkTargetSpec, PreviewFacts


async def _run(owner_id: str, target: RecordTarget) -> PublicWorkflowRun | None:
    execution = await workflow_executions_repository.get_for_user(target.id, owner_id)
    if execution is None:
        return None
    workflow = await workflow_repository.get_for_user(execution.workflow_id, owner_id)
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


async def _project(
    link: ShortLink, target: RecordTarget, _viewer: LinkViewerKind
) -> PublicWorkflowRun | None:
    return await _run(link.user_id, target)


async def _preview(
    owner_id: str, target: RecordTarget, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    run = await _run(owner_id, target)
    return PreviewFacts(title=run.workflow_title, image_url=None) if run else None


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.WORKFLOW_RUN,
    target=RecordTarget,
    kind_line="What a GAIA workflow did, shared with you.",
    project=_project,
    preview=_preview,
)
