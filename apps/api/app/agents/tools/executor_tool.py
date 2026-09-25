"""Executor tools for comms agent: delegate tasks and cancel running tasks.

Non-blocking: spawns executor as a background asyncio task and returns
immediately. The executor saves its terminal text as a new bot message
in MongoDB and pushes it via WebSocket when it completes — see
run_executor_background.
"""

import asyncio
import time
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_queue import (
    adopt_lock,
    build_lock_value,
    decode_raw_item,
    parse_lock_value,
    release_lock_if_owned,
    try_acquire_lock,
)
from app.agents.core.background.executor_runner import run_executor_background
from app.agents.core.background.running_registry import RunningSubagents, stop_stream
from app.agents.core.background.session import (
    ExecutorRun,
    RunIdentity,
    RunKind,
    mark_executor_spawned,
)
from app.agents.core.subagents.subagent_runner import compose_executor_brief
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.general import CALL_EXECUTOR_NAME
from app.constants.log_tags import LogTag
from app.constants.streaming import WS_EVENT_EXECUTOR_CANCELLED
from app.core.stream_manager import StreamManager
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.services.hil.ledger_decide import cancel_ledger_approvals
from app.services.hil.resolution import cancel_conversation_approvals
from app.services.workflow.execution_service import get_last_run_brief
from app.services.workflow.playbook.check import playbook_check_brief
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

# A same-turn "stop X, do Y" redirect races call_executor against
# cancel_executor for the busy lock; these bound the wait for the cancel to free
# it so Y runs live. DETECT: max wait for evidence of a cancel; WAIT: total cap.
REDIRECT_CANCEL_DETECT_S = 0.4
REDIRECT_CANCEL_WAIT_S = 1.5
REDIRECT_CANCEL_POLL_S = 0.05


async def _acquire_lock_through_redirect(
    lock_key: str,
    lock_value: str,
    held_stream_id: str,
) -> bool:
    """Take the busy lock once an in-flight cancel of its current holder frees it.

    Returns True if the lock was acquired for a live run, False if the holder is
    not being cancelled (a genuinely busy different turn — queue instead) or it
    did not release within the wait budget.
    """
    if not held_stream_id:
        return False
    waited = 0.0
    saw_cancel = False
    # Polls Redis state (try_acquire_lock / is_cancelled) freed by cancel_executor,
    # which may run in a different uvicorn worker — an asyncio.Event can't observe
    # that cross-process release, so polling is the correct mechanism here.
    while waited < REDIRECT_CANCEL_WAIT_S:  # NOSONAR python:S7484
        if not saw_cancel:
            saw_cancel = await StreamManager.is_cancelled(held_stream_id)
        # Try the lock on every poll: cancel_executor deletes the busy key
        # without calling cancel_stream for empty/"1" stream ids, so
        # is_cancelled() may never flip though the holder is gone.
        if await try_acquire_lock(lock_key, lock_value):
            return True
        if not saw_cancel and waited >= REDIRECT_CANCEL_DETECT_S:
            return False
        await asyncio.sleep(REDIRECT_CANCEL_POLL_S)
        waited += REDIRECT_CANCEL_POLL_S
    return False


