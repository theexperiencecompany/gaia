"""
ARQ worker tasks for executing scheduled tracked todos.

Handles:
- Acquiring Redis locks to prevent double-execution
- Retry logic with exponential backoff
- Workflow-based and agent-based execution paths
- Recurrence scheduling (re-enqueue after success)
- Safety-net cron for orphaned todos
"""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
import random
from typing import Any, cast
from uuid import uuid4

from arq.connections import ArqRedis

from app.agents.core.agent import call_agent_silent
from app.constants.todos import FAILED_LABEL, PENDING_QUESTION_TTL, terminal_marker_key
from app.db.repositories.todos import todo_repository
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument, TodoUpdate
from app.models.user_models import AuthenticatedUser
from app.services.notification_service import notification_service
from app.services.todo_canvas_storage import read_canvas
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.cron_utils import CronError, get_next_run_time
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [timedelta(hours=1), timedelta(hours=4)]
LOCK_TTL_SECONDS = 1800
# The lock is renewed well inside its TTL so a long run never loses it, and
# released by compare-and-delete so an expired holder can't delete a successor's lock.
LOCK_HEARTBEAT_SECONDS = 120

# Redis Lua: only touch the lock if we still own it (value == our token).
_LOCK_EXTEND_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
_LOCK_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


class TerminalToolNotCalled(RuntimeError):
    """A scheduled tracked-todo run ended without calling finish_todo_run."""


async def _load_user_with_tz(user_id: str) -> tuple[AuthenticatedUser, Timezone]:
    """Fetch user record once and resolve their home timezone.

    Returns (user_data with user_id populated, Timezone). Uses the canonical
    Timezone value object so a stored ±HH:MM offset doesn't crash ZoneInfo;
    falls back to UTC if the user record or timezone is missing.
    """
    try:
        user_data = await get_user_by_id(user_id)
        if user_data:
            user_data["user_id"] = user_id
            # The legacy bridge dict is a spread of a validated UserDocument plus
            # the user_id stamped above, which is exactly AuthenticatedUser's
            # shape — cast, not isinstance (Type Safety item 12). Narrowing it to
            # the fields the agent reads would drop `onboarding`, which
            # construct_langchain_messages needs for custom instructions.
            return cast(AuthenticatedUser, user_data), Timezone.parse(user_data.get("timezone"))
        return {"user_id": user_id}, Timezone.utc()
    except Exception as e:
        log.warning("tracked_todo.load_user_failed", user_id=user_id, error=str(e))
        return {"user_id": user_id}, Timezone.utc()


