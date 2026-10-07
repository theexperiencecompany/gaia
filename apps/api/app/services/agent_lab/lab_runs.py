"""Per-run identity for agent-lab runs: workdir layout plus the todo's run subscription.

A run is owned by the tracked todo that launched it through one trigger
subscription: every event the run reports fires that subscription, which runs
the todo with the event attached. Composio ids stay empty, so the ordinary
subscription teardown ends the run's watch without touching anything upstream.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from app.constants.execute import SANDBOX_LAB_MAX_RUN_SECONDS
from app.db.repositories.todos import todo_repository
from app.decorators.entitlements import is_paid
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
)
from app.services.agent_lab.agents_home import AGENTS_RUNS_DIR
from app.services.feature_flags import is_agent_lab_enabled
from app.services.triggers.subscription_service import store_subscription

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


class LabAccess(StrEnum):
    """Whether a user may run sandbox agents, and if not, which requirement is missing."""

    ALLOWED = "allowed"
    NOT_PAID = "not_paid"
    FLAG_OFF = "flag_off"


async def lab_access(user_id: str) -> LabAccess:
    """Check the paid plan and the AGENT_LAB flag: one rule for launching a run and receiving its events.

    Sharing it means a run is never launched whose events would then be refused.
    """
    if not await is_paid(user_id):
        return LabAccess.NOT_PAID
    if not await is_agent_lab_enabled(user_id):
        return LabAccess.FLAG_OFF
    return LabAccess.ALLOWED


@dataclass(frozen=True)
class RunCapStatus:
    """Whether any watched run is still within the run cap, and the todos whose runs all passed it."""

    live: bool
    capped_todo_ids: list[str]


def run_cap_status(todos: list[TodoDocument]) -> RunCapStatus:
    """Split the todos' watched runs by SANDBOX_LAB_MAX_RUN_SECONDS since each run started."""
    now = datetime.now(UTC)
    started = [(todo.id, sub.created_at) for todo in todos for sub in run_subscriptions(todo)]
    live = any((now - at).total_seconds() <= SANDBOX_LAB_MAX_RUN_SECONDS for _, at in started)
    capped = [] if live else sorted({todo_id for todo_id, _ in started})
    return RunCapStatus(live=live, capped_todo_ids=capped)


async def keeps_sandbox_awake(user_id: str) -> bool:
    """Whether the user's sandbox must stay running: the flag is on and a watched run is within the cap.

    A coding agent works without GAIA calls, so nothing else would hold the
    sandbox; past the cap, or with no run, it idle-pauses like any other.
    """
    if not await is_agent_lab_enabled(user_id):
        return False
    todos = await todo_repository.find_active_by_user_and_trigger(user_id, SANDBOX_RUN_TRIGGER)
    return run_cap_status(todos).live


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
    await store_subscription(
        todo,
        subscription,
        repaired=False,
        activity=f"watching sandbox run {run_id} (run folder {run_dir(run_id)})",
    )
    return subscription