@tool
async def call_executor(
    config: RunnableConfig,
    task: Annotated[
        str,
        "The task to execute - describe what needs to be done",
    ],
    acceptance_criteria: Annotated[
        list[str],
        "What must be TRUE for this task to count as done, as a checklist (e.g. "
        "['the 3 promo emails archived', 'the offer letter flagged']). Give the "
        "executor a concrete target so it doesn't stop after one step. NEVER "
        "omit: even a single-step ask needs a concrete done state.",
    ],
    active_todo_id: Annotated[
        str | None,
        "Optional tracked-todo ID to BIND this executor run to. When set, "
        "the executor's canvas writes default to this todo's canvas and a "
        "🎯 ACTIVE TODO banner is added to its context. Use when delegating "
        "work that's clearly about a specific existing tracked todo (e.g. "
        "'update progress on todo X', 'continue working on Y'). Omit for "
        "general tasks.",
    ] = None,
) -> str:
    """Delegate a task to the executor agent for background execution.

    Use this when the user asks you to do something that requires action
    (creating todos, checking calendar, sending emails, searching, etc.)
    or when you need context from your capabilities.

    The executor runs in the background and posts its result to the
    conversation as a new bot message when it completes.
    """
    base_configurable: AgentConfigurable = agent_configurable(config)
    # Shallow-copy so the executor's overrides (todo binding) never mutate the
    # comms agent's live RunnableConfig. The model is inherited from the comms
    # configurable (set by per-plan routing).
    configurable: AgentConfigurable = {**base_configurable}
    if active_todo_id:
        configurable["active_todo_id"] = active_todo_id
    conversation_id = configurable.get("thread_id", "")

    if not conversation_id:
        log.error(f"{LogTag.TOOL} call_executor: missing thread_id in configurable")
        return "Internal error: conversation context unavailable. Please try again."

    task_id = str(uuid4())
    # Read off the configurable, never a tool argument: asking the comms model to
    # re-transcribe the request corrupted 3 of 4 recipient addresses on a pasted
    # billing table and dropped the verbatim copy entirely.

    # A workflow run's threads are reset before it starts, so its previous run
    # reaches the executor here — as one recorded trace instead of the whole
    # replayed transcript. Empty for interactive chat and for a first run.
    workflow_id = base_configurable.get("workflow_id")
    user_id = base_configurable.get("user_id")
    is_workflow_run = bool(workflow_id and user_id)
    last_run = await get_last_run_brief(workflow_id, user_id) if is_workflow_run else ""
    # Asked here, not at narration time: write_playbook is an executor tool that
    # comms (which narrates the result) cannot reach. The stopped-replay record
    # rides along verbatim for the same reason as the request: comms paraphrases.
    playbook_check = (
        await playbook_check_brief(
            workflow_id, user_id, fallback_note=base_configurable.get("playbook_fallback")
        )
        if is_workflow_run
        else ""
    )

    composed_task = compose_executor_brief(
        task,
        acceptance_criteria,
        verbatim_request=base_configurable.get("user_request"),
        last_run=last_run,
        playbook_check=playbook_check,
    )

    try:
        return await _dispatch_executor(
            task=composed_task,
            task_id=task_id,
            configurable=configurable,
            conversation_id=conversation_id,
        )
    except Exception as e:
        log.error(f"{LogTag.TOOL} Error dispatching executor", error=str(e))
        # Release only if this dispatch's acquire holds the lock: an unconditional
        # delete here freed a FOREIGN lock when failure hit the queue branch,
        # letting a second concurrent executor start in the same conversation.
        await release_lock_if_owned(conversation_id, configurable.get("stream_id"), task_id)
        return f"Error starting task: {e!s}"


async def _dispatch_executor(
    *,
    task: str,
    task_id: str,
    configurable: AgentConfigurable,
    conversation_id: str,
) -> str:
    """Core dispatch logic — acquire lock, queue if busy, or spawn."""
    log.set(
        tool={
            "name": CALL_EXECUTOR_NAME,
            "action": "dispatch",
            "task_id": task_id,
        },
    )
    stream_id = configurable.get("stream_id")
    user_message_id = configurable.get("user_message_id")
    bot_message_id = configurable.get("bot_message_id")
    # Dispatch stamp every later latency derives from; monotonic, never logged.
    t_dispatch = time.perf_counter()

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    lock_value = build_lock_value(stream_id, task_id)

    # A workflow fire reserves its conversation up front, so a held lock here
    # is its own claim. Adopting it turns the reservation into a hand-off
    # rather than a self-inflicted queue.
    acquired = await try_acquire_lock(lock_key, lock_value)
    if not acquired and (reserved := configurable.get("executor_lock_reservation")):
        acquired = await adopt_lock(conversation_id, reserved, lock_value)

    if not acquired:
        # The lock is held: same stream_id means a duplicate call_executor in one
        # turn (reject it — the first dispatch covers the turn); a different one
        # means a new request while busy, handed to the live run's inbox.
        held_value = await redis_cache.client.get(lock_key)
        held_stream_id = parse_lock_value(decode_raw_item(held_value))[0] if held_value else ""
        if stream_id and held_stream_id == stream_id:
            log.warning(
                f"{LogTag.TOOL} Duplicate call_executor in same turn — ignored, not queued",
                task_id=task_id,
                stream_id=stream_id,
                conversation_id=conversation_id,
            )
            return (
                "That task is already running from this same message, not "
                "starting it again. The results are on the way."
            )

        # A same-turn redirect (cancel + call_executor together) races the
        # cancel: wait for it to free the lock and run live in the same turn's
        # card instead of queuing. Only waits when a cancel is in flight.
        redirect_start = time.perf_counter()
        redirect_acquired = await _acquire_lock_through_redirect(
            lock_key, lock_value, held_stream_id
        )
        if redirect_acquired:
            log.set(
                tool={
                    "name": CALL_EXECUTOR_NAME,
                    "action": "dispatch",
                    "task_id": task_id,
                    "redirect_wait_ms": round((time.perf_counter() - redirect_start) * 1000.0, 2),
                },
            )
            log.info(
                f"{LogTag.TOOL} Acquired executor lock after redirect cancel — running live",
                task_id=task_id,
                conversation_id=conversation_id,
            )
        else:
            # The executor is mid-run on a different turn: hand this to that run,
            # whose drain hook reads the inbox before every model call.
            await ExecutorInbox(conversation_id).append(task_id, task)
            log.info(
                f"{LogTag.TOOL} Executor busy — task handed to the live run",
                task_id=task_id,
                conversation_id=conversation_id,
            )
            return (
                "It's been added to the work already in progress and will be "
                "covered in the same answer. Confirm briefly in plain words — "
                "never mention runs, task ids, queues, or waiting."
            )

    # MCP tools load lazily inside each subagent's first use — the old eager
    # warmup hit get_all_connected_tools() on every executor call and
    # dominated cold-start latency.

    if stream_id:
        mark_executor_spawned(stream_id)

    run = ExecutorRun.from_configurable(
        configurable,
        identity=RunIdentity(
            stream_id=stream_id or "",
            conversation_id=conversation_id,
            kind=RunKind.LIVE,
            task_id=task_id,
            user_message_id=user_message_id,
            bot_message_id=bot_message_id,
            t_dispatch_perf=t_dispatch,
        ),
    )
    spawn_background_task(
        run_executor_background(
            run=run,
            task=task,
            configurable=configurable,
        ),
    )

    log.info(
        f"{LogTag.TOOL} Executor dispatched to background",
        task_id=task_id,
        stream_id=stream_id,
    )
    # Comms writes its user-facing reply from THIS string, before the executor
    # has run a single tool — so it must not read as completion, and it has to
    # name the approval gate the user may be about to see.
    return (
        f"Task accepted (task_id: {task_id}). Nothing has run yet: this only means the "
        "work has STARTED. Do not tell the user anything was sent, created, deleted, or "
        "finished. Risky actions pause for the user's approval first and they see an "
        "approval card; if that happens the work waits on them, not on you. Acknowledge "
        "that you are on it, and say the action is waiting for their approval if one is "
        "pending. This guidance applies ONLY to this acknowledgment. The real result "
        "arrives later as its own message and supersedes it completely: by then the gate "
        "is settled, so report what happened and never ask again for an approval the "
        "user has already given."
    )