async def execute_tracked_todo(_ctx: dict[str, Any], todo_id: str) -> str:
    """
    ARQ task: execute a single scheduled tracked todo.

    Acquires a Redis lock to prevent concurrent execution, then delegates
    to the retry/execution helper. The lock is always released in the
    finally block.
    """
    log.set(todo_id=todo_id)
    log.info("tracked_todo.execute_started", todo_id=todo_id)

    pool = await RedisPoolManager.get_pool()
    lock_key = f"gaia_todo_exec:{todo_id}"

    lock_token = uuid4().hex
    acquired = await pool.set(lock_key, lock_token, nx=True, ex=LOCK_TTL_SECONDS)
    if not acquired:
        log.info("tracked_todo.execute_lock_held", todo_id=todo_id)
        return f"skipped:{todo_id} (lock held)"

    # ArqRedis's stub doesn't declare eval; redis-py's async client does.
    lua: Any = cast("ArqRedis", pool)

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(LOCK_HEARTBEAT_SECONDS)
            try:
                await lua.eval(_LOCK_EXTEND_LUA, 1, lock_key, lock_token, LOCK_TTL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Transient Redis errors must not end renewal — a lapsed lock
                # lets a second execution in. Keep retrying on the next tick.
                log.warning(
                    "tracked_todo.lock_renew_failed",
                    todo_id=todo_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        return await _execute_todo_with_retry(todo_id, pool)
    finally:
        heartbeat_task.cancel()
        # Await cancellation before releasing so the renewer can't fire a
        # renewal that lands AFTER our release and resurrects the lock.
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        await lua.eval(_LOCK_RELEASE_LUA, 1, lock_key, lock_token)


async def _execute_todo_with_retry(todo_id: str, pool: ArqRedis) -> str:
    """
    Fetch the todo document, run the appropriate execution path, and
    handle retry / recurrence logic on the result.
    """
    doc = await todo_repository.get_by_id(todo_id)
    if not doc:
        log.warning("tracked_todo.execute_not_found", todo_id=todo_id)
        return f"not_found:{todo_id}"

    if doc.completed:
        log.info("tracked_todo.execute_already_completed", todo_id=todo_id)
        return f"completed:{todo_id}"

    # Skip expired todos — let maintenance sweep handle gracefully
    if doc.expires_at and doc.expires_at <= datetime.now(UTC):
        log.info(
            "tracked_todo.execute_expired",
            todo_id=todo_id,
            expires_at=doc.expires_at.isoformat(),
        )
        return f"expired:{todo_id}"

    # Skip failed todos — user must manually reset before re-execution
    if FAILED_LABEL in doc.labels:
        log.info("tracked_todo.execute_marked_failed", todo_id=todo_id)
        return f"skipped:{todo_id} (marked failed)"

    user_id = doc.user_id
    retry_count = doc.gaia_retry_count

    if not user_id:
        log.error("tracked_todo.execute_missing_user_id", todo_id=todo_id)
        return f"error:{todo_id} (missing user_id)"

    # Single user fetch per run — pattern matches workflow_tasks.py:416–427.
    # Reused for both agent execution (timezone/model config) and the next-run
    # computation below, so a tz change takes effect on the next fire without
    # an extra DB round-trip.
    user_data, user_tz = await _load_user_with_tz(user_id)

    try:
        # A stale marker from a previous run of this todo would falsely satisfy
        # the terminal contract — clear it before the agent starts.
        await pool.delete(terminal_marker_key(todo_id))

        outcome = await _run_execution(doc, user_id, user_data=user_data)

        if outcome not in (None, "complete", "reschedule", "ask_user"):
            log.warning(
                "tracked_todo.unexpected_terminal_outcome", todo_id=todo_id, outcome=outcome
            )

        # When the run terminated itself via finish_todo_run (complete/reschedule),
        # it already decided the todo's next state — don't overwrite scheduled_at
        # or double-enqueue here. The retry budget still resets: the run succeeded.
        agent_decided_next = outcome in ("complete", "reschedule")

        # scheduled_at must always name the NEXT planned execution — it is the
        # field find_due_tracked_all_users selects on, so a value left pointing
        # at the run that just happened makes the safety net re-enqueue this
        # todo on every scan. Recurrence is evaluated in the user's stored
        # timezone (looked up once at the top of this run).
        next_run = (
            _compute_next_run(doc.recurrence, user_tz.value, anchor=doc.scheduled_at)
            if doc.recurrence and not agent_decided_next and outcome != "ask_user"
            else None
        )
        if agent_decided_next:
            update = TodoUpdate(gaia_retry_count=0)
        elif outcome == "ask_user":
            # The run asked the user a question: the recurrence must NOT advance
            # while a question is outstanding (the re-run comes from the user's
            # reply, or from the expiry sweep). Park scheduled_at on the
            # question's expiry so the safety net doesn't re-enqueue the blocked
            # todo on every scan.
            fresh = await todo_repository.get_by_id(todo_id)
            parked_until = (
                fresh.pending_question.expires_at
                if fresh and fresh.pending_question
                else datetime.now(UTC) + PENDING_QUESTION_TTL
            )
            update = TodoUpdate(gaia_retry_count=0, scheduled_at=parked_until)
        else:
            update = TodoUpdate(gaia_retry_count=0, scheduled_at=next_run)
        await todo_repository.update(todo_id, user_id=user_id, update=update)

        if next_run:
            await enqueue_worker_job(
                pool,
                "execute_tracked_todo",
                todo_id,
                _defer_until=next_run,
            )
            log.info(
                "tracked_todo.re_enqueued",
                todo_id=todo_id,
                next_run=next_run.isoformat(),
            )

        return f"success:{todo_id}"

    except Exception as exc:
        log.exception("tracked_todo.execution_failed", todo_id=todo_id, error=str(exc))
        new_retry_count = retry_count + 1

        if new_retry_count >= MAX_RETRY_ATTEMPTS:
            await todo_repository.update(
                todo_id, user_id=user_id, update=TodoUpdate(gaia_retry_count=new_retry_count)
            )
            await _mark_todo_failed(todo_id, user_id, doc)
            return f"failed:{todo_id} (max retries reached)"

        # Compute backoff delay
        backoff_index = min(new_retry_count - 1, len(RETRY_BACKOFF) - 1)
        backoff = RETRY_BACKOFF[backoff_index]
        next_attempt = datetime.now(UTC) + backoff
        # Park scheduled_at on the backoff target as well: left in the past it
        # keeps matching the safety net's due-query, which would fire the retry
        # on the next 30-minute scan and flatten the 1h/4h ladder.
        await todo_repository.update(
            todo_id,
            user_id=user_id,
            update=TodoUpdate(gaia_retry_count=new_retry_count, scheduled_at=next_attempt),
        )
        await enqueue_worker_job(
            pool,
            "execute_tracked_todo",
            todo_id,
            _defer_until=next_attempt,
        )
        log.info(
            "tracked_todo.retry_enqueued",
            todo_id=todo_id,
            next_attempt=next_attempt.isoformat(),
            attempt=new_retry_count,
            max_attempts=MAX_RETRY_ATTEMPTS,
        )
        return f"retry:{todo_id} (attempt {new_retry_count})"


async def _run_execution(
    doc: TodoDocument, user_id: str, *, user_data: AuthenticatedUser
) -> str | None:
    """
    Dispatch execution to the correct path:
    - If the todo has a workflow_id, queue the workflow.
    - Otherwise, run the agent directly.

    Returns the terminal outcome recorded by finish_todo_run (agent path only).
    """
    if doc.workflow_id:
        # Deferred import to avoid circular dependency
        # Deferred import: breaks circular dependency with the workflow queue/service stack
        from app.services.workflow.queue_service import (  # noqa: PLC0415 -- deferred
            WorkflowQueueService,
        )

        context = {
            "trigger_type": "scheduled_todo",
            "todo_id": doc.id,
        }
        success = await WorkflowQueueService.queue_workflow_execution(
            doc.workflow_id, user_id, context
        )
        if not success:
            raise RuntimeError(f"Failed to queue workflow {doc.workflow_id} for todo {doc.id}")
        log.info("tracked_todo.workflow_queued", workflow_id=doc.workflow_id, todo_id=doc.id)
        return None
    return await _execute_via_agent(doc, user_id, user_data=user_data)


def _extract_learnings(ref_canvas: str) -> str | None:
    """Return the ``## Learnings`` section of a canvas, or None if absent."""
    if not ref_canvas or "## Learnings" not in ref_canvas:
        return None
    learnings_start = ref_canvas.index("## Learnings")
    next_section = ref_canvas.find("\n## ", learnings_start + 1)
    if next_section != -1:
        return ref_canvas[learnings_start:next_section]
    return ref_canvas[learnings_start:]


async def _collect_reference_context(ref_ids: list[str], user_id: str) -> str:
    """Gather ``## Learnings`` from up to 5 referenced todos for prompt context."""
    if not ref_ids:
        return ""
    ref_parts: list[str] = []
    for ref_id in ref_ids[:5]:  # Cap at 5 to avoid context bloat
        try:
            ref_doc = await todo_repository.get_by_id(ref_id)
            if not ref_doc:
                continue
            learnings = _extract_learnings(await read_canvas(ref_id, user_id) or "")
            if learnings:
                ref_parts.append(f'From past todo "{ref_doc.title}":\n{learnings.strip()}')
        except Exception as e:
            log.debug("execute_todo.reference_read_failed", ref_id=ref_id, error=str(e))
            continue
    if not ref_parts:
        return ""
    return "\n\nPast experience (from similar completed todos):\n" + "\n\n".join(ref_parts)


def _build_execution_prompt(
    *, title: str, description: str, canvas_content: str | None, reference_context: str
) -> str:
    """Assemble the scheduled-run prompt from the todo's fields and context."""
    prompt_parts = [f"Execute the following scheduled task: {title}"]
    if description:
        prompt_parts.append(f"Details: {description}")
    if canvas_content:
        prompt_parts.append(f"Canvas context:\n{canvas_content}")
    if reference_context:
        prompt_parts.append(reference_context)
    prompt_parts.append(
        "MANDATORY: When the work for THIS run is done, you MUST call finish_todo_run "
        "as your final action — 'complete' (goal fully achieved), 'reschedule' (with "
        "reschedule_at) when work remains but should happen later, or 'ask_user' (with "
        "question) only when you are blocked on a decision only the user can make. "
        "Ending this run without finish_todo_run counts as a failed run."
    )
    return "\n\n".join(prompt_parts)


async def _execute_via_agent(
    doc: TodoDocument, user_id: str, *, user_data: AuthenticatedUser
) -> str | None:
    """
    Execute the todo using call_agent_silent directly (no workflow needed).

    Enforces the terminal contract: the run MUST end via finish_todo_run.
    Returns the terminal outcome recorded by that tool, or None when the run
    ended without it (which raises instead).
    """
    todo_id = doc.id

    # Read canvas content from the todo's Mongo-backed canvas field
    canvas_content: str | None = None
    try:
        canvas_content = await read_canvas(todo_id, user_id)
    except Exception as exc:
        log.warning(
            "tracked_todo.canvas_read_failed",
            todo_id=todo_id,
            error=str(exc),
        )

    # Read referenced canvases for institutional memory
    reference_context = await _collect_reference_context(doc.references, user_id)

    # Build prompt
    title = doc.title
    prompt = _build_execution_prompt(
        title=title,
        description=doc.description or "",
        canvas_content=canvas_content,
        reference_context=reference_context,
    )

    # Generate a fresh conversation_id for each execution to prevent
    # history accumulation in PostgreSQL. Each execution is independent.
    conversation_id = str(uuid4())

    request = MessageRequestWithHistory(
        message=prompt,
        messages=[],
        fileIds=[],
        fileData=[],
        selectedTool=None,
    )

    trigger_context = {
        "trigger_type": "scheduled_todo",
        "todo_id": todo_id,
        "todo_title": title,
        "active_todo_id": todo_id,
        "execution_mode": "background",
    }

    # Structural paper trail — write a start marker to the canvas Timeline
    # BEFORE the agent runs, so the run leaves evidence even if the LLM forgets.
    short_conv = conversation_id[:8]
    start_iso = datetime.now(UTC).isoformat()
    await tracked_todo_service.append_canvas_timeline(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"▶ {start_iso} — scheduled run started (conversation_id={short_conv})",
    )

    complete_message: str = ""
    try:
        complete_message, _tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            trigger_context=trigger_context,
        )
    except Exception as exc:
        # End marker: failure
        fail_iso = datetime.now(UTC).isoformat()
        await tracked_todo_service.append_canvas_timeline(
            todo_id=todo_id,
            user_id=user_id,
            entry=f"✗ {fail_iso} — scheduled run failed ({type(exc).__name__})",
        )
        raise

    # End marker: success
    end_iso = datetime.now(UTC).isoformat()
    summary = (complete_message or "").strip().replace("\n", " ")[:120]
    await tracked_todo_service.append_canvas_timeline(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"✓ {end_iso} — scheduled run finished (summary={summary!r})",
    )

    pool = await RedisPoolManager.get_pool()
    marker = await pool.get(terminal_marker_key(todo_id))
    if isinstance(marker, bytes):
        marker = marker.decode()
    if not marker:
        # No quiet exit: a run that never terminated through finish_todo_run is
        # a failed run and goes through the standard retry ladder.
        raise TerminalToolNotCalled(f"run for todo {todo_id} ended without calling finish_todo_run")

    log.info("tracked_todo.agent_completed", todo_id=todo_id, outcome=str(marker))
    return str(marker)


async def _mark_todo_failed(todo_id: str, user_id: str, doc: TodoDocument) -> None:
    """
    Mark the todo as permanently failed by adding a 'failed' label,
    then send an in-app notification to the user.
    """
    await todo_repository.add_labels(todo_id, user_id=user_id, labels=[FAILED_LABEL])
    log.info("tracked_todo.marked_failed", todo_id=todo_id)

    title: str = doc.title
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.ERROR,
                content=NotificationContent(
                    title=f"Scheduled Task Failed: {title}",
                    body=(
                        f"Your scheduled task '{title}' could not be completed after "
                        f"{MAX_RETRY_ATTEMPTS} attempts. Please check the task and try again."
                    ),
                ),
                metadata={
                    "todo_id": todo_id,
                    "retry_count": MAX_RETRY_ATTEMPTS,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(
            "tracked_todo.failure_notification_failed",
            todo_id=todo_id,
            error=str(notify_exc),
        )


def _compute_next_run(
    recurrence: str,
    recurrence_tz: str | None = None,
    anchor: datetime | None = None,
) -> datetime | None:
    """
    Compute the next scheduled run time from a recurrence string.

    Evaluated in the user's timezone (recurrence_tz, IANA name). Returned as
    a UTC-aware datetime suitable for ARQ's _defer_until.

    Supports named shortcuts:
    - "daily"    → next occurrence at the anchor's local wall-clock time
    - "weekly"   → next occurrence at the anchor's local weekday + time
    - "every_4h" → +4 hours (interval)
    - "every_1h" → +1 hour (interval)

    "daily"/"weekly" are anchored to ``anchor`` (the original scheduled_at) so
    a late run does NOT drift the wall-clock time forward. The next fire keeps
    the anchor's local time-of-day and advances by whole days/weeks until it is
    strictly in the future. Without an anchor we fall back to a plain delta.

    Falls back to croniter for cron expressions (e.g. "0 9 * * *"), which are
    evaluated in recurrence_tz so "9am" means user-local 9am.
    Returns None if the recurrence string is unrecognised.
    """
    # Canonical, offset-safe zone resolution (a stored ±HH:MM won't crash here).
    home_tz = Timezone.parse(recurrence_tz)
    tz = home_tz.tzinfo

    now_utc = datetime.now(UTC)

    interval_shortcuts: dict[str, timedelta] = {
        "every_4h": timedelta(hours=4),
        "every_1h": timedelta(hours=1),
    }
    if recurrence in interval_shortcuts:
        # Intervals are deltas from "now" — drift is acceptable/expected.
        return now_utc + interval_shortcuts[recurrence]

    anchored_steps: dict[str, timedelta] = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
    }
    if recurrence in anchored_steps:
        step = anchored_steps[recurrence]
        if anchor is None:
            # No anchor available — fall back to a plain delta from now.
            return now_utc + step
        # Anchor to the original local wall-clock time. Advance whole
        # days/weeks from the anchor until strictly after now, preserving
        # the time-of-day (and weekday for weekly).
        anchor_local = anchor.astimezone(tz)
        next_local = anchor_local
        if next_local <= now_utc.astimezone(tz):
            elapsed = now_utc.astimezone(tz) - anchor_local
            steps_to_skip = (elapsed // step) + 1
            next_local = anchor_local + step * steps_to_skip
        return next_local.astimezone(UTC)

    # Cron expression — evaluate in the user's local timezone via the canonical
    # helper (single source of cron-in-zone math + observability).
    try:
        return get_next_run_time(recurrence, now_utc, home_tz)
    except CronError:
        log.warning("tracked_todo.next_run_unrecognised", recurrence=recurrence)
        return None


async def safety_net_check_orphaned_todos(_ctx: dict[str, Any]) -> str:
    """
    Cron safety net: find scheduled tracked todos that should have run but
    were never picked up (e.g. worker was down, job was lost).

    Queries todos where:
    - scheduled_at <= now
    - completed = False
    - labels includes "gaia-tracked"
    - gaia_retry_count < MAX_RETRY_ATTEMPTS

    For each, checks whether the execution lock already exists; if not,
    re-enqueues with a random 0–60 second jitter to spread load.
    """
    now = datetime.now(UTC)

    candidates = await todo_repository.find_due_tracked_all_users(
        now=now, max_retries=MAX_RETRY_ATTEMPTS, limit=100
    )
    log.set(tracked_todo={"candidates": len(candidates)})

    pool = await RedisPoolManager.get_pool()
    re_enqueued = 0
    skipped = 0

    for doc in candidates:
        todo_id = doc.id
        lock_key = f"gaia_todo_exec:{todo_id}"

        lock_exists = await pool.exists(lock_key)
        if lock_exists:
            skipped += 1
            continue

        # Random jitter: 0–60 seconds
        jitter_seconds = random.randint(0, 60)  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
        run_at = now + timedelta(seconds=jitter_seconds)
        await enqueue_worker_job(pool, "execute_tracked_todo", todo_id, _defer_until=run_at)
        re_enqueued += 1

    log.set_ns("tracked_todo", re_enqueued=re_enqueued, skipped=skipped)
    return f"re_enqueued:{re_enqueued} skipped:{skipped}"
