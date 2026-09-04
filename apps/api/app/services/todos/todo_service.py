import asyncio
from datetime import UTC, datetime
import math
import uuid

from app.db.repositories.projects import project_repository
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.todo_models import (
    BulkMoveRequest,
    BulkOperationResponse,
    BulkUpdateRequest,
    PaginationMeta,
    Priority,
    ProjectCreate,
    ProjectDocument,
    ProjectResponse,
    ProjectUpdate,
    SearchMode,
    SubTask,
    TodoDocument,
    TodoLabelCount,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdate,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.triggers.subscription_service import teardown_subscriptions
from app.services.user_todos_fs import schedule_user_todos_sync
from app.utils.canvas_vector_utils import delete_canvas_embedding
from app.utils.todo_vector_utils import (
    delete_todo_embedding,
    hybrid_search_todos as vector_hybrid_search,
    semantic_search_todos as vector_search,
    store_todo_embedding,
    update_todo_embedding,
)
from shared.py.wide_events import log, spawn_logged_task


async def _get_workflow_categories_for_todos(
    todos: list[TodoDocument], user_id: str
) -> dict[str, list[str]]:
    """Fetch workflow step categories for todos that have linked workflows.

    Returns a dict mapping todo_id -> list of unique tool categories (cross-domain
    read via the workflow repository)."""
    workflow_ids = [todo.workflow_id for todo in todos if todo.workflow_id]
    if not workflow_ids:
        return {}

    workflows = await workflow_repository.find_by_ids_for_user(workflow_ids, user_id)

    workflow_categories: dict[str, list[str]] = {}
    for workflow in workflows:
        categories = list(dict.fromkeys(step.category for step in workflow.steps if step.category))[
            :3
        ]
        workflow_categories[workflow.id] = categories

    result: dict[str, list[str]] = {}
    for todo in todos:
        if todo.workflow_id and todo.workflow_id in workflow_categories:
            result[todo.id] = workflow_categories[todo.workflow_id]
    return result


def _ensure_subtask_ids(subtasks: list[SubTask]) -> list[SubTask]:
    """Give every subtask a stable id, generating one where it is missing."""
    result: list[SubTask] = []
    for subtask in subtasks:
        result.append(
            subtask if subtask.id else subtask.model_copy(update={"id": str(uuid.uuid4())})
        )
    return result


def _to_todo_update(updates: TodoUpdateRequest) -> TodoUpdate:
    """Project a partial API update onto the repository's ``$set`` model.

    ``None`` means "not provided" on this API — no field can be cleared through
    it — so None-valued fields are dropped rather than written as nulls, and the
    resulting model's set fields are exactly what will be written.
    """
    update = TodoUpdate(**updates.model_dump(exclude_none=True))
    if update.subtasks is not None:
        update.subtasks = _ensure_subtask_ids(update.subtasks)
    return update


def _drop_completion_fields(update: TodoUpdate) -> TodoUpdate:
    """Rebuild ``update`` without the completion fields.

    A ``TodoUpdate`` writes exactly the fields that are *set* on it, and a field
    cannot be un-set in place, so dropping one means rebuilding from the rest.
    """
    fields = update.model_dump(exclude_unset=True)
    fields.pop("completed", None)
    fields.pop("completed_at", None)
    return TodoUpdate(**fields)


class TodoService:
    """Service class for todo operations. Persistence + caching live in the
    todos/projects repositories; this layer holds orchestration only."""

    @staticmethod
    async def _get_inbox_id(user_id: str) -> str:
        """Resolve (creating on first use) the user's default Inbox project id."""
        inbox = await project_repository.get_or_create_inbox(user_id)
        return inbox.id

    @staticmethod
    def _needs_inbox_default(params: TodoSearchParams) -> bool:
        """The unfiltered main list scopes to Inbox; every filtered view does not."""
        return not (
            params.project_id
            or params.q
            or params.completed is not None
            or params.priority
            or params.labels
        )

    @staticmethod
    async def _calculate_stats(user_id: str) -> TodoStats:
        """Todo statistics for a user (cached inside the repository)."""
        return await todo_repository.compute_stats(user_id=user_id)

    # CRUD Operations
    @classmethod
    async def create_todo(cls, todo: TodoModel, user_id: str) -> TodoResponse:
        """Create a new todo with automatic inbox assignment."""
        log.set(
            component="todo_service",
            operation="create_todo",
            user_id=user_id,
            todo={
                "title": todo.title,
                "project_id": todo.project_id,
                "priority": str(todo.priority) if todo.priority else None,
                "has_due_date": todo.due_date is not None,
                "is_completed": False,
                "user_id": user_id,
            },
        )
        # Whether the caller filed the todo into a project themselves — read
        # before the Inbox default below makes project_id unconditionally set.
        project_chosen = todo.project_id is not None
        if not todo.project_id:
            todo.project_id = await cls._get_inbox_id(user_id)
        else:
            project = await project_repository.get(todo.project_id, user_id=user_id)
            if not project:
                raise ValueError(f"Project {todo.project_id} not found")

        document = TodoDocument(
            user_id=user_id,
            title=todo.title,
            description=todo.description,
            labels=todo.labels,
            due_date=todo.due_date,
            due_date_timezone=todo.due_date_timezone,
            priority=todo.priority,
            project_id=todo.project_id,
            completed=False,
            subtasks=_ensure_subtask_ids(todo.subtasks),
            workflow_id=todo.workflow_id,
            workflow_activated=True,  # Start activated by default
            vfs_path=todo.vfs_path,
            scheduled_at=todo.scheduled_at,
            recurrence=todo.recurrence,
            gaia_retry_count=todo.gaia_retry_count,
            expires_at=todo.expires_at,
            references=todo.references,
        )
        created = await todo_repository.create(document)

        # Queue workflow generation as fire-and-forget (does not block response)
        try:
            # Deferred import: workflow/ARQ enqueue stack loads only when generation is actually queued
            from app.services.workflow.queue_service import (  # noqa: PLC0415 -- deferred
                WorkflowQueueService,
            )

            spawn_logged_task(
                "todo_workflow_generation",
                WorkflowQueueService.queue_todo_workflow_generation(
                    todo_id=created.id,
                    user_id=user_id,
                    title=todo.title,
                    description=todo.description or "",
                ),
                user={"id": user_id},
                todo={"id": created.id},
            )
            log.info("todo.workflow_generation_queued", todo_id=created.id, title=todo.title)
        except Exception as e:
            log.warning("todo.workflow_queue_failed", title=todo.title, error=str(e))

        # Index for search
        try:
            await store_todo_embedding(created.id, created.model_dump(), user_id)
        except Exception as e:
            log.warning("todo.index_failed", error=str(e))

        schedule_user_todos_sync(user_id)
        capture_event(
            user_id,
            AnalyticsEvents.TODO_CREATED,
            {
                "priority": created.priority.value,
                "has_due_date": created.due_date is not None,
                "has_description": bool(created.description),
                "labels_count": len(created.labels),
                "subtasks_count": len(created.subtasks),
                "has_project": project_chosen,
            },
        )
        return TodoResponse.from_document(created)

    @classmethod
    async def get_todo(cls, todo_id: str, user_id: str) -> TodoResponse:
        """Get a single todo by ID."""
        log.set(component="todo_service", operation="get_todo", user_id=user_id, todo_id=todo_id)
        todo = await todo_repository.get(todo_id, user_id=user_id)
        if not todo:
            raise ValueError(f"Todo {todo_id} not found")

        if todo.workflow_id:
            workflow_categories = await _get_workflow_categories_for_todos([todo], user_id)
            return TodoResponse.from_document(
                todo, workflow_categories=workflow_categories.get(todo.id, [])
            )
        return TodoResponse.from_document(todo)

    @classmethod
    async def list_todos(cls, user_id: str, params: TodoSearchParams) -> TodoListResponse:
        """List todos with filtering, pagination, and optional stats."""
        # Semantic / hybrid search is a vector concern handled separately.
        if params.q and params.mode in [SearchMode.SEMANTIC, SearchMode.HYBRID]:
            return await cls._search_todos(user_id, params)

        inbox_project_id = (
            await cls._get_inbox_id(user_id) if cls._needs_inbox_default(params) else None
        )
        page = await todo_repository.list_page(
            user_id=user_id, params=params, inbox_project_id=inbox_project_id
        )

        workflow_categories = await _get_workflow_categories_for_todos(page.items, user_id)
        data = [
            TodoResponse.from_document(
                todo, workflow_categories=workflow_categories.get(todo.id, [])
            )
            for todo in page.items
        ]
        pages = math.ceil(page.total / params.per_page) if params.per_page else 0
        meta = PaginationMeta(
            total=page.total,
            page=params.page,
            per_page=params.per_page,
            pages=pages,
            has_next=params.page < pages,
            has_prev=params.page > 1,
        )
        response = TodoListResponse(data=data, meta=meta)
        if params.include_stats:
            response.stats = await cls._calculate_stats(user_id)
        return response

    @classmethod
    async def update_todo(
        cls, todo_id: str, updates: TodoUpdateRequest, user_id: str
    ) -> TodoResponse:
        """Update a todo."""
        log.set(
            component="todo_service",
            operation="update_todo",
            user_id=user_id,
            todo={
                "id": todo_id,
                "user_id": user_id,
                "is_completed": updates.completed if updates.completed is not None else None,
                "priority": str(updates.priority) if updates.priority is not None else None,
            },
        )
        update = _to_todo_update(updates)

        if update.project_id is not None:
            project = await project_repository.get(update.project_id, user_id=user_id)
            if not project:
                raise ValueError(f"Project {update.project_id} not found")

        # Track completion timestamp (explicit None clears it when un-completing).
        if update.completed is not None:
            update.completed_at = datetime.now(UTC) if update.completed else None

        # Completing a tracked todo (one with a VFS canvas) must run the tracked
        # lifecycle FIRST — complete_tracked_todo archives the canvas and sets the
        # completion fields itself. So route completion through the service, then
        # strip the completion fields from this update so we don't re-trip the
        # completion guard or clobber the archived vfs_path.
        if update.completed is True:
            existing = await todo_repository.get(todo_id, user_id=user_id)
            if existing and existing.vfs_path:
                try:
                    from app.services.tracked_todo_service import (  # noqa: PLC0415 -- tracked_todo_service imports this module at module level, so a top-level import back would be circular
                        tracked_todo_service,
                    )

                    await tracked_todo_service.complete_tracked_todo(
                        todo_id, user_id, summary="Completed via UI"
                    )
                except Exception as e:
                    log.warning("tracked_todo.ui_complete_failed", todo_id=todo_id, error=str(e))
                update = _drop_completion_fields(update)

        if update.model_fields_set:
            updated = await todo_repository.update(todo_id, user_id=user_id, update=update)
        else:
            # Only a tracked completion happened; it already persisted + invalidated.
            updated = await todo_repository.get(todo_id, user_id=user_id)

        if not updated:
            raise ValueError(f"Todo {todo_id} not found")

        try:
            await update_todo_embedding(todo_id, updated.model_dump(), user_id)
        except Exception as e:
            log.warning("todo.index_update_failed", todo_id=todo_id, error=str(e))

        schedule_user_todos_sync(user_id)
        if updates.completed is not None:
            # Toggle semantics: fires for both completing and un-completing,
            # tracked or plain.
            capture_event(
                user_id,
                AnalyticsEvents.TODO_TOGGLED,
                {
                    "completed": updates.completed,
                    "todo_id": todo_id,
                    "priority": updated.priority.value,
                    "has_due_date": updated.due_date is not None,
                },
            )
        elif update.model_fields_set:
            capture_event(
                user_id,
                AnalyticsEvents.TODO_UPDATED,
                {
                    "changed_field_count": len(update.model_fields_set),
                    "changed_fields": sorted(update.model_fields_set),
                    "todo_id": todo_id,
                    "priority": updated.priority.value,
                    "has_due_date": updated.due_date is not None,
                    "has_subtasks": bool(updated.subtasks),
                },
            )
        return TodoResponse.from_document(updated)

    @classmethod
    async def delete_todo(cls, todo_id: str, user_id: str) -> None:
        """Delete a todo."""
        log.set(component="todo_service", operation="delete_todo", user_id=user_id, todo_id=todo_id)
        doc = await todo_repository.get(todo_id, user_id=user_id)
        if not doc:
            raise ValueError(f"Todo {todo_id} not found")

        # Unregister before the document goes: once it is deleted nothing names
        # the Composio trigger any more, so the registration would leak forever.
        if doc.trigger_subscriptions:
            await teardown_subscriptions(todo_id, user_id, reason="deleted")

        # Tracked-todo canvas/log content lives on the doc, so it disappears with
        # the delete below — only the ChromaDB canvas embedding needs cleanup.
        if doc.vfs_path:
            try:
                await delete_canvas_embedding(todo_id)
            except Exception as e:
                log.warning("todo.canvas_embedding_delete_failed", todo_id=todo_id, error=str(e))

        if not await todo_repository.delete(todo_id, user_id=user_id):
            raise ValueError(f"Todo {todo_id} not found")

        try:
            await delete_todo_embedding(todo_id)
        except Exception as e:
            log.warning("todo.index_remove_failed", todo_id=todo_id, error=str(e))

        schedule_user_todos_sync(user_id)
        capture_event(user_id, AnalyticsEvents.TODO_DELETED, {"todo_id": todo_id})

    # Bulk Operations
    @classmethod
    async def bulk_update_todos(
        cls, request: BulkUpdateRequest, user_id: str
    ) -> BulkOperationResponse:
        """Bulk update multiple todos."""
        update = _to_todo_update(request.updates)
        if not update.model_fields_set:
            return BulkOperationResponse(
                success=[], failed=[], total=len(request.todo_ids), message="No updates provided"
            )

        if update.project_id is not None:
            project = await project_repository.get(update.project_id, user_id=user_id)
            if not project:
                raise ValueError(f"Project {update.project_id} not found")

        modified = await todo_repository.bulk_update(user_id, request.todo_ids, update)

        if modified > 0:
            try:
                updated_todos = await todo_repository.find_by_ids(user_id, request.todo_ids)
                await asyncio.gather(
                    *(update_todo_embedding(t.id, t.model_dump(), user_id) for t in updated_todos),
                    return_exceptions=True,
                )
            except Exception as e:
                log.warning("todo.bulk_index_update_failed", error=str(e))
            schedule_user_todos_sync(user_id)

        return BulkOperationResponse(
            success=request.todo_ids[:modified],
            failed=[],
            total=len(request.todo_ids),
            message=f"Updated {modified} todos",
        )

    @classmethod
    async def bulk_delete_todos(cls, todo_ids: list[str], user_id: str) -> BulkOperationResponse:
        """Bulk delete multiple todos."""
        todos_to_delete = await todo_repository.find_by_ids(user_id, todo_ids)
        deleted = await todo_repository.bulk_delete(user_id, todo_ids)

        if deleted > 0:
            for todo in todos_to_delete:
                try:
                    await delete_todo_embedding(todo.id)
                except Exception as e:
                    log.warning("todo.index_remove_failed", todo_id=todo.id, error=str(e))
            schedule_user_todos_sync(user_id)
            capture_event(user_id, AnalyticsEvents.TODO_DELETED, {"count": deleted})

        return BulkOperationResponse(
            success=todo_ids[:deleted],
            failed=[],
            total=len(todo_ids),
            message=f"Deleted {deleted} todos",
        )

    @classmethod
    async def bulk_move_todos(cls, request: BulkMoveRequest, user_id: str) -> BulkOperationResponse:
        """Bulk move todos to another project."""
        project = await project_repository.get(request.project_id, user_id=user_id)
        if not project:
            raise ValueError(f"Project {request.project_id} not found")

        modified = await todo_repository.bulk_update(
            user_id, request.todo_ids, TodoUpdate(project_id=request.project_id)
        )
        if modified:
            schedule_user_todos_sync(user_id)

        return BulkOperationResponse(
            success=request.todo_ids if modified > 0 else [],
            failed=[],
            total=len(request.todo_ids),
            message=f"Moved {modified} todos",
        )

    # Search Operations
    @classmethod
    async def _search_todos(cls, user_id: str, params: TodoSearchParams) -> TodoListResponse:
        """Perform semantic or hybrid search."""
        if not params.q:
            return TodoListResponse(
                data=[],
                meta=PaginationMeta(
                    total=0,
                    page=params.page,
                    per_page=params.per_page,
                    pages=0,
                    has_next=False,
                    has_prev=False,
                ),
            )

        if params.mode == SearchMode.SEMANTIC:
            results = await vector_search(
                query=params.q,
                user_id=user_id,
                top_k=params.per_page * params.page,
                completed=params.completed,
                priority=params.priority.value if params.priority else None,
                project_id=params.project_id,
                include_traditional_search=False,
            )
        else:  # HYBRID
            results = await vector_hybrid_search(
                query=params.q,
                user_id=user_id,
                top_k=params.per_page * params.page,
                semantic_weight=0.7,
                completed=params.completed,
                priority=params.priority.value if params.priority else None,
                project_id=params.project_id,
            )

        total = len(results)
        start = (params.page - 1) * params.per_page
        paginated_results = results[start : start + params.per_page]
        pages = math.ceil(total / params.per_page)
        meta = PaginationMeta(
            total=total,
            page=params.page,
            per_page=params.per_page,
            pages=pages,
            has_next=params.page < pages,
            has_prev=params.page > 1,
        )
        response = TodoListResponse(data=paginated_results, meta=meta)
        if params.include_stats:
            response.stats = await cls._calculate_stats(user_id)
        return response


# Project Operations (kept separate as they're less complex)
class ProjectService:
    """Service for project operations."""

    @staticmethod
    async def create_project(project: ProjectCreate, user_id: str) -> ProjectResponse:
        """Create a new project."""
        log.set(
            component="todo_service",
            operation="create_project",
            user_id=user_id,
            project_name=project.name,
        )
        await project_repository.get_or_create_inbox(user_id)  # ensure inbox exists

        created = await project_repository.create(
            ProjectDocument(
                user_id=user_id,
                name=project.name,
                description=project.description,
                color=project.color,
                is_default=False,
            )
        )
        todo_count = await todo_repository.count_in_project(user_id, created.id)
        return ProjectResponse.from_document(created, todo_count=todo_count)

    @staticmethod
    async def list_projects(user_id: str) -> list[ProjectResponse]:
        """List all projects with todo counts."""
        await project_repository.get_or_create_inbox(user_id)  # ensure inbox exists
        projects = await project_repository.list_with_counts(user_id=user_id)
        return [ProjectResponse.from_document(project) for project in projects]

    @staticmethod
    async def update_project(
        project_id: str, updates: UpdateProjectRequest, user_id: str
    ) -> ProjectResponse:
        """Update a project."""
        log.set(
            component="todo_service",
            operation="update_project",
            user_id=user_id,
            project_id=project_id,
        )
        existing = await project_repository.get(project_id, user_id=user_id)
        if not existing:
            raise ValueError(f"Project {project_id} not found")
        if existing.is_default:
            raise ValueError("Cannot update default Inbox project")

        update_fields = {k: v for k, v in updates.model_dump().items() if v is not None}
        updated = await project_repository.update(
            project_id, user_id=user_id, update=ProjectUpdate(**update_fields)
        )
        if not updated:
            raise ValueError(f"Project {project_id} not found")

        todo_count = await todo_repository.count_in_project(user_id, project_id)
        return ProjectResponse.from_document(updated, todo_count=todo_count)

    @staticmethod
    async def delete_project(project_id: str, user_id: str) -> None:
        """Delete a project and move its todos to inbox."""
        log.set(
            component="todo_service",
            operation="delete_project",
            user_id=user_id,
            project_id=project_id,
        )
        project = await project_repository.get(project_id, user_id=user_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        if project.is_default:
            raise ValueError("Cannot delete default Inbox project")

        inbox_id = await project_repository.get_or_create_inbox(user_id)
        await todo_repository.move_todos_to_project(user_id, project_id, inbox_id.id)
        await project_repository.delete(project_id, user_id=user_id)


# Compatibility functions for old API
async def create_todo(todo: TodoModel, user_id: str) -> TodoResponse:
    """Compatibility wrapper for old create_todo function."""
    return await TodoService.create_todo(todo, user_id)


async def get_todo(todo_id: str, user_id: str) -> TodoResponse:
    """Compatibility wrapper for old get_todo function."""
    return await TodoService.get_todo(todo_id, user_id)


async def get_all_todos(
    user_id: str,
    project_id: str | None = None,
    completed: bool | None = None,
    priority: Priority | None = None,
    has_due_date: bool | None = None,
    overdue: bool | None = None,
    skip: int = 0,
    limit: int = 50,
) -> list[TodoResponse]:
    """Compatibility wrapper for old get_all_todos function."""

    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        project_id=project_id,
        completed=completed,
        priority=priority,
        has_due_date=has_due_date,
        overdue=overdue,
        page=(skip // limit) + 1 if limit > 0 else 1,
        per_page=limit,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def update_todo(todo_id: str, updates: TodoUpdateRequest, user_id: str) -> TodoResponse:
    """Compatibility wrapper for old update_todo function."""
    return await TodoService.update_todo(todo_id, updates, user_id)


async def delete_todo(todo_id: str, user_id: str) -> None:
    """Compatibility wrapper for old delete_todo function."""
    await TodoService.delete_todo(todo_id, user_id)


async def create_project(project: ProjectCreate, user_id: str) -> ProjectResponse:
    """Compatibility wrapper for old create_project function."""
    return await ProjectService.create_project(project, user_id)


async def get_all_projects(user_id: str) -> list[ProjectResponse]:
    """Compatibility wrapper for old get_all_projects function."""
    return await ProjectService.list_projects(user_id)


async def update_project(
    project_id: str, updates: UpdateProjectRequest, user_id: str
) -> ProjectResponse:
    """Compatibility wrapper for old update_project function."""
    return await ProjectService.update_project(project_id, updates, user_id)


async def delete_project(project_id: str, user_id: str) -> None:
    """Compatibility wrapper for old delete_project function."""
    await ProjectService.delete_project(project_id, user_id)


async def search_todos(
    query: str,
    user_id: str,
    completed: bool | None = None,
    priority: Priority | None = None,
    project_id: str | None = None,
) -> list[TodoResponse]:
    """Compatibility wrapper for old search_todos function."""
    params = TodoSearchParams(
        q=query,
        mode=SearchMode.TEXT,
        project_id=project_id,
        completed=completed,
        priority=priority,
        page=1,
        per_page=100,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


# Additional compatibility functions that might be used elsewhere
async def get_todo_stats(user_id: str) -> TodoStats:
    """Get statistics about user's todos."""
    return await TodoService._calculate_stats(user_id)


async def get_todos_by_date_range(
    user_id: str, start_date: datetime, end_date: datetime
) -> list[TodoResponse]:
    """Get todos within a date range."""
    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        due_date_start=start_date,
        due_date_end=end_date,
        completed=False,
        page=1,
        per_page=100,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def get_all_labels(user_id: str) -> list[TodoLabelCount]:
    """Get all unique labels used by the user with counts."""
    stats = await TodoService._calculate_stats(user_id)
    return stats.labels or []


async def get_todos_by_label(user_id: str, label: str) -> list[TodoResponse]:
    """Get all todos that have a specific label."""
    params = TodoSearchParams(
        q=None,
        mode=SearchMode.TEXT,
        labels=[label],
        page=1,
        per_page=100,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data


async def semantic_search_todos(
    query: str,
    user_id: str,
    limit: int = 20,
    project_id: str | None = None,
    completed: bool | None = None,
    priority: Priority | None = None,
) -> list[TodoResponse]:
    """Perform semantic search on todos."""
    params = TodoSearchParams(
        q=query,
        mode=SearchMode.SEMANTIC,
        project_id=project_id,
        completed=completed,
        priority=priority,
        page=1,
        per_page=limit,
        include_stats=False,
    )

    response = await TodoService.list_todos(user_id, params)
    return response.data
