"""A tracked todo's deliverable: its title and the deliverable facet of its canvas."""

from app.db.repositories.todos import todo_repository
from app.models.short_link_models import LinkSnapshot, PublicTodoDeliverable, ShortLinkTargetType
from app.services.canvas_markdown import deliverable_markdown
from app.services.links.spec import LinkTargetSpec, PreviewFacts


async def _project(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PublicTodoDeliverable | None:
    todo = await todo_repository.get(target_id, user_id=owner_id)
    if todo is None:
        return None
    return PublicTodoDeliverable(
        target_type=ShortLinkTargetType.TODO_DELIVERABLE,
        title=todo.title,
        completed=todo.completed,
        content=deliverable_markdown(todo.canvas_content or ""),
    )


async def _preview(
    owner_id: str, target_id: str, _snapshot: LinkSnapshot | None
) -> PreviewFacts | None:
    todo = await todo_repository.get(target_id, user_id=owner_id)
    return PreviewFacts(title=todo.title, image_url=None) if todo else None


SPEC = LinkTargetSpec(
    type=ShortLinkTargetType.TODO_DELIVERABLE,
    kind_line="Something GAIA worked on, shared with you.",
    project=_project,
    preview=_preview,
)