@tool
async def cancel_executor(
    config: RunnableConfig,
    task_ids: Annotated[
        list[str],
        "List of task_ids to cancel. Empty list = cancel ALL (running + pending).",
    ] = [],  # noqa: B006 -- empty default is the cancel-all sentinel; list is never mutated
    message: Annotated[
        str | None,
        "What the user wants INSTEAD, when they are redirecting rather than just "
        "stopping ('stop that, do X'). Delivered to the executor together with the "
        "stop, so prefer this over a separate call_executor for a redirect.",
    ] = None,
) -> str:
    """Cancel background executor tasks by their task_ids.

    task_ids behavior:
    - Empty list [] = cancel EVERYTHING (running task + all queued).
      Use for: "stop everything", "cancel all", or generic "stop that".
    - Specific task_ids = cancel only those (running or pending), keep rest.
      Use for: "cancel the search task" / "stop the second one".
      Match user intent to task_ids from call_executor responses in
      conversation history (e.g. "Task accepted (task_id: abc-123)").

    For a redirect ("stop that, do X instead") pass ``message="X"``. The stop
    and the new instruction reach the executor together, so it cannot resume the
    abandoned task before hearing what to do instead.

    CRITICAL: NEVER use this tool unless the user EXPLICITLY asks to stop,
    cancel, or abort. Valid triggers: "stop that", "cancel it", "abort",
    "kill that task", "don't do that anymore", "cancel the X task".

    DO NOT use if the user is just changing the subject, asking a new
    question, or saying "nevermind" about a NEW request. Only the USER
    decides to cancel.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    conversation_id = configurable.get("thread_id", "")

    if not conversation_id:
        return "No conversation context available."

    lock_key = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
    inbox = ExecutorInbox(conversation_id)
    subagents = RunningSubagents(conversation_id)
    cancel_all = len(task_ids) == 0

    # Use raw client.get() — lock value is a plain string ("stream_id:task_id"),
    # not JSON. redis_cache.get() would fail to deserialize it.
    raw_lock = await redis_cache.client.get(lock_key)
    lock_value: str | None = decode_raw_item(raw_lock) if raw_lock is not None else None
    has_pending = await inbox.count() > 0
    has_subagents = bool(await subagents.live())

    if not lock_value and not has_pending and not has_subagents:
        return "No executor tasks are running or pending for this conversation."

    try:
        cancelled = await _cancel_running_task(
            lock_key,
            lock_value,
            task_ids,
            cancel_all,
            conversation_id,
        )
        # Running task was present but not targeted for cancellation
        # Whether the RUNNING task actually died — captured before `cancelled`
        # grows to include pending entries, which say nothing about the run.
        running_cancelled = bool(cancelled)
        # A background subagent outlives the run that dispatched it, so "stop
        # everything" reaches it even after that run has finished.
        stopped_subagents = await subagents.stop_all() if cancel_all else []
        skipped_running = bool(lock_value) and not running_cancelled
        if cancelled:
            # Only once the RUNNING task is actually gone: a cancel that spared it
            # (queued-only) must leave its approvals alone — it is still waiting on them.
            await cancel_conversation_approvals(conversation_id, configurable.get("user_id", ""))
            await cancel_ledger_approvals(conversation_id, configurable.get("user_id", ""))
        cancelled += await _cancel_pending_tasks(
            inbox,
            task_ids,
            cancel_all,
            conversation_id,
        )
        if stopped_subagents:
            cancelled.append(f"{len(stopped_subagents)} running subagent(s)")

        if not cancelled:
            return "None of the specified task_ids matched any running or pending tasks."

        # Record the stop into the per-conversation thread, or the next run
        # resumes exactly what the user stopped — but only when the RUNNING
        # task or its subagents actually died; a spared live executor would drain the notice.
        if running_cancelled or stopped_subagents:
            await inbox.announce_interruption(message)

        # Tell the client an agent-initiated cancel happened so it can clear the
        # stuck executor-pending loading state and finalize in-flight tool cards
        # — it has no other way to learn of a cancel it didn't initiate.
        await _broadcast_executor_cancelled(
            user_id=configurable.get("user_id", ""),
            conversation_id=conversation_id,
            cancelled=cancelled,
        )

        result = f"Cancelled: {', '.join(cancelled)}."
        if skipped_running:
            result += " Currently running task was not in the cancel list, still running."
        return result

    except Exception as e:
        # Deliberately no lock cleanup here: unconditional deletion previously
        # let two executors run concurrently on one conversation. TTL recovers it.
        log.error(f"{LogTag.TOOL} cancel_executor failed", error=str(e))
        return f"Cancellation attempted but hit an error: {e}"


async def _broadcast_executor_cancelled(
    *,
    user_id: str,
    conversation_id: str,
    cancelled: list[str],
) -> None:
    """Push the executor-cancelled control event to the user's clients."""
    if not user_id:
        return
    try:
        await websocket_manager.broadcast_to_user(
            user_id,
            {
                "type": WS_EVENT_EXECUTOR_CANCELLED,
                "conversation_id": conversation_id,
                "cancelled": cancelled,
            },
        )
    except Exception as e:  # best-effort UI signal
        log.warning(f"{LogTag.TOOL} Failed to broadcast executor.cancelled", error=str(e))


