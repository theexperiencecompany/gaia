"""Per-run identity for agent-lab runs: workdir layout plus the todo's run subscription.

A run is owned by the tracked todo that launched it through one trigger
subscription: every event the run reports fires that subscription, which runs
the todo with the event attached. Composio ids stay empty, so the ordinary
subscription teardown ends the run's watch without touching anything upstream.
"""

from typing import Final

from app.constants.todos import TodoActivityEvent
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.agent_lab.agents_home import AGENTS_RUNS_DIR
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.todo_activity import record_activity
from app.utils.errors import AppError

#: Trigger name of a todo's subscription to one of its sandbox runs.
SANDBOX_RUN_TRIGGER: Final[str] = "sandbox_run"

#: Key in the subscription's trigger_data naming the run it watches.
RUN_ID_KEY: Final[str] = "run_id"

#: Seed runs CLI installs, so allow time for a cold download.
LAB_SEED_TIMEOUT_SECONDS: Final[int] = 300


def run_dir(run_id: str) -> str:
    """Return the run's folder (its env file) under the agents' home."""
    return f"{AGENTS_RUNS_DIR}/{run_id}"


def run_subscriptions(todo: TodoDocument) -> list[TriggerSubscription]:
    """Return the todo's subscriptions to its sandbox runs."""
    return [s for s in todo.trigger_subscriptions if s.trigger_name == SANDBOX_RUN_TRIGGER]


def run_id_of(subscription: TriggerSubscription) -> str:
    """Return the run a sandbox-run subscription watches."""
    return str(subscription.trigger_data[RUN_ID_KEY])


def find_run(
    todos: list[TodoDocument], run_id: str
) -> tuple[TodoDocument, TriggerSubscription] | None:
    """Return the todo subscribed to run_id with that subscription, if any todo is."""
    for todo in todos:
        for subscription in run_subscriptions(todo):
            if run_id_of(subscription) == run_id:
                return todo, subscription
    return None


async def subscribe_todo_to_run(todo: TodoDocument, run_id: str) -> TriggerSubscription:
    """Attach the run's subscription to the todo; cooldown 0 so no event is ever suppressed."""
    subscription = TriggerSubscription(
        trigger_name=SANDBOX_RUN_TRIGGER,
        action=SubscriptionAction.EXECUTE,
        cooldown_seconds=0,
        resolution=SubscriptionResolution.ACCOUNT,
        trigger_data={RUN_ID_KEY: run_id},
    )
    updated = await todo_repository.update(
        todo.id,
        user_id=todo.user_id,
        update=TodoUpdate(trigger_subscriptions=[*todo.trigger_subscriptions, subscription]),
    )
    if updated is None:
        raise AppError(
            message="the todo vanished while subscribing it to its run",
            why=f"todo {todo.id} is gone after it was resolved",
            fix="create the tracked todo again, then relaunch the run",
            status_code=404,
            code="agent_lab_todo_missing",
        )
    capture_event(
        todo.user_id,
        AnalyticsEvents.TODO_SUBSCRIPTION_REGISTERED,
        {
            "trigger_name": SANDBOX_RUN_TRIGGER,
            "action": subscription.action.value,
            "resolution": subscription.resolution.value,
            "condition_count": 0,
            "repaired": False,
            "cooldown_seconds": 0,
        },
    )
    await record_activity(
        todo.id,
        todo.user_id,
        TodoActivityEvent.WATCH_ADDED,
        f"watching sandbox run {run_id} (run folder {run_dir(run_id)})",
    )
    return subscription
