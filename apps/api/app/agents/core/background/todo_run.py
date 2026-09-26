"""Run a tracked todo on the executor, with no comms turn in front of it.

Comms has no work tools, so a comms hop in front of a background todo run only
paraphrased the brief and wrote a pre-work acknowledgement that was then
delivered as if it were the result. The executor does the work here; its
terminal outcome goes through result_delivery to todo_run_delivery.
"""

import asyncio
from dataclasses import dataclass, replace
import time
from typing import cast
from uuid import uuid4

from langgraph.constants import CONF

from app.agents.core.background.executor_capture import (
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import build_lock_value, try_acquire_lock
from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    TodoRun,
    executor_failure,
    mark_executor_failed,
    mark_executor_spawned,
)
from app.agents.llm.lane import AgentRole
from app.constants.cache import BACKGROUND_EXECUTOR_WAIT_TIMEOUT, EXECUTOR_BUSY_PREFIX
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTurn,
    background_authorization,
    build_agent_config,
)
from app.models.agent_config import AgentConfigurable
from app.models.agent_models import agent_user_context
from app.models.user_models import AuthenticatedUser
from app.utils.background_tasks import spawn_background_task
from app.utils.user_preferences_utils import onboarding_preferences

TODO_EXECUTOR_TASK_NAME = "tracked-todo-executor-run"


class TodoRunFailedError(RuntimeError):
    """The executor ended a tracked todo run in an error, or never finished it."""


@dataclass(frozen=True)
class TodoRunRequest:
    """One tracked todo run: whose, which todo, the brief, and the conversation it runs in."""

    user: AuthenticatedUser
    todo_run: TodoRun
    todo_title: str
    task: str
    conversation_id: str


async def run_todo_on_executor(request: TodoRunRequest) -> None:
    """Run the brief on the executor through to delivery; raises TodoRunFailedError on failure."""
    stream_id = str(uuid4())
    task_id = str(uuid4())
    configurable = await _todo_run_configurable(request, stream_id)

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{request.conversation_id}"
    if not await try_acquire_lock(lock_key, build_lock_value(stream_id, task_id)):
        raise TodoRunFailedError(
            f"the executor is already running in conversation {request.conversation_id}"
        )

    register_executor_capture(stream_id)
    try:
        mark_executor_spawned(stream_id)
        run = replace(
            ExecutorRun.from_configurable(
                configurable,
                identity=RunIdentity(
                    stream_id=stream_id,
                    conversation_id=request.conversation_id,
                    kind=RunKind.LIVE,
                    task_id=task_id,
                    user_message_id=None,
                    t_dispatch_perf=time.perf_counter(),
                ),
            ),
            todo_run=request.todo_run,
        )
        run_task = spawn_background_task(
            run_executor_background(run=run, task=request.task, configurable=configurable),
            name=TODO_EXECUTOR_TASK_NAME,
        )
        try:
            # The whole run, delivery included, so the worker's next steps see
            # its outcome; shielded so a timed-out wait leaves the run alive.
            await asyncio.wait_for(asyncio.shield(run_task), BACKGROUND_EXECUTOR_WAIT_TIMEOUT)
        except TimeoutError:
            reason = f"the executor did not finish within {BACKGROUND_EXECUTOR_WAIT_TIMEOUT}s"
            # Abandoned: its late finalize delivers nothing while the retry runs.
            mark_executor_failed(stream_id, reason)
            raise TodoRunFailedError(reason) from None
        if failure := executor_failure(stream_id):
            raise TodoRunFailedError(failure)
    finally:
        teardown_executor_capture(stream_id)


async def _todo_run_configurable(request: TodoRunRequest, stream_id: str) -> AgentConfigurable:
    """Build the root configurable the executor inherits, as a comms turn would have."""
    user = request.user
    user_preferences, writing_style = onboarding_preferences(user.onboarding)
    config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=request.conversation_id,
            user=agent_user_context(user),
            agent_name="executor_agent",
        ),
        lane=AgentLane(role=AgentRole.EXECUTOR),
        turn=AgentTurn(
            active_todo_id=request.todo_run.todo_id,
            execution_mode="background",
            # The todo's own title authorizes its gated calls the way a live
            # turn's words would; the run brief is generated and never does.
            user_messages=background_authorization(
                [], execution_mode="background", todo_title=request.todo_title
            ),
            user_preferences=user_preferences,
            writing_style=writing_style,
        ),
    )
    # Indexed, not read via agent_configurable: this bag is written to.
    configurable = cast(AgentConfigurable, config[CONF])
    configurable["stream_id"] = stream_id
    return configurable
