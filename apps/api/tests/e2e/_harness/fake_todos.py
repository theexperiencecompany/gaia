"""In-memory stand-in for the todo repository calls agent-lab runs make.

Implements only what the run path touches: the bash tool's lookup, the run
subscription's append and its removal, and the receiver's open-todos-by-trigger
query (incomplete todos with an ACTIVE subscription on that trigger, like the
real query).
"""

from __future__ import annotations

from collections.abc import Collection

from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    TriggerSubscription,
    TriggerSubscriptionStatus,
)


class InMemoryTodos:
    """Todos by id; subscription writes land on the documents the tests hold."""

    def __init__(self, *todos: TodoDocument) -> None:
        self._by_id = {todo.id: todo for todo in todos}

    async def get(self, todo_id: str, *, user_id: str | None = None) -> TodoDocument | None:
        todo = self._by_id.get(todo_id)
        return todo if todo is not None and user_id in (None, todo.user_id) else None

    async def add_trigger_subscription(
        self, todo_id: str, *, user_id: str, subscription: TriggerSubscription
    ) -> TodoDocument | None:
        todo = await self.get(todo_id, user_id=user_id)
        if todo is None:
            return None
        todo.trigger_subscriptions = [*todo.trigger_subscriptions, subscription]
        return todo

    async def remove_trigger_subscriptions(
        self, todo_id: str, *, user_id: str, subscription_ids: Collection[str]
    ) -> TodoDocument | None:
        todo = await self.get(todo_id, user_id=user_id)
        if todo is None or all(s.id not in subscription_ids for s in todo.trigger_subscriptions):
            return None
        before = todo.model_copy()
        todo.trigger_subscriptions = [
            s for s in todo.trigger_subscriptions if s.id not in subscription_ids
        ]
        return before

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


def with_watch(todo: TodoDocument, subscription: TriggerSubscription) -> TodoDocument:
    """Return the todo as the repository's append leaves it when no identical watch is on it."""
    return todo.model_copy(
        update={"trigger_subscriptions": [*todo.trigger_subscriptions, subscription]}
    )
