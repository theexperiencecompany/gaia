import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NotRequired, TypeAlias, TypedDict
import uuid

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.constants.log_tags import LogTag
from app.constants.todos import (
    MAX_MISCOPIED_ID_CHARS,
    TODO_STATS_LABEL_LIMIT,
    TODO_SUMMARY_PREVIEW_LIMIT,
    TODO_UPCOMING_DAYS,
)
from app.db.repositories.todos import todo_repository
from app.decorators import with_doc, with_rate_limiting
from app.models.agent_models import current_stream_writer, get_user_id
from app.models.todo_card_models import (
    ProjectCounts,
    RecentlyCompletedBucket,
    SummaryStats,
    TodoBucket,
    TodoCardAction,
    TodoCardData,
    TodosSummary,
)
from app.models.todo_models import (
    Priority,
    ProjectCreate,
    ProjectResponse,
    SearchMode,
    SubTask,
    TodoDayWindow,
    TodoListResponse,
    TodoModel,
    TodoResponse,
    TodoSearchParams,
    TodoStats,
    TodoUpdateRequest,
    UpdateProjectRequest,
)
from app.models.tool_card_registry import tool_card
from app.services.todos.errors import TodoNotFoundError
from app.services.todos.todo_bulk_service import (
    bulk_complete_todos as bulk_complete_service,
    bulk_delete_todos as bulk_delete_service,
    bulk_move_todos as bulk_move_service,
)
from app.services.todos.todo_service import (
    TodoService,
    create_project as create_project_service,
    delete_project as delete_project_service,
    delete_todo as delete_todo_service,
    get_all_projects as get_all_projects_service,
    get_all_todos as get_all_todos_service,
    get_todo as get_todo_service,
    get_todos_by_date_range,
    get_todos_by_label as get_todos_by_label_service,
    project_completion,
    search_todos as search_todos_service,
    semantic_search_todos as semantic_search_todos_service,
    todo_responses,
    update_project as update_project_service,
    update_todo as update_todo_service,
    user_todo_counts,
)
from app.templates.docstrings.todo_tool_docs import (
    ADD_CHECKLIST_ITEM,
    BULK_COMPLETE_TODOS,
    BULK_DELETE_TODOS,
    BULK_MOVE_TODOS,
    CREATE_PROJECT,
    CREATE_TODO,
    DELETE_CHECKLIST_ITEM,
    DELETE_PROJECT,
    DELETE_TODO,
    GET_ALL_LABELS,
    GET_TODAY_TODOS,
    GET_TODO_STATS,
    GET_TODOS_BY_LABEL,
    GET_TODOS_SUMMARY,
    GET_UPCOMING_TODOS,
    LIST_PROJECTS,
    LIST_TODOS,
    SEARCH_TODOS,
    SEMANTIC_SEARCH_TODOS,
    UPDATE_CHECKLIST_ITEM,
    UPDATE_PROJECT,
    UPDATE_TODO,
)
from app.utils.log_identifiers import user_text_shape
from app.utils.timezone import home_timezone_from_config
from shared.py.wide_events import log

# A TodoResponse / ProjectResponse / TodoStats serialized with
# ``model_dump(mode="json")`` — an arbitrary JSON object by the time a tool
# hands it to the LLM and the stream writer.
SerializedModel: TypeAlias = dict[str, Any]


def _show(card: TodoCardData) -> None:
    """Stream the todo_data card to the chat."""
    current_stream_writer()(tool_card("todo_data", card))


# Tool return shapes are plain TypedDicts, not models: LangChain stringifies
# the value into the ToolMessage the LLM reads. ``count`` is ``NotRequired``
# because error paths return only the payload key plus ``error``.


class TodoResult(TypedDict):
    """A single-todo mutation result (create/update/checklist edits)."""

    todo: SerializedModel | None
    error: str | None


class TodoListResult(TypedDict):
    """A list of todos, with the match count on the success path."""

    todos: list[SerializedModel]
    count: NotRequired[int]
    error: str | None


class SemanticSearchResult(TodoListResult):
    """``semantic_search_todos`` — a todo list tagged with the search backend."""

    search_type: NotRequired[Literal["semantic"]]


class SuccessResult(TypedDict):
    """A delete/bulk-delete outcome carrying no entity."""

    success: bool
    error: str | None


