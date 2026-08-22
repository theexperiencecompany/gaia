from typing import cast

from arq import cron
from arq.typing import WorkerCoroutine

# The worker runs the executor agent + Composio custom tools, so it needs the
# same monkey-patches as the API process (main.py). Without this, custom tools
# 500 with "Missing user_id in auth_credentials" because the CustomTool
# user_id-injection patch never loads in this process.
import app.patches  # noqa: F401 -- applies monkeypatches on import; must run before the patched SDKs are used
from app.workers.config.worker_settings import WorkerSettings
from app.workers.lifecycle import shutdown, startup
from app.workers.task_envelope import arq_task
from app.workers.tasks import (
    backfill_active_users,
    backfill_user_memories,
    check_inactive_users,
    cleanup_expired_reminders,
    cleanup_stuck_personalization,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_gmail_emails_to_memory,
    process_onboarding_intelligence_task,
    process_onboarding_workflows_task,
    process_reminder,
    process_workflow_generation_task,
    promote_usage_badges,
    prune_checkpoint_versions,
    prune_inactive_sessions,
    regenerate_workflow_steps,
    run_nurture_sequence_task,
    sweep_abandoned_imessage_registrations,
    sweep_idle_sandboxes,
)
from app.workers.tasks.hil_sweep_tasks import sweep_hil_approvals
from app.workers.tasks.maintenance_sweep_tasks import maintenance_sweep_tracked_todos
from app.workers.tasks.scheduler_recovery_tasks import rescan_pending_scheduled_tasks
from app.workers.tasks.tracked_todo_tasks import (
    execute_tracked_todo,
    safety_net_check_orphaned_todos,
)
from app.workers.tasks.workflow_dormancy_tasks import sweep_dormant_user_workflows

# Wrap every task in the standard envelope (wide event + Prometheus histogram)
# so arq-worker.json can show real p50/p95/p99 latency per task name and every
# run emits one correlated worker_task event. Cron jobs reference the same
# wrapped functions so scheduled runs get both too.
_process_reminder = arq_task(process_reminder)
_cleanup_expired_reminders = arq_task(cleanup_expired_reminders)
_sweep_hil_approvals = arq_task(sweep_hil_approvals)
_check_inactive_users = arq_task(check_inactive_users)
_process_workflow_generation_task = arq_task(process_workflow_generation_task)
_execute_workflow_by_id = arq_task(execute_workflow_by_id)
_regenerate_workflow_steps = arq_task(regenerate_workflow_steps)
_generate_workflow_steps = arq_task(generate_workflow_steps)
_process_gmail_emails_to_memory = arq_task(process_gmail_emails_to_memory)
_process_onboarding_intelligence_task = arq_task(process_onboarding_intelligence_task)
_process_onboarding_workflows_task = arq_task(process_onboarding_workflows_task)
_cleanup_stuck_personalization = arq_task(cleanup_stuck_personalization)
_backfill_active_users = arq_task(backfill_active_users)
_backfill_user_memories = arq_task(backfill_user_memories)
_sweep_idle_sandboxes = arq_task(sweep_idle_sandboxes)
_prune_inactive_sessions = arq_task(prune_inactive_sessions)
_prune_checkpoint_versions = arq_task(prune_checkpoint_versions)
_execute_tracked_todo = arq_task(execute_tracked_todo)
_safety_net_check_orphaned_todos = arq_task(safety_net_check_orphaned_todos)
_maintenance_sweep_tracked_todos = arq_task(maintenance_sweep_tracked_todos)
_rescan_pending_scheduled_tasks = arq_task(rescan_pending_scheduled_tasks)
_run_nurture_sequence_task = arq_task(run_nurture_sequence_task)
_promote_usage_badges = arq_task(promote_usage_badges)
_sweep_dormant_user_workflows = arq_task(sweep_dormant_user_workflows)
_sweep_abandoned_imessage_registrations = arq_task(sweep_abandoned_imessage_registrations)

