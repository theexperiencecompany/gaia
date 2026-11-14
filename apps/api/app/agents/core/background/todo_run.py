"""Run a tracked todo on the executor in its own chat, logged so the conversation step writes its result up.

Comms has no work tools, so a comms hop in front of a background todo run only
paraphrased the brief. The executor does the work: the run is a TodoWoke entry in
the todo's chat and work that answers it, and the reply the step writes for that
work is the run's write-up, which todo_run_delivery sends on.

The chat is reused across runs, but each new run starts from an empty executor
thread: what it needs of earlier runs comes from the todo's canvas and activity,
never from a replayed checkpoint. Only an approval resume continues the thread.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import time
from typing import cast
from uuid import uuid4

from langgraph.constants import CONF

from app.agents.core.background.executor_queue import (
    build_lock_value,
    release_lock_if_owned,
    try_acquire_lock,
)
from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    mark_executor_failed,
    mark_executor_spawned,
)
from app.agents.core.background.todo_run_delivery import (
    FinishedTodoRun,
    finish_todo_run,
    hand_unfinished_run_to_job,
)
from app.agents.llm.lane import AgentRole
from app.constants.cache import BACKGROUND_EXECUTOR_WAIT_TIMEOUT, EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.helpers.agent_helpers import (
    AgentIdentity,
    AgentLane,
    AgentTurn,
    background_authorization,
    build_agent_config,
)
from app.models.agent_config import AgentConfigurable
from app.models.agent_models import agent_user_context
from app.models.conversation_log_models import LoggedEntry, TodoRun, TodoWoke, WorkOutcome
from app.models.user_models import AuthenticatedUser
from app.services.checkpoint_thread_reset import reset_conversation_threads
from app.services.conversation.log import accept
from app.services.conversation.outcome import EntryOutcome, await_outcome
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.work_log import record_work_carried
from app.utils.background_tasks import spawn_background_task
from app.utils.errors import ConversationNotFoundError
from app.utils.user_preferences_utils import onboarding_preferences
from shared.py.conversation_wire import ReplyOutcome
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
    """One tracked todo run: whose, which run of which todo, the brief, and the todo's chat it runs in."""

    user: AuthenticatedUser
    todo_run: TodoRun
    task: str
    conversation_id: str
    #: A new run starts from an empty executor thread; an approval resume
    #: continues the thread the parked run left.
    fresh_thread: bool
    #: Awaited once the chat's executor lock is this run's, so a run that finds
    #: the chat busy never reads as started.
    on_started: Callable[[], Awaitable[object]] | None = None


async def run_todo_on_executor(request: TodoRunRequest) -> None:
    """Run the brief on the executor through to its write-up and delivery; raises TodoRunFailedError on failure.

    A run parked on an approval returns with nothing delivered: the run its approval resumes reports it.
    """
    stream_id = str(uuid4())
    task_id = str(uuid4())
    conversation_id = request.conversation_id
    user_id = request.user.user_id
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
        woke = await _log_the_wake(request, task_id)
    except Exception:
        # No run owns the lock yet, so nothing else would ever release it.
        await release_lock_if_owned(conversation_id, stream_id, task_id)
        raise

    mark_executor_spawned(stream_id)
    run = ExecutorRun.from_configurable(
        configurable,
        identity=RunIdentity(
            stream_id=stream_id,
            conversation_id=conversation_id,
            kind=RunKind.LIVE,
            task_id=task_id,
            user_message_id=None,
            t_dispatch_perf=time.perf_counter(),
        ),
    )
    run_task = spawn_background_task(
        run_executor_background(run=run, task=request.task, configurable=configurable),
        name=TODO_EXECUTOR_TASK_NAME,
    )
    try:
        # Shielded so it is marked abandoned before it is cancelled.
        await asyncio.wait_for(asyncio.shield(run_task), BACKGROUND_EXECUTOR_WAIT_TIMEOUT)
    except TimeoutError:
        reason = f"the executor did not finish within {BACKGROUND_EXECUTOR_WAIT_TIMEOUT}s"
        # Abandoned, so the finalize the cancel triggers logs no result.
        mark_executor_failed(
            stream_id, reason
        )  # pragma: no mutate — the reason dies with the session torn down below
        # Stopped, or it keeps calling tools while the worker's retry runs the todo again.
        run_task.cancel()
        await asyncio.wait({run_task})
        raise TodoRunFailedError(reason) from None
    log_port = runtime_ports().log
    try:
        state = await log_port.state(conversation_id, user_id)
    except ConversationNotFoundError:
        # The todo was deleted with its chat while the run went: nothing is left to deliver.
        log.set_ns("tracked_todo", chat_deleted=True)
        return
    if any(work.task_id == task_id for work in state.work):
        log.set_ns("tracked_todo", parked_on_approval=True)
        return
    outcome = await await_outcome(
        log_port, conversation_id, user_id, woke, BACKGROUND_EXECUTOR_WAIT_TIMEOUT
    )
    finished = _finished_run(request, task_id, outcome)
    if (undone := await finish_todo_run(finished)) is not None:
        await hand_unfinished_run_to_job(undone)


async def _log_the_wake(request: TodoRunRequest, task_id: str) -> LoggedEntry:
    """Log the wake in the todo's chat, then the run's work as answering it; return the wake."""
    run = request.todo_run
    accepted = await accept(
        runtime_ports(),
        request.conversation_id,
        request.user.user_id,
        TodoWoke(id=f"todo:{run.run_id}", run=run),
    )
    woke = accepted.appended.logged
    if not await record_work_carried(request.conversation_id, request.user.user_id, task_id, woke):
        raise TodoRunCancelledError(
            f"a Stop in conversation {request.conversation_id} came before the run started"
        )
    return woke


def _finished_run(request: TodoRunRequest, task_id: str, outcome: EntryOutcome) -> FinishedTodoRun:
    """Read what the run's reply settled to; raise when the run was stopped or its work did not finish."""
    run = request.todo_run
    if outcome.settled is None or outcome.settled.outcome is ReplyOutcome.STOPPED:
        raise TodoRunCancelledError(
            f"the user stopped the run in conversation {request.conversation_id}"
        )
    work = next((item for item in outcome.work if item.task_id == task_id), None)
    if work is None or work.outcome is not WorkOutcome.DONE:
        raise TodoRunFailedError(work.report if work is not None else "its work never finished")
    return FinishedTodoRun(
        run_id=run.run_id,
        todo_id=run.todo_id,
        user_id=request.user.user_id,
        conversation_id=request.conversation_id,
        trigger_type=run.trigger_type,
        report_form=run.report_form,
        result_text=work.report,
        write_up=outcome.text,
        reply=outcome.settled.outcome,
        nothing_for_user=work.nothing_for_user,
    )


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
                [], execution_mode="background", todo_title=request.todo_run.title
            ),
            user_preferences=user_preferences,
            writing_style=writing_style,
        ),
    )
    # Indexed, not read via agent_configurable: this bag is written to.
    configurable = cast(AgentConfigurable, config[CONF])
    configurable["stream_id"] = stream_id
    return configurable