class TodoStatsResult(TypedDict):
    """``get_todo_statistics`` — the serialized stats model."""

    stats: SerializedModel | None
    error: str | None


class ProjectResult(TypedDict):
    """A single-project mutation result."""

    project: SerializedModel | None
    error: str | None


class ProjectListResult(TypedDict):
    """A list of projects, with the match count on the success path."""

    projects: list[SerializedModel]
    count: NotRequired[int]
    error: str | None


class LabelListResult(TypedDict):
    """``get_all_labels`` — every label the user has, serialized."""

    labels: list[SerializedModel]
    error: str | None


class TodosSummaryResult(TypedDict):
    """``get_todos_summary`` — the whole snapshot in one call."""

    summary: SerializedModel | None
    error: str | None


def _day_window(config: RunnableConfig, upcoming_days: int = TODO_UPCOMING_DAYS) -> TodoDayWindow:
    """The run user's todo day, on their home timezone."""
    return TodoDayWindow.for_timezone(
        home_timezone_from_config(config), datetime.now(UTC), upcoming_days
    )


@tool
@with_rate_limiting("todo_operations")
@with_doc(CREATE_TODO)
async def create_todo(
    config: RunnableConfig,
    title: Annotated[str, "Title of the todo item (required)"],
    description: Annotated[str | None, "Detailed description of the todo"] = None,
    labels: Annotated[list[str] | None, "List of labels/tags for categorization"] = None,
    due_date: Annotated[datetime | None, "When the task should be completed"] = None,
    due_date_timezone: Annotated[
        str | None, "Timezone for the due date (e.g., 'America/New_York')"
    ] = None,
    priority: Annotated[Priority | None, "Priority level"] = None,
    project_id: Annotated[str | None, "Project ID to assign the todo to"] = None,
) -> TodoResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "create_todo", "action": "create"})
        log.info(f"{LogTag.TOOL} Todo Tool: Creating todo", title=title)

        priority_enum = priority or Priority.NONE

        todo_data = TodoModel(
            title=title,
            description=description,
            labels=labels or [],
            due_date=due_date,
            due_date_timezone=due_date_timezone,
            priority=priority_enum,
            project_id=project_id,
        )

        result = await TodoService.create_todo(todo_data, user_id)
        todo_dict = result.model_dump(mode="json")

        _show(
            TodoCardData(
                todos=[result], action=TodoCardAction.CREATE, message=f"Created task: {title}"
            )
        )

        return {"todo": todo_dict, "error": None}

    except Exception as e:
        error_msg = f"Error creating todo: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error creating todo",
            error_type=type(e).__name__,
            error=str(e),
            title=title,
        )
        return {"error": error_msg, "todo": None}


@tool
@with_doc(LIST_TODOS)
async def list_todos(
    config: RunnableConfig,
    project_id: Annotated[str | None, "Filter by specific project ID"] = None,
    completed: Annotated[bool | None, "Filter by completion status"] = None,
    priority: Annotated[Priority | None, "Filter by priority"] = None,
    has_due_date: Annotated[bool | None, "Filter todos with/without due dates"] = None,
    overdue: Annotated[bool | None, "Filter overdue uncompleted todos"] = None,
    skip: Annotated[int, "Number of records to skip for pagination"] = 0,
    limit: Annotated[int, "Maximum number of records to return"] = 50,
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "list_todos", "action": "list"})
        log.info(f"{LogTag.TOOL} Todo Tool: Listing todos with filters")

        # Ensure limit is reasonable
        limit = min(limit, 100)

        results = await get_all_todos_service(
            user_id,
            project_id=project_id,
            completed=completed,
            priority=priority,
            has_due_date=has_due_date,
            overdue=overdue,
            day_window=_day_window(config),
            skip=skip,
            limit=limit,
        )

        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the todo data to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.LIST,
                message=f"Found {len(results)} task{'s' if len(results) != 1 else ''}",
            )
        )

        return {"todos": todos_data, "count": len(results), "error": None}

    except Exception as e:
        error_msg = f"Error listing todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error listing todos",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "todos": []}


