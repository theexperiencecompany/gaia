"""The todo_data card's payload: what a todo tool shows the user in the chat."""

from enum import StrEnum

from app.models.todo_models import ProjectResponse, TodoCounts, TodoResponse, TodoStats
from app.schemas.common import ResponseModel


class TodoCardAction(StrEnum):
    """What the todo tool did, which picks the card's heading."""

    CREATE = "create"
    LIST = "list"
    UPDATE = "update"
    DELETE = "delete"
    SEARCH = "search"
    STATS = "stats"
    SUMMARY = "summary"


class TodoBucket(ResponseModel):
    """One bucket of the summary: its count over every todo, and a capped preview."""

    count: int
    todos: list[TodoResponse]
    has_more: bool


class RecentlyCompletedBucket(ResponseModel):
    """The todos completed today; the summary card never offers to expand it."""

    count: int
    todos: list[TodoResponse]


class SummaryStats(ResponseModel):
    """The summary's productivity counters."""

    total: int
    completed: int
    pending: int
    completed_today: int
    overdue: int
    completion_rate: float


class ProjectCounts(ResponseModel):
    """One project's task tallies in the summary."""

    total: int
    completed: int
    pending: int


class TodosSummary(ResponseModel):
    """The get_todos_summary snapshot; by_project is keyed by project name."""

    today: TodoBucket
    overdue: TodoBucket
    upcoming_week: TodoBucket
    high_priority: TodoBucket
    recently_completed: RecentlyCompletedBucket
    next_deadline: TodoResponse | None
    stats: SummaryStats
    by_project: dict[str, ProjectCounts]


class TodoCardData(ResponseModel):
    """The todo_data card; counts ride with stats, project_completion (percent by project id) with projects."""

    action: TodoCardAction
    message: str
    todos: list[TodoResponse] | None = None
    projects: list[ProjectResponse] | None = None
    project_completion: dict[str, int] | None = None
    stats: TodoStats | None = None
    counts: TodoCounts | None = None
    summary: TodosSummary | None = None
