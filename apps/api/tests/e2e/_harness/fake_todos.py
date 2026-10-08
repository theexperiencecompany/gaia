"""In-memory stand-in for the todo repository calls agent-lab runs make.

Implements only what the run path touches: the bash tool's lookup, the run
subscription write, and the receiver's open-todos-by-trigger query (incomplete
todos with an ACTIVE subscription on that trigger, like the real query).
"""

from __future__ import annotations

from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import TriggerSubscriptionStatus


class InMemoryTodos:
    """Todos by id; subscription writes land on the documents the tests hold."""

    def __init__(self, *todos: TodoDocument) -> None:
        self._by_id = {todo.id: todo for todo in todos}

    async def get(self, todo_id: str, *, user_id: str | None = None) -> TodoDocument | None:
        todo = self._by_id.get(todo_id)
        return todo if todo is not None and user_id in (None, todo.user_id) else None

    async def update(
        self, todo_id: str, *, user_id: str, update: TodoUpdate
    ) -> TodoDocument | None:
        todo = await self.get(todo_id, user_id=user_id)
        if todo is None:
            return None
        if update.trigger_subscriptions is not None:
            todo.trigger_subscriptions = list(update.trigger_subscriptions)
        return todo

    async def find_active_by_user_and_trigger(
        self, user_id: str, trigger_name: str
    ) -> list[TodoDocument]:
        return [
            todo
            for todo in self._by_id.values()
            if todo.user_id == user_id
            and not todo.completed
            and any(
                s.trigger_name == trigger_name and s.status is TriggerSubscriptionStatus.ACTIVE
                for s in todo.trigger_subscriptions
            )
        ]