def _near_todos(todos: list[TodoResponse], todo_id: str) -> list[TodoResponse]:
    """Return the user's todos whose ids are within a few characters of todo_id, nearest first."""
    near: list[tuple[int, TodoResponse]] = []
    for todo in todos:
        if len(todo.id) != len(todo_id):
            continue
        diff = sum(
            a != b
            for a, b in zip(todo.id, todo_id, strict=True)  # pragma: no mutate — lengths match here
        )
        if diff <= MAX_MISCOPIED_ID_CHARS:
            near.append((diff, todo))
    return [todo for _, todo in sorted(near, key=lambda pair: pair[0])]


async def _unknown_todos_note(user_id: str, todo_ids: list[str]) -> str:
    """Say which ids matched no todo, and which real todo each was most likely meant to be.

    Todos created seconds apart have ObjectIds that differ in one or two hex
    characters, and a model copying them mixes the two up. A bare "not found"
    made it retry the same wrong id and tell the user the todo had vanished.
    """
    todos = await get_all_todos_service(user_id, limit=100)
    parts: list[str] = []
    for todo_id in todo_ids:
        # Every near id, never just the nearest: one miscopy is often equally
        # close to two real todos, and only the title tells which was meant.
        near = ", ".join(f'{t.id} ("{t.title}")' for t in _near_todos(todos, todo_id))
        hint = f" Closest real ids: {near}; pick by title." if near else ""
        parts.append(f"{todo_id} matches none of the user's todos.{hint}")
    return " ".join([*parts, "Copy todo ids exactly as list_todos returns them."])


@tool
@with_doc(UPDATE_TODO)
async def update_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the todo to update (required)"],
    title: Annotated[str | None, "New title for the todo"] = None,
    description: Annotated[str | None, "New description"] = None,
    labels: Annotated[list[str] | None, "New list of labels"] = None,
    due_date: Annotated[datetime | None, "New due date"] = None,
    due_date_timezone: Annotated[str | None, "New timezone for due date"] = None,
    priority: Annotated[Priority | None, "New priority"] = None,
    project_id: Annotated[str | None, "Move to different project"] = None,
    completed: Annotated[bool | None, "Mark as complete/incomplete"] = None,
) -> TodoResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "update_todo", "action": "update"})
        log.info(f"{LogTag.TOOL} Todo Tool: Updating todo", todo_id=todo_id)

        # Build update data with only provided fields
        update_request = TodoUpdateRequest(
            title=title,
            description=description,
            labels=labels,
            due_date=due_date,
            due_date_timezone=due_date_timezone,
            priority=priority,
            project_id=project_id,
            completed=completed,
        )
        result = await update_todo_service(todo_id, update_request, user_id)
        todo_dict = result.model_dump(mode="json")

        # Stream the updated todo to frontend
        _show(
            TodoCardData(
                todos=[result],
                action=TodoCardAction.UPDATE,
                message=f"Updated task: {result.title}",
            )
        )

        return {"todo": todo_dict, "error": None}

    except TodoNotFoundError as e:
        log.warning(f"{LogTag.TOOL} update_todo got an unknown todo id", todo_id=todo_id)
        return {"error": await _unknown_todos_note(user_id, [e.todo_id]), "todo": None}
    except Exception as e:
        error_msg = f"Error updating todo: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error updating todo",
            error_type=type(e).__name__,
            error=str(e),
            todo_id=todo_id,
        )
        return {"error": error_msg, "todo": None}


@tool
@with_doc(DELETE_TODO)
async def delete_todo(
    config: RunnableConfig,
    todo_id: Annotated[str, "ID of the todo to delete (required)"],
) -> SuccessResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "delete_todo", "action": "delete"})
        log.info(f"{LogTag.TOOL} Todo Tool: Deleting todo", todo_id=todo_id)

        # Get the todo first to show what was deleted
        todo = await get_todo_service(todo_id, user_id)
        todo_title = todo.title

        await delete_todo_service(todo_id, user_id)

        # Stream the deletion confirmation to frontend
        _show(TodoCardData(action=TodoCardAction.DELETE, message=f"Deleted task: {todo_title}"))

        return {"success": True, "error": None}

    except TodoNotFoundError as e:
        log.warning(f"{LogTag.TOOL} delete_todo got an unknown todo id", todo_id=todo_id)
        return {"error": await _unknown_todos_note(user_id, [e.todo_id]), "success": False}
    except Exception as e:
        error_msg = f"Error deleting todo: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error deleting todo",
            error_type=type(e).__name__,
            error=str(e),
            todo_id=todo_id,
        )
        return {"error": error_msg, "success": False}


