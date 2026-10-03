"""ARQ tasks that maintain per-user E2B sandboxes + JuiceFS metadata.

Currently:
- sweep_idle_sandboxes: hourly. Marks sandboxes whose last_used_at is older
  than the eviction threshold as dead and drops them from the in-process pool
  so the next request creates a fresh one. The underlying E2B sandbox is left
  to E2B's own paused-TTL to reclaim (default 30 days), which keeps the FS
  available if the user comes back inside the window. AGENT_LAB users are
  exempt while the flag is on (their keep-warm refresh keeps last_used_at
  fresh anyway; the exemption covers a missed cron run).
- refresh_lab_sandboxes: every 30 minutes. Re-acquires flagged users'
  sandboxes so the E2B kill timer never lapses, which also re-stages the
  sandbox bridge token after a pause/resume cycle. Runs older than
  SANDBOX_LAB_MAX_RUN_SECONDS are skipped (idle-pause reclaims them) with one
  notification per cap window; dead-run marking lives in the future
  supervisor tick (see TODO-S1-supervisor-tick), not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from arq.connections import ArqRedis
from e2b import AsyncSandbox

from app.agents.tools.agent_lab_tools import (
    LAB_RUN_DIR_PREFIX,
    LAB_SEED_TIMEOUT_SECONDS,
    parse_lab_routing_ref,
)
from app.config.settings import settings
from app.constants.execute import SANDBOX_LAB_MAX_RUN_SECONDS
from app.constants.log_tags import LogTag
from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.db.repositories.todos import todo_repository
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.todo_models import TodoDocument
from app.services.agent_lab.sandbox_setup import (
    build_seed_command,
    lab_events_url,
    mint_lab_hooks_token,
)
from app.services.feature_flags import is_agent_lab_enabled
from app.services.notification_service import notification_service
from app.services.sandbox import acquire_sandbox, mark_sandbox_dead
from shared.py.wide_events import SandboxContext, log


async def sweep_idle_sandboxes(_ctx: dict[str, Any]) -> str:
    """Evict sandboxes whose last_used_at is older than the eviction window."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.E2B_SANDBOX_EVICT_DAYS)
    idle_user_ids = await e2b_sandbox_repository.find_idle_user_ids(cutoff=cutoff)
    evicted = 0
    skipped_lab = 0
    for user_id in idle_user_ids:
        try:
            if await is_agent_lab_enabled(user_id):
                skipped_lab += 1
                continue
            await mark_sandbox_dead(user_id)
            evicted += 1
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} failed to mark sandbox dead",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    log.set(sandbox=SandboxContext(operation="sweep", evicted_count=evicted))
    log.info(
        f"{LogTag.SANDBOX} sweep evicted idle sandboxes",
        evicted_count=evicted,
        skipped_lab_count=skipped_lab,
    )
    return f"Evicted {evicted} idle sandboxes (cutoff={cutoff.isoformat()})"


