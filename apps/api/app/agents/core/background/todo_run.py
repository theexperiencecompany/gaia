"""Run a tracked todo on the executor, with no comms turn in front of it.

Comms has no work tools, so a comms hop in front of a background todo run only
paraphrased the brief and wrote a pre-work acknowledgement that was then
delivered as if it were the result. The executor does the work here, in the
todo's own chat: the run streams into it live, and its terminal outcome goes
through result_delivery, which keeps the report there, to todo_run_delivery.

The chat is reused across runs, but each new run starts from an empty executor
thread: what it needs of earlier runs comes from the todo's canvas and activity,
never from a replayed checkpoint. Only an approval resume continues the thread.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
import time
from typing import cast
from uuid import uuid4

from langgraph.constants import CONF

from app.agents.core.background.executor_capture import (
    register_executor_capture,
    teardown_executor_capture,
)
from app.agents.core.background.executor_queue import (
    announce_detached_stream,
    build_lock_value,
    end_detached_stream,
    release_lock_if_owned,
    try_acquire_lock,
)
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
from app.constants.log_tags import LogTag
from app.constants.streaming import DetachedStreamKind
from app.core.stream_manager import StreamManager
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
from app.services.checkpoint_thread_reset import reset_conversation_threads
from app.utils.background_tasks import spawn_background_task
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.wide_events import log

TODO_EXECUTOR_TASK_NAME = "tracked-todo-executor-run"


class TodoRunFailedError(RuntimeError):
    """The executor ended a tracked todo run in an error, or never finished it."""


class ExecutorBusyError(RuntimeError):
    """Another executor run holds the todo's chat, so this run never started."""


class TodoRunCancelledError(RuntimeError):
    """The user stopped the run from its chat before it finished."""


@dataclass(frozen=True)
class TodoRunRequest:
    """One tracked todo run: whose, which todo, the brief, and the todo's chat it runs in."""

    user: AuthenticatedUser
    todo_run: TodoRun
    todo_title: str
    task: str
    conversation_id: str
    #: A new run starts from an empty executor thread; an approval resume
    #: continues the thread the parked run left.
    fresh_thread: bool
    #: Awaited once the chat's executor lock is this run's, so a run that finds
    #: the chat busy never reads as started.
    on_started: Callable[[], Awaitable[object]] | None = None


async def run_todo_on_executor(request: TodoRunRequest) -> None:
    """Run the brief on the executor through to delivery; raises TodoRunFailedError on failure."""
    stream_id = str(uuid4())
    task_id = str(uuid4())
    conversation_id = request.conversation_id
    configurable = await _todo_run_configurable(request, stream_id)

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    if not await try_acquire_lock(lock_key, build_lock_value(stream_id, task_id)):
        raise ExecutorBusyError(
            f"the executor is already running in conversation {conversation_id}"
        )

    try:
        if request.on_started is not None:
            await request.on_started()
        # Under the lock: no other executor can be writing the threads it drops.
        if request.fresh_thread:
            await _reset_executor_threads(conversation_id)
        await announce_detached_stream(
            stream_id,
            conversation_id=conversation_id,
            user_id=request.user.user_id,
            task_id=task_id,
            bot_message_id=None,
            kind=DetachedStreamKind.EXECUTOR,
        )
    except Exception:
        # No run owns the lock yet, so nothing else would ever release it.
        await release_lock_if_owned(conversation_id, stream_id, task_id)
        raise

    register_executor_capture(stream_id)
    try:
        mark_executor_spawned(stream_id)
        run = replace(
            ExecutorRun.from_configurable(
                configurable,
                identity=RunIdentity(
                    stream_id=stream_id,
                    conversation_id=conversation_id,
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
            # The whole run, delivery included, so the worker's next steps see its
            # outcome; shielded so it is marked abandoned before it is cancelled.
            await asyncio.wait_for(asyncio.shield(run_task), BACKGROUND_EXECUTOR_WAIT_TIMEOUT)
        except TimeoutError:
            reason = f"the executor did not finish within {BACKGROUND_EXECUTOR_WAIT_TIMEOUT}s"
            # Abandoned, so the finalize the cancel triggers delivers nothing.
            mark_executor_failed(
                stream_id, reason
            )  # pragma: no mutate — the reason dies with the session torn down below
            # Stopped, or it keeps calling tools while the worker's retry runs the todo again.
            run_task.cancel()
            await asyncio.wait({run_task})
            raise TodoRunFailedError(reason) from None
        if await StreamManager.is_cancelled(stream_id):
            raise TodoRunCancelledError(
                f"the user stopped the run in conversation {conversation_id}"
            )
        if failure := executor_failure(stream_id):
            raise TodoRunFailedError(failure)
    finally:
        teardown_executor_capture(stream_id)
        # After delivery saved the report, so a client reading the chat at [DONE] finds it.
        await end_detached_stream(stream_id, cancelled=await StreamManager.is_cancelled(stream_id))


async def _reset_executor_threads(conversation_id: str) -> None:
    """Drop the executor threads earlier runs and follow-ups left, keeping the chat's own thread."""
    result = await reset_conversation_threads(conversation_id, keep_conversation_thread=True)
    if result is None:
        # No Postgres checkpointer (a dev box): there is no persisted thread to replay.
        log.warning(
            f"{LogTag.TODO} Todo chat executor-thread reset skipped — no checkpointer pool",
            conversation_id=conversation_id,
        )
        return
    log.set_ns(
        "tracked_todo",
        threads_reset=result.reset,
        threads_skipped_inflight=result.skipped_inflight,
    )


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