@tool
@with_doc(SEARCH_TODOS)
async def search_todos(
    config: RunnableConfig,
    query: Annotated[str, "Search query to match against todos (required)"],
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "search_todos", "action": "search"})
        log.info(f"{LogTag.TOOL} Todo Tool: Searching todos", query=user_text_shape(query))

        results = await search_todos_service(query, user_id)
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the search results to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.SEARCH,
                message=f"Found {len(results)} task{'s' if len(results) != 1 else ''} matching '{query}'",
            )
        )

        return {"todos": todos_data, "count": len(results), "error": None}

    except Exception as e:
        error_msg = f"Error searching todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error searching todos",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(SEMANTIC_SEARCH_TODOS)
async def semantic_search_todos(
    config: RunnableConfig,
    query: Annotated[str, "Natural language search query (required)"],
    limit: Annotated[int, "Maximum number of results to return"] = 20,
    project_id: Annotated[str | None, "Filter by specific project ID"] = None,
    completed: Annotated[bool | None, "Filter by completion status"] = None,
    priority: Annotated[Priority | None, "Filter by priority"] = None,
) -> SemanticSearchResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "semantic_search_todos", "action": "search"})
        log.info(f"{LogTag.TOOL} Todo Tool: Semantic search", query=user_text_shape(query))

        # Ensure limit is reasonable
        limit = min(limit, 50)

        results = await semantic_search_todos_service(
            query=query,
            user_id=user_id,
            limit=limit,
            project_id=project_id,
            completed=completed,
            priority=priority,
        )

        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the semantic search results to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.SEARCH,
                message=f"Found {len(results)} task{'s' if len(results) != 1 else ''} using AI search for '{query}'",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "search_type": "semantic",
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error in semantic search: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error in semantic search",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(GET_TODO_STATS)
async def get_todo_statistics(config: RunnableConfig) -> TodoStatsResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_todo_statistics", "action": "stats"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting todo statistics")

        window = _day_window(config)
        stats, counts = await asyncio.gather(
            todo_repository.compute_stats(user_id=user_id, window=window),
            user_todo_counts(user_id, window),
        )
        _show(
            TodoCardData(
                stats=stats,
                counts=counts,
                action=TodoCardAction.STATS,
                message="Here's your task overview",
            )
        )

        return {"stats": stats.model_dump(mode="json"), "error": None}

    except Exception as e:
        error_msg = f"Error getting todo statistics: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting todo statistics",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "stats": None}


@tool
@with_doc(GET_TODAY_TODOS)
async def get_today_todos(config: RunnableConfig) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_today_todos", "action": "get"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting today's todos")

        results = await get_todos_by_date_range(user_id, *_day_window(config).today)
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream today's todos to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.LIST,
                message=f"Found {len(results)} task{'s' if len(results) != 1 else ''} due today",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error getting today's todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting today's todos",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(GET_UPCOMING_TODOS)
async def get_upcoming_todos(
    config: RunnableConfig,
    days: Annotated[int, "Number of days to look ahead"] = 7,
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_upcoming_todos", "action": "get"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting upcoming todos", days=days)

        results = await get_todos_by_date_range(user_id, *_day_window(config, days).upcoming)
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream upcoming todos to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.LIST,
                message=f"Found {len(results)} upcoming task{'s' if len(results) != 1 else ''} in the next {days} days",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error getting upcoming todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting upcoming todos",
            error_type=type(e).__name__,
            error=str(e),
            days=days,
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(CREATE_PROJECT)
async def create_project(
    config: RunnableConfig,
    name: Annotated[str, "Name of the project (required)"],
    description: Annotated[str | None, "Project description"] = None,
    color: Annotated[str | None, "Hex color code (e.g., #FF5733)"] = None,
) -> ProjectResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "create_project", "action": "create"})
        log.info(f"{LogTag.TOOL} Todo Tool: Creating project", project_name=name)

        project_data = ProjectCreate(
            name=name,
            description=description,
            color=color,
        )

        result = await create_project_service(project_data, user_id)
        project_dict = result.model_dump(mode="json")

        # Stream the created project to frontend
        _show(
            TodoCardData(
                projects=[result], action=TodoCardAction.CREATE, message=f"Created project: {name}"
            )
        )

        return {"project": project_dict, "error": None}

    except Exception as e:
        error_msg = f"Error creating project: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error creating project",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "project": None}