async def refresh_lab_sandboxes(ctx: dict[str, Any]) -> str:
    """Re-acquire flagged users' sandboxes so the E2B kill timer never lapses."""
    user_ids = await e2b_sandbox_repository.find_live_user_ids()
    refreshed = 0
    capped = 0
    for user_id in user_ids:
        try:
            if not await is_agent_lab_enabled(user_id):
                continue
            lab_todos = await _lab_run_todos(user_id)
            past_cap, capped_todo_ids = _lab_cap_status(lab_todos)
            if past_cap:
                capped += 1
                log.info(
                    f"{LogTag.SANDBOX} lab run past cap; leaving sandbox to idle-pause",
                    user_id=user_id,
                    capped_todo_ids=capped_todo_ids,
                )
                await _notify_lab_cap_hit(ctx, user_id, capped_todo_ids)
                continue
            # Re-acquire refreshes the kill timer (connect carries a full
            # lifetime), touches last_used_at, and re-stages the bridge token.
            # The hooks token outlives nothing here: it is 6h against the 12h
            # cap, so a refreshed run also gets a fresh token re-seeded into
            # each of its workdirs (same candidate scan the cap uses).
            async with acquire_sandbox(user_id) as sbx:
                await _reseed_lab_tokens(user_id, sbx, lab_todos)
            refreshed += 1
        except Exception as e:
            # TODO-S1-supervisor-tick: this catch is the whole miss policy today —
            # a single failed re-acquire logs and moves on, with no todo touched.
            # The supervisor tick must add Redis consecutive-miss counting (K=3)
            # here and, on the Kth miss, mark each lab-run todo FAILED
            # (add_labels FAILED_LABEL + record_activity) and deliver its last
            # stored tail. Do NOT reuse record_lab_event for that: it overwrites
            # the tail with the new event instead of delivering the stored one —
            # deliver via deliver_result_to_platforms, the same call the wake
            # path (_wake_or_quiet) uses, reading the tail out of log_content.
            log.warning(
                f"{LogTag.SANDBOX} failed to refresh lab sandbox",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    log.set(sandbox=SandboxContext(operation="lab_refresh", evicted_count=refreshed))
    log.info(
        f"{LogTag.SANDBOX} refreshed lab sandboxes",
        refreshed_count=refreshed,
        capped_count=capped,
    )
    return f"Refreshed {refreshed} lab sandboxes, skipped {capped} past cap"


# How many of a user's tracked todos to scan for lab-run candidates per tick.
# list_active_tracked returns most-recently-updated first and a silent/wedged
# lab run's todo goes stale, so stale lab todos sort last: the scan must cover
# a deep tracked backlog or a capped run hides past the cutoff and refreshes
# forever. One bounded query; a miss fails open (keep refreshing), never caps.
_LAB_RUN_TODO_SCAN_LIMIT = 200


def _lab_cap_notified_key(user_id: str) -> str:
    """Redis key throttling the cap-hit notification to one per cap window."""
    return f"lab:cap_notified:{user_id}"


def _lab_run_started_at(todo: TodoDocument) -> datetime | None:
    """Best-effort run-start proxy: the todo's own write clock.

    No lab_run_started_at field exists on the todo — the receiver resolves
    run → todo via find_by_reference on `references` — so age is derived from
    updated_at (lab_start records the run id on the todo, and every lab event
    overwrites its log tail, both stamping updated_at), falling back to
    created_at. A chatty run therefore slides its cap; accepted, since the cap
    bounds forgotten/wedged runs, not active ones. Missing stamps fail open
    (None = keep refreshing) rather than stranding a live run.
    """
    stamp = todo.updated_at or todo.created_at
    if stamp is None:
        return None
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=UTC)


def _lab_run_ids(references: list[str]) -> list[str]:
    """Run ids with a routing entry, in reference order, deduplicated.

    Only ``lab:<run_id>:<cli_session_id>`` entries (written by lab_start via
    parse_lab_routing_ref's shape) mark a lab run. Bare ids and institutional-
    memory links are ignored: an old unrelated todo must never read as a
    capped run or steer a token re-seed.
    """
    seen: set[str] = set()
    run_ids: list[str] = []
    for entry in references:
        parsed = parse_lab_routing_ref(entry)
        if parsed is None:
            continue
        run_id, _ = parsed
        if run_id not in seen:
            seen.add(run_id)
            run_ids.append(run_id)
    return run_ids


async def _lab_run_todos(user_id: str) -> list[TodoDocument]:
    """Active tracked todos actually carrying a lab run (routing entry present)."""
    todos = await todo_repository.list_active_tracked(user_id, limit=_LAB_RUN_TODO_SCAN_LIMIT)
    return [todo for todo in todos if _lab_run_ids(todo.references)]


