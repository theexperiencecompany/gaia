"""Per-run identity for agent-lab runs: workdir layout plus the GAIA task's run subscription.

A run is owned by the GAIA task that launched it through one subscription: every event the
run reports is taken by that subscription, which runs the task with the event attached.
Composio ids stay empty, so nothing upstream is registered or released for it, and the
watch ends with the task.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from app.constants.execute import SANDBOX_LAB_MAX_RUN_SECONDS
from app.constants.tasks import Assignee, TaskFlag, TaskLogEvent
from app.db.repositories.tasks import task_repository
from app.decorators.entitlements import is_paid
from app.models.task_models import TaskDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.agent_lab.agents_home import AGENTS_RUNS_DIR
from app.services.feature_flags import is_agent_lab_enabled
from app.services.tasks.run_records import record_event
from app.utils.errors import AppError

#: Trigger name of a task's subscription to one of its sandbox runs.
SANDBOX_RUN_TRIGGER: Final[str] = "sandbox_run"

#: Key in the subscription's trigger_data naming the run it watches.
RUN_ID_KEY: Final[str] = "run_id"

#: Seed runs CLI installs, so allow time for a cold download.
LAB_SEED_TIMEOUT_SECONDS: Final[int] = 300


def run_dir(run_id: str) -> str:
    """Return the run's folder (its env file) under the agents' home."""
    return f"{AGENTS_RUNS_DIR}/{run_id}"


def run_subscriptions(task: TaskDocument) -> list[TriggerSubscription]:
    """Return the task's live subscriptions to its sandbox runs."""
    return [
        s
        for s in task.subscriptions
        if s.trigger_name == SANDBOX_RUN_TRIGGER and s.status is TriggerSubscriptionStatus.ACTIVE
    ]


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


def run_refusal(task: TaskDocument) -> str | None:
    """Say why the task cannot own a sandbox run, None when it can: its events would go unheard."""
    if task.assignee is not Assignee.GAIA:
        return f"task {task.id} is the user's own to-do, not GAIA's"
    if task.completed:
        return f"task {task.id} is completed; create a new one"
    if TaskFlag.FAILED in task.status_flags:
        return f"task {task.id} is marked failed; reset it first"
    if not task.active and task.pause_reason is None:
        return f"task {task.id} was stopped; create a new one"
    return None


@dataclass(frozen=True)
class RunCapStatus:
    """Whether any watched run is still within the run cap, and the tasks whose runs all passed it."""

    live: bool
    capped_task_ids: list[str]


def run_cap_status(tasks: list[TaskDocument]) -> RunCapStatus:
    """Split the tasks' watched runs by SANDBOX_LAB_MAX_RUN_SECONDS since each run started."""
    now = datetime.now(UTC)
    started = [(task.id, sub.created_at) for task in tasks for sub in run_subscriptions(task)]
    live = any((now - at).total_seconds() <= SANDBOX_LAB_MAX_RUN_SECONDS for _, at in started)
    capped = [] if live else sorted({task_id for task_id, _ in started})
    return RunCapStatus(live=live, capped_task_ids=capped)


async def watching_tasks(user_id: str) -> list[TaskDocument]:
    """Return the user's open tasks listening to a sandbox run of theirs."""
    tasks = await task_repository.find_listening_by_user_and_trigger(user_id, [SANDBOX_RUN_TRIGGER])
    return [task for task in tasks if run_subscriptions(task)]


async def lab_run_status(user_id: str) -> RunCapStatus:
    """Split the user's watched runs by the cap; a live one keeps the sandbox awake.

    A coding agent works without GAIA calls, so nothing else holds the sandbox.
    The flag gates launching a run, never this: it reads off whenever PostHog
    is unreachable, and a running agent must not freeze on that.
    """
    return run_cap_status(await watching_tasks(user_id))


def find_run(
    tasks: list[TaskDocument], run_id: str
) -> tuple[TaskDocument, TriggerSubscription] | None:
    """Return the task subscribed to run_id with that subscription, if any task is."""
    for task in tasks:
        for subscription in run_subscriptions(task):
            if run_id_of(subscription) == run_id:
                return task, subscription
    return None


async def subscribe_task_to_run(task: TaskDocument, run_id: str) -> TriggerSubscription:
    """Attach the run's subscription to the task; cooldown 0 so no event is ever held back."""
    subscription = TriggerSubscription(
        trigger_name=SANDBOX_RUN_TRIGGER,
        action=SubscriptionAction.EXECUTE,
        cooldown_seconds=0,
        resolution=SubscriptionResolution.ACCOUNT,
        trigger_data={RUN_ID_KEY: run_id},
    )
    written = await task_repository.add_subscription(
        task.id, user_id=task.user_id, subscription=subscription
    )
    if written is None:
        raise AppError(
            message="the task could not be subscribed to its sandbox run",
            why=f"task {task.id} is gone",
            fix="check the task still exists, then launch the run again",
            status_code=404,
            code="task_subscription_not_stored",
        )
    await record_event(
        written,
        TaskLogEvent.SUBSCRIBED,
        f"watching sandbox run {run_id} (run folder {run_dir(run_id)})",
    )
    return subscription


async def stop_watching_run(task_id: str, user_id: str, subscription_id: str) -> None:
    """Drop the subscription of a run that never started, so it does not count as live."""
    await task_repository.remove_subscriptions(
        task_id, user_id=user_id, subscription_ids=[subscription_id]
    )