@tool
@with_doc(LIST_PROJECTS)
async def list_projects(config: RunnableConfig) -> ProjectListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "list_projects", "action": "list"})
        log.info(f"{LogTag.TOOL} Todo Tool: Listing all projects")

        results, stats = await asyncio.gather(
            get_all_projects_service(user_id),
            todo_repository.compute_stats(user_id=user_id, window=_day_window(config)),
        )
        projects_data = [project.model_dump(mode="json") for project in results]

        _show(
            TodoCardData(
                projects=results,
                project_completion=project_completion(stats),
                action=TodoCardAction.LIST,
                message=f"You have {len(results)} project{'s' if len(results) != 1 else ''}",
            )
        )

        return {"projects": projects_data, "count": len(results), "error": None}

    except Exception as e:
        error_msg = f"Error listing projects: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error listing projects",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "projects": []}


@tool
@with_doc(UPDATE_PROJECT)
async def update_project(
    config: RunnableConfig,
    project_id: Annotated[str, "ID of the project to update (required)"],
    name: Annotated[str | None, "New project name"] = None,
    description: Annotated[str | None, "New project description"] = None,
    color: Annotated[str | None, "New hex color code"] = None,
) -> ProjectResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "update_project", "action": "update"})
        log.info(f"{LogTag.TOOL} Todo Tool: Updating project", project_id=project_id)

        update_request = UpdateProjectRequest(name=name, description=description, color=color)
        result = await update_project_service(project_id, update_request, user_id)
        project_dict = result.model_dump(mode="json")

        # Stream the updated project to frontend
        _show(
            TodoCardData(
                projects=[result],
                action=TodoCardAction.UPDATE,
                message=f"Updated project: {result.name}",
            )
        )

        return {"project": project_dict, "error": None}

    except Exception as e:
        error_msg = f"Error updating project: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error updating project",
            error_type=type(e).__name__,
            error=str(e),
            project_id=project_id,
        )
        return {"error": error_msg, "project": None}


@tool
@with_doc(DELETE_PROJECT)
async def delete_project(
    config: RunnableConfig,
    project_id: Annotated[str, "ID of the project to delete (required)"],
) -> SuccessResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "delete_project", "action": "delete"})
        log.info(f"{LogTag.TOOL} Todo Tool: Deleting project", project_id=project_id)

        # Get all projects and find the one being deleted
        all_projects = await get_all_projects_service(user_id)
        project = next((p for p in all_projects if p.id == project_id), None)
        project_name = project.name if project else "Unknown Project"

        await delete_project_service(project_id, user_id)

        # Stream the deletion confirmation to frontend
        _show(
            TodoCardData(action=TodoCardAction.DELETE, message=f"Deleted project: {project_name}")
        )

        return {"success": True, "error": None}

    except Exception as e:
        error_msg = f"Error deleting project: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error deleting project",
            error_type=type(e).__name__,
            error=str(e),
            project_id=project_id,
        )
        return {"error": error_msg, "success": False}


@tool
@with_doc(GET_TODOS_BY_LABEL)
async def get_todos_by_label(
    config: RunnableConfig,
    label: Annotated[str, "The label to filter by (required)"],
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_todos_by_label", "action": "get"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting todos by label", label=label)

        results = await get_todos_by_label_service(user_id, label)
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the labeled todos to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.LIST,
                message=f"Found {len(results)} task{'s' if len(results) != 1 else ''} with label '{label}'",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error getting todos by label: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting todos by label",
            error_type=type(e).__name__,
            error=str(e),
            label=label,
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(GET_ALL_LABELS)
async def get_all_labels(config: RunnableConfig) -> LabelListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_all_labels", "action": "get"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting all labels")

        results = await todo_repository.top_labels(user_id=user_id, limit=TODO_STATS_LABEL_LIMIT)
        return {"labels": [label.model_dump() for label in results], "error": None}

    except Exception as e:
        error_msg = f"Error getting labels: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting labels",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "labels": []}


