"""In-memory stand-in for the todo repository calls agent-lab runs and watch gating make.

Implements only what those paths touch: the bash tool's lookup, the run
subscription's append and its removal, the receiver's open-todos-by-trigger
query (incomplete todos with an ACTIVE subscription on that trigger, like the
real query), and the open-todos-by-ref read and gate write the desk gate uses.
"""

from __future__ import annotations

from collections.abc import Collection

from app.models.todo_models import ExternalRef, TodoDocument
from app.models.trigger_gate_models import AuthoredGate, SystemGate
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

    async def list_open_by_external_ref_all_users(self, ref: ExternalRef) -> list[TodoDocument]:
        return [t for t in self._by_id.values() if not t.completed and t.external_ref == ref]

    async def gate_ungated_subscriptions(
        self,
        todo_id: str,
        *,
        user_id: str,
        subscription_ids: Collection[str],
        gate: AuthoredGate | SystemGate,
    ) -> TodoDocument | None:
        todo = await self.get(todo_id, user_id=user_id)
        if todo is None:
            return None
        due = {
            s.id for s in todo.trigger_subscriptions if s.id in subscription_ids and s.gate is None
        }
        if not due:
            return None
        todo.trigger_subscriptions = [
            s.model_copy(update={"gate": gate}) if s.id in due else s
            for s in todo.trigger_subscriptions
        ]
        return todo


def with_watch(todo: TodoDocument, subscription: TriggerSubscription) -> TodoDocument:
    """Return the todo as the repository's append leaves it when no identical watch is on it."""
    return todo.model_copy(
        update={"trigger_subscriptions": [*todo.trigger_subscriptions, subscription]}
    )
