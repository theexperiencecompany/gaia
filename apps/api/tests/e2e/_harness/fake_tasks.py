"""In-memory stand-in for the task repository calls agent-lab runs make.

Implements only what the run path touches: the bash tool's lookup, the run
subscription's append and its removal, and the receiver's listening-tasks query
(open tasks with a subscription on one of the trigger names, like the real query).
"""

from __future__ import annotations

from collections.abc import Collection

from app.models.task_models import TaskDocument
from app.models.trigger_subscription_models import TriggerSubscription


class InMemoryTasks:
    """Tasks by id; subscription writes land on the documents the tests hold."""

    def __init__(self, *tasks: TaskDocument) -> None:
        self._by_id = {task.id: task for task in tasks}

    async def get(self, task_id: str, *, user_id: str) -> TaskDocument | None:
        task = self._by_id.get(task_id)
        return task if task is not None and task.user_id == user_id else None

    async def add_subscription(
        self, task_id: str, *, user_id: str, subscription: TriggerSubscription
    ) -> TaskDocument | None:
        task = await self.get(task_id, user_id=user_id)
        if task is None:
            return None
        task.subscriptions = [*task.subscriptions, subscription]
        return task

    async def remove_subscriptions(
        self, task_id: str, *, user_id: str, subscription_ids: Collection[str]
    ) -> TaskDocument | None:
        task = await self.get(task_id, user_id=user_id)
        if task is None or all(s.id not in subscription_ids for s in task.subscriptions):
            return None
        before = task.model_copy()
        task.subscriptions = [s for s in task.subscriptions if s.id not in subscription_ids]
        return before

    async def find_listening_by_user_and_trigger(
        self, user_id: str, trigger_names: Collection[str]
    ) -> list[TaskDocument]:
        return [
            task
            for task in self._by_id.values()
            if task.user_id == user_id
            and not task.completed
            and (task.active or task.pause_reason is not None)
            and any(s.trigger_name in trigger_names for s in task.subscriptions)
        ]


def with_watch(task: TaskDocument, subscription: TriggerSubscription) -> TaskDocument:
    """Return the task as the repository's append leaves it when no identical watch is on it."""
    return task.model_copy(update={"subscriptions": [*task.subscriptions, subscription]})