@tool
@with_doc(BULK_COMPLETE_TODOS)
async def bulk_complete_todos(
    config: RunnableConfig,
    todo_ids: Annotated[list[str], "List of todo IDs to mark as complete (required)"],
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "bulk_complete_todos", "action": "bulk_complete"})
        log.info(f"{LogTag.TOOL} Todo Tool: Bulk completing todos", todo_count=len(todo_ids))

        completion = await bulk_complete_service(todo_ids, user_id)
        results = completion.todos
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the bulk completed todos to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.UPDATE,
                message=f"Completed {len(results)} task{'s' if len(results) != 1 else ''}",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "error": (
                f"Not completed, still open: {', '.join(completion.failed)}"
                if completion.failed
                else None
            ),
        }

    except Exception as e:
        error_msg = f"Error bulk completing todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error bulk completing todos",
            error_type=type(e).__name__,
            error=str(e),
            todo_count=len(todo_ids),
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(BULK_MOVE_TODOS)
async def bulk_move_todos(
    config: RunnableConfig,
    todo_ids: Annotated[list[str], "List of todo IDs to move (required)"],
    project_id: Annotated[str, "Target project ID (required)"],
) -> TodoListResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "bulk_move_todos", "action": "bulk_move"})
        log.info(
            f"{LogTag.TOOL} Todo Tool: Bulk moving todos",
            todo_count=len(todo_ids),
            project_id=project_id,
        )

        results = await bulk_move_service(todo_ids, project_id, user_id)
        todos_data = [todo.model_dump(mode="json") for todo in results]

        # Stream the bulk moved todos to frontend
        _show(
            TodoCardData(
                todos=results,
                action=TodoCardAction.UPDATE,
                message=f"Moved {len(results)} task{'s' if len(results) != 1 else ''} to project",
            )
        )

        return {
            "todos": todos_data,
            "count": len(results),
            "error": None,
        }

    except Exception as e:
        error_msg = f"Error bulk moving todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error bulk moving todos",
            error_type=type(e).__name__,
            error=str(e),
            todo_count=len(todo_ids),
            project_id=project_id,
        )
        return {"error": error_msg, "todos": []}


@tool
@with_doc(BULK_DELETE_TODOS)
async def bulk_delete_todos(
    config: RunnableConfig,
    todo_ids: Annotated[list[str], "List of todo IDs to delete (required)"],
) -> SuccessResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "bulk_delete_todos", "action": "bulk_delete"})
        log.info(f"{LogTag.TOOL} Todo Tool: Bulk deleting todos", todo_count=len(todo_ids))

        result = await bulk_delete_service(todo_ids, user_id)
        deleted = len(result.success)

        # Stream the bulk deletion confirmation to frontend
        _show(
            TodoCardData(
                action=TodoCardAction.DELETE,
                message=f"Deleted {deleted} task{'s' if deleted != 1 else ''}",
            )
        )

        if result.failed:
            log.warning(
                f"{LogTag.TOOL} bulk_delete_todos got unknown todo ids",
                todo_count=len(todo_ids),
                unknown_count=len(result.failed),
            )
            note = await _unknown_todos_note(user_id, result.failed)
            return {"success": False, "error": f"Deleted {deleted} of {len(todo_ids)}. {note}"}
        return {"success": True, "error": None}

    except Exception as e:
        error_msg = f"Error bulk deleting todos: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error bulk deleting todos",
            error_type=type(e).__name__,
            error=str(e),
            todo_count=len(todo_ids),
        )
        return {"error": error_msg, "success": False}


@tool
@with_doc(ADD_CHECKLIST_ITEM)
async def add_checklist_item(
    config: RunnableConfig,
    todo_id: Annotated[str, "Parent todo ID (required)"],
    title: Annotated[str, "Checklist item title (required)"],
) -> TodoResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "add_checklist_item", "action": "create"})
        log.info(f"{LogTag.TOOL} Todo Tool: Adding checklist item", todo_id=todo_id)

        todo = await get_todo_service(todo_id, user_id)

        new_subtask = SubTask(id=str(uuid.uuid4()), title=title, completed=False)

        update_data = TodoUpdateRequest(subtasks=todo.subtasks + [new_subtask])

        result = await update_todo_service(todo_id, update_data, user_id)
        todo_dict = result.model_dump(mode="json")

        # Stream the updated todo with its new checklist item to the frontend
        _show(
            TodoCardData(
                todos=[result],
                action=TodoCardAction.UPDATE,
                message=f"Added checklist item '{title}' to {result.title}",
            )
        )

        return {"todo": todo_dict, "error": None}

    except Exception as e:
        error_msg = f"Error adding checklist item: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error adding checklist item",
            error_type=type(e).__name__,
            error=str(e),
            todo_id=todo_id,
        )
        return {"error": error_msg, "todo": None}