def _lab_cap_status(lab_todos: list[TodoDocument]) -> tuple[bool, list[str]]:
    """Whether every lab-run candidate todo is older than the cap.

    `references` also carries non-lab institutional-memory links, but those
    never reach here — _lab_run_todos already filtered to routing entries —
    so all-old means every live run has been silent for 12h and genuinely
    looks dead. No candidates (or any fresh one) means keep refreshing.
    """
    if not lab_todos:
        return False, []
    now = datetime.now(UTC)
    capped_ids = [
        todo.id
        for todo in lab_todos
        if (started := _lab_run_started_at(todo)) is not None
        and (now - started).total_seconds() > SANDBOX_LAB_MAX_RUN_SECONDS
    ]
    if len(capped_ids) != len(lab_todos):
        return False, []
    return True, capped_ids


async def _lab_runs_past_cap(user_id: str) -> tuple[bool, list[str]]:
    """Whether every lab-run candidate todo for user_id is older than the cap."""
    return _lab_cap_status(await _lab_run_todos(user_id))


async def _reseed_lab_tokens(user_id: str, sbx: AsyncSandbox, lab_todos: list[TodoDocument]) -> None:
    """Stage a fresh hooks token into each active lab run's workdir.

    The hooks token lives 6h against the 12h run cap, so a refreshed run would
    otherwise go deaf halfway through its second half. Re-runs the canonical
    seeder per run (idempotent by construction); one run's failure costs a
    warning line, never the tick or its sibling runs.
    """
    if not lab_todos:
        return
    try:
        events_url = lab_events_url()
    except Exception as e:
        log.warning(
            f"{LogTag.SANDBOX} lab token re-seed skipped: events URL unconfigured",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return
    for todo in lab_todos:
        for run_id in _lab_run_ids(todo.references):
            try:
                token = mint_lab_hooks_token(user_id, run_id)
                seed = build_seed_command(
                    events_url, token, run_id, f"{LAB_RUN_DIR_PREFIX}/{run_id}"
                )
                await sbx.commands.run(seed, timeout=LAB_SEED_TIMEOUT_SECONDS)
            except Exception as e:
                log.warning(
                    f"{LogTag.SANDBOX} lab token re-seed failed; run keeps its aging token",
                    user_id=user_id,
                    todo_id=todo.id,
                    run_id=run_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )


async def _notify_lab_cap_hit(ctx: dict[str, Any], user_id: str, todo_ids: list[str]) -> None:
    """One in-app notification that keep-warm stopped for a capped run.

    Best-effort mirror of the tracked-todo failure notify: delivery failure
    costs a warning line, never the tick. Redis throttles to one notification
    per cap window; a bare ctx (unit tests) has no pool and notifies outright.
    """
    pool = cast(ArqRedis | None, ctx.get("redis"))
    if pool is not None:
        try:
            if await pool.exists(_lab_cap_notified_key(user_id)):
                return
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} lab cap dedup check failed; notifying anyway",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
    cap_hours = SANDBOX_LAB_MAX_RUN_SECONDS // 3600
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.WARNING,
                content=NotificationContent(
                    title=f"Agent lab run hit the {cap_hours}-hour cap",
                    body=(
                        f"GAIA stopped keeping its sandbox warm after {cap_hours} hours, "
                        "so the sandbox will pause when idle. Start a fresh run to continue."
                    ),
                ),
                metadata={
                    "cap_seconds": SANDBOX_LAB_MAX_RUN_SECONDS,
                    "todo_ids": todo_ids,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(
            f"{LogTag.SANDBOX} lab cap notification failed",
            user_id=user_id,
            error_type=type(notify_exc).__name__,
            error=str(notify_exc),
        )
        return
    if pool is not None:
        try:
            await pool.set(_lab_cap_notified_key(user_id), "1", ex=SANDBOX_LAB_MAX_RUN_SECONDS)
        except Exception as e:
            log.warning(
                f"{LogTag.SANDBOX} lab cap dedup stamp failed",
                user_id=user_id,
                error_type=type(e).__name__,
                error=str(e),
            )
