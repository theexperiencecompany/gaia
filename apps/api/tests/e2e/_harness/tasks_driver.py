"""The user's actions on tasks, implemented on today's /todos and /workflows system.

Journeys speak only through this driver and tasks_views, so the same journey
files can later run against /tasks by swapping this module's implementation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from httpx import AsyncClient, Response

from tests.e2e._harness.tasks_views import Counts, Subtask, TaskNotFoundError, TaskView

TODOS = "/api/v1/todos"


def _ok(response: Response) -> dict[str, Any]:
    if response.status_code == 404:
        raise TaskNotFoundError(response.text)
    assert response.is_success, (
        f"{response.request.method} {response.request.url}: {response.status_code} {response.text}"
    )
    return response.json()


def _task_view(body: dict[str, Any]) -> TaskView:
    return TaskView(
        id=body["id"],
        title=body["title"],
        done=body["completed"],
        due=datetime.fromisoformat(body["due_date"]) if body.get("due_date") else None,
        subtasks=tuple(
            Subtask(id=s["id"], title=s["title"], done=s["completed"]) for s in body["subtasks"]
        ),
        parent_id=body.get("parent_todo_id"),
        open_children=body.get("sub_todo_count", 0),
        pending_approval=body.get("pending_approval") is not None,
    )


class TasksDriver:
    """A signed-in user's hands on their tasks, and their eyes on what came of them."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    # To-dos the user does themselves.

    async def create_todo(self, title: str, *, due: datetime | None = None) -> TaskView:
        payload: dict[str, Any] = {"title": title}
        if due is not None:
            payload["due_date"] = due.isoformat()
        return _task_view(_ok(await self._client.post(TODOS, json=payload)))

    async def edit(
        self, task_id: str, *, title: str | None = None, due: datetime | None = None
    ) -> TaskView:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if due is not None:
            payload["due_date"] = due.isoformat()
        return _task_view(_ok(await self._client.put(f"{TODOS}/{task_id}", json=payload)))

    async def complete(self, task_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.put(f"{TODOS}/{task_id}", json={"completed": True}))
        )

    async def reopen(self, task_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.put(f"{TODOS}/{task_id}", json={"completed": False}))
        )

    async def delete(self, task_id: str) -> None:
        response = await self._client.delete(f"{TODOS}/{task_id}")
        assert response.status_code == 204, response.text

    async def add_subtask(self, task_id: str, title: str) -> TaskView:
        return _task_view(
            _ok(await self._client.post(f"{TODOS}/{task_id}/subtasks", json={"title": title}))
        )

    async def rename_subtask(self, task_id: str, subtask_id: str, title: str) -> TaskView:
        return _task_view(
            _ok(
                await self._client.put(
                    f"{TODOS}/{task_id}/subtasks/{subtask_id}", json={"title": title}
                )
            )
        )

    async def tick_subtask(self, task_id: str, subtask_id: str) -> TaskView:
        return _task_view(
            _ok(await self._client.post(f"{TODOS}/{task_id}/subtasks/{subtask_id}/toggle"))
        )

    # What the user sees.

    async def get(self, task_id: str) -> TaskView | None:
        response = await self._client.get(f"{TODOS}/{task_id}")
        if response.status_code == 404:
            return None
        return _task_view(_ok(response))

    async def open_list(self) -> list[TaskView]:
        """Return the open tasks list, in the order the list API returns it."""
        return await self._list(completed="false")

    async def overdue(self) -> list[TaskView]:
        return await self._list(overdue="true")

    async def completed_list(self) -> list[TaskView]:
        return await self._list(completed="true")

    async def counts(self) -> Counts:
        body = _ok(await self._client.get(f"{TODOS}/counts"))
        return Counts(today=body["today"], overdue=body["overdue"], completed=body["completed"])

    async def _list(self, **params: str) -> list[TaskView]:
        body = _ok(await self._client.get(TODOS, params=params))
        return [_task_view(item) for item in body["data"]]