@tool
@with_doc(UPDATE_CHECKLIST_ITEM)
async def update_checklist_item(
    config: RunnableConfig,
    todo_id: Annotated[str, "Parent todo ID (required)"],
    item_id: Annotated[str, "Checklist item ID to update (required)"],
    title: Annotated[str | None, "New checklist item title"] = None,
    completed: Annotated[bool | None, "Checklist item completion status"] = None,
) -> TodoResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "update_checklist_item", "action": "update"})
        log.info(
            f"{LogTag.TOOL} Todo Tool: Updating checklist item", item_id=item_id, todo_id=todo_id
        )

        # Get the todo first
        todo = await get_todo_service(todo_id, user_id)

        # Find and update the subtask
        updated_subtasks = []
        subtask_found = False
        for subtask in todo.subtasks:
            if subtask.id == item_id:
                subtask_found = True
                if title is not None:
                    subtask.title = title
                if completed is not None:
                    subtask.completed = completed
            updated_subtasks.append(subtask)

        if not subtask_found:
            return {"error": f"Checklist item {item_id} not found", "todo": None}

        # Update todo with modified subtasks
        update_data = TodoUpdateRequest(subtasks=updated_subtasks)
        result = await update_todo_service(todo_id, update_data, user_id)
        todo_dict = result.model_dump(mode="json")

        # Stream the updated todo with its edited checklist item to the frontend
        _show(
            TodoCardData(
                todos=[result],
                action=TodoCardAction.UPDATE,
                message=f"Updated checklist item in {result.title}",
            )
        )

        return {"todo": todo_dict, "error": None}

    except Exception as e:
        error_msg = f"Error updating checklist item: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error updating checklist item",
            error_type=type(e).__name__,
            error=str(e),
            todo_id=todo_id,
            item_id=item_id,
        )
        return {"error": error_msg, "todo": None}


@tool
@with_doc(DELETE_CHECKLIST_ITEM)
async def delete_checklist_item(
    config: RunnableConfig,
    todo_id: Annotated[str, "Parent todo ID (required)"],
    item_id: Annotated[str, "Checklist item ID to delete (required)"],
) -> TodoResult:
    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "delete_checklist_item", "action": "delete"})
        log.info(
            f"{LogTag.TOOL} Todo Tool: Deleting checklist item", item_id=item_id, todo_id=todo_id
        )

        # Get the todo first
        todo = await get_todo_service(todo_id, user_id)

        # Remove the subtask
        updated_subtasks = [s for s in todo.subtasks if s.id != item_id]

        if len(updated_subtasks) == len(todo.subtasks):
            return {"error": f"Checklist item {item_id} not found", "todo": None}

        # Update todo with remaining subtasks
        update_data = TodoUpdateRequest(subtasks=updated_subtasks)
        result = await update_todo_service(todo_id, update_data, user_id)
        todo_dict = result.model_dump(mode="json")

        # Stream the updated todo without the removed checklist item to the frontend
        _show(
            TodoCardData(
                todos=[result],
                action=TodoCardAction.UPDATE,
                message=f"Removed checklist item from {result.title}",
            )
        )

        return {"todo": todo_dict, "error": None}

    except Exception as e:
        error_msg = f"Error deleting checklist item: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error deleting checklist item",
            error_type=type(e).__name__,
            error=str(e),
            todo_id=todo_id,
            item_id=item_id,
        )
        return {"error": error_msg, "todo": None}


def _preview(window: TodoDayWindow, *, completed: bool) -> TodoSearchParams:
    """A summary preview page of the user's open or completed todos, before its bucket filter."""
    return TodoSearchParams(
        mode=SearchMode.TEXT,
        per_page=TODO_SUMMARY_PREVIEW_LIMIT,
        completed=completed,
        day_window=window,
    )