WorkerSettings.functions = [
    _sweep_hil_approvals,
    _process_reminder,
    _cleanup_expired_reminders,
    _check_inactive_users,
    _run_nurture_sequence_task,
    _process_workflow_generation_task,
    _execute_workflow_by_id,
    _regenerate_workflow_steps,
    _generate_workflow_steps,
    _process_gmail_emails_to_memory,
    _process_onboarding_intelligence_task,
    _process_onboarding_workflows_task,
    _cleanup_stuck_personalization,
    _sweep_idle_sandboxes,
    _prune_inactive_sessions,
    _prune_checkpoint_versions,
    _execute_tracked_todo,
    _backfill_active_users,
    _backfill_user_memories,
    _promote_usage_badges,
    _sweep_dormant_user_workflows,
    _sweep_abandoned_imessage_registrations,
]

WorkerSettings.cron_jobs = [
    cron(
        # Every minute: HIL approvals must expire promptly — a stale pending
        # approval hijacks the conversation's next messages and holds the
        # executor's claim on the thread.
        _sweep_hil_approvals,
        second=0,
    ),
    cron(
        _cleanup_expired_reminders,
        hour=0,  # At midnight
        minute=0,
        second=0,
    ),
    cron(
        _check_inactive_users,
        hour=9,  # At 9 AM
        minute=0,
        second=0,
    ),
    # Hourly so every user is evaluated at 9am in their own timezone; the
    # engine itself filters to users whose local hour matches.
    cron(
        _run_nurture_sequence_task,
        minute=10,
        second=0,
    ),
    cron(
        _cleanup_stuck_personalization,
        minute={0, 30},  # Every 30 minutes
        second=0,
    ),
    cron(
        cast(WorkerCoroutine, _sweep_idle_sandboxes),
        minute=0,  # Hourly
        second=0,
    ),
    # Hourly, off the top of the hour so it does not pile onto the other sweeps.
    # A registration abandoned mid-connect holds a shared-pool seat until this runs.
    cron(
        cast(WorkerCoroutine, _sweep_abandoned_imessage_registrations),
        minute=20,
        second=0,
    ),
    cron(
        cast(WorkerCoroutine, _prune_inactive_sessions),
        hour=3,  # Daily at 03:00 UTC
        minute=0,
        second=0,
    ),
    cron(
        cast(WorkerCoroutine, _prune_checkpoint_versions),
        hour=4,  # Daily at 04:30 UTC (low traffic, after session prune)
        minute=30,
        second=0,
    ),
    cron(cast(WorkerCoroutine, _safety_net_check_orphaned_todos), minute={0, 30}, second=0),
    cron(
        cast(WorkerCoroutine, _maintenance_sweep_tracked_todos),
        hour={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22},
        minute=15,
        second=0,
    ),
    # Recovery safety net: re-enqueue due scheduled tasks whose ARQ job was lost
    # (Redis eviction/flush). Idempotent via the deterministic _job_id.
    cron(cast(WorkerCoroutine, _rescan_pending_scheduled_tasks), minute={0, 30}, second=0),
    # Seed long-term memory for recently-active pre-launch users (capped per
    # run; the marker makes it resume and pick up returning users).
    cron(
        _backfill_active_users,
        hour=4,  # Daily at 04:00 UTC (low traffic)
        minute=0,
        second=0,
    ),
    # First-time badge-tier promotions (monotonic + idempotent, so a missed or
    # doubled run is harmless). After the day's rollups have settled.
    cron(
        cast(WorkerCoroutine, _promote_usage_badges),
        hour=5,  # Daily at 05:00 UTC
        minute=0,
        second=0,
    ),
    # Pause workflows owned by users who stopped using GAIA — they otherwise fire
    # (and bill) forever. Undone on the user's next login, not by this sweep.
    cron(
        cast(WorkerCoroutine, _sweep_dormant_user_workflows),
        hour=6,  # Daily at 06:00 UTC
        minute=0,
        second=0,
    ),
]

WorkerSettings.on_startup = startup
WorkerSettings.on_shutdown = shutdown