async def _cancel_running_task(
    lock_key: str,
    lock_value: str | None,
    task_ids: list[str],
    cancel_all: bool,
    conversation_id: str,
) -> list[str]:
    """Cancel the currently running executor if it matches task_ids."""
    if not lock_value:
        return []

    active_stream_id, active_task_id = parse_lock_value(lock_value)
    should_cancel = cancel_all or active_task_id in task_ids

    if not should_cancel:
        return []

    if active_stream_id and active_stream_id not in ("", "1"):
        await stop_stream(conversation_id, active_stream_id)

    await redis_cache.delete(lock_key)

    log.info(
        f"{LogTag.TOOL} cancel_executor: stopped running task",
        task_id=active_task_id,
        stream_id=active_stream_id,
        conversation_id=conversation_id,
    )
    return [active_task_id or "running"]


async def _cancel_pending_tasks(
    inbox: ExecutorInbox,
    task_ids: list[str],
    cancel_all: bool,
    conversation_id: str,
) -> list[str]:
    """Cancel work that is waiting for the executor — all of it, or by task_id."""
    if cancel_all:
        cleared = await inbox.clear()
        if cleared:
            log.info(
                f"{LogTag.TOOL} cancel_executor: cleared pending work",
                pending=cleared,
                conversation_id=conversation_id,
            )
        return [f"{cleared} pending task(s)"] if cleared else []

    cancelled = await inbox.discard(set(task_ids))
    if cancelled:
        log.info(
            f"{LogTag.TOOL} cancel_executor: removed pending tasks",
            removed=len(cancelled),
            conversation_id=conversation_id,
        )
    return cancelled


tools = [call_executor, cancel_executor]