def _bucket(page: TodoListResponse) -> TodoBucket:
    """A preview of one bucket, with the count over all of its todos."""
    return TodoBucket(
        count=page.meta.total, todos=page.data, has_more=page.meta.total > len(page.data)
    )


def _project_breakdown(
    stats: TodoStats, projects: list[ProjectResponse]
) -> dict[str, ProjectCounts]:
    """Per-project totals from the stats over every todo, keyed by project name."""
    breakdown: dict[str, ProjectCounts] = {}
    for project in projects:
        total = stats.by_project.get(project.id, 0)
        pending = stats.pending_by_project.get(project.id, 0)
        breakdown[project.name] = ProjectCounts(
            total=total, completed=total - pending, pending=pending
        )
    return breakdown


@tool
@with_doc(GET_TODOS_SUMMARY)
async def get_todos_summary(config: RunnableConfig) -> TodosSummaryResult:
    """Get a comprehensive summary of the user's todos in a single call."""

    user_id = get_user_id(config)

    try:
        log.set(tool={"name": "get_todos_summary", "action": "summary"})
        log.info(f"{LogTag.TOOL} Todo Tool: Getting comprehensive todos summary")

        window = _day_window(config)
        open_todos = _preview(window, completed=False)
        today, overdue, upcoming, high_priority, completed_today = await asyncio.gather(
            TodoService.list_todos(
                user_id,
                open_todos.model_copy(
                    update={"due_date_start": window.today.start, "due_date_end": window.today.end}
                ),
            ),
            TodoService.list_todos(user_id, open_todos.model_copy(update={"overdue": True})),
            TodoService.list_todos(
                user_id,
                open_todos.model_copy(
                    update={
                        "due_date_start": window.upcoming.start,
                        "due_date_end": window.upcoming.end,
                    }
                ),
            ),
            TodoService.list_todos(
                user_id, open_todos.model_copy(update={"priority": Priority.HIGH})
            ),
            TodoService.list_todos(
                user_id,
                _preview(window, completed=True).model_copy(
                    update={"completed_after": window.today_start}
                ),
            ),
        )
        stats, projects, next_due = await asyncio.gather(
            todo_repository.compute_stats(user_id=user_id, window=window),
            get_all_projects_service(user_id),
            todo_repository.next_due(user_id, after=datetime.now(UTC)),
        )
        next_deadline = (await todo_responses(user_id, [next_due]))[0] if next_due else None

        summary = TodosSummary(
            today=_bucket(today),
            overdue=_bucket(overdue),
            upcoming_week=_bucket(upcoming),
            high_priority=_bucket(high_priority),
            recently_completed=RecentlyCompletedBucket(
                count=completed_today.meta.total, todos=completed_today.data
            ),
            next_deadline=next_deadline,
            stats=SummaryStats(
                total=stats.total,
                completed=stats.completed,
                pending=stats.pending,
                completed_today=completed_today.meta.total,
                overdue=stats.overdue,
                completion_rate=stats.completion_rate,
            ),
            by_project=_project_breakdown(stats, projects),
        )

        _show(
            TodoCardData(
                summary=summary,
                action=TodoCardAction.SUMMARY,
                message=f"Here's your productivity snapshot: {today.meta.total} tasks today, {stats.overdue} overdue, {stats.completion_rate}% completion rate",
            )
        )

        return {"summary": summary.model_dump(mode="json"), "error": None}

    except Exception as e:
        error_msg = f"Error getting todos summary: {e!s}"
        log.error(
            f"{LogTag.TOOL} Error getting todos summary",
            error_type=type(e).__name__,
            error=str(e),
        )
        return {"error": error_msg, "summary": None}


# Export all todo tools as a list for easy registration
tools = [
    create_todo,
    list_todos,
    update_todo,
    delete_todo,
    search_todos,
    semantic_search_todos,
    get_todo_statistics,
    get_today_todos,
    get_upcoming_todos,
    create_project,
    list_projects,
    update_project,
    delete_project,
    get_todos_by_label,
    get_all_labels,
    bulk_complete_todos,
    bulk_move_todos,
    bulk_delete_todos,
    add_checklist_item,
    update_checklist_item,
    delete_checklist_item,
    get_todos_summary,
]
