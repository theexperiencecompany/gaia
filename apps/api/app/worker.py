from arq import cron

from app.workers.config.worker_settings import WorkerSettings
from app.workers.lifecycle import shutdown, startup
from app.workers.metrics import instrument_task
from app.workers.tasks import (
    check_inactive_users,
    cleanup_expired_reminders,
    cleanup_stuck_personalization,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_gmail_emails_to_memory,
    process_onboarding_intelligence_task,
    process_reminder,
    process_workflow_generation_task,
    prune_inactive_sessions,
    regenerate_workflow_steps,
    store_memories_batch,
    sweep_idle_sandboxes,
)
from app.workers.tasks.maintenance_sweep_tasks import maintenance_sweep_tracked_todos
from app.workers.tasks.tracked_todo_tasks import (
    execute_tracked_todo,
    safety_net_check_orphaned_todos,
)

# Wrap every task with the Prometheus histogram instrumentation so arq-worker.json
# can show real p50/p95/p99 latency per task name. Cron jobs reference the same
# wrapped functions so scheduled runs are also instrumented.
_process_reminder = instrument_task(process_reminder)
_cleanup_expired_reminders = instrument_task(cleanup_expired_reminders)
_check_inactive_users = instrument_task(check_inactive_users)
_process_workflow_generation_task = instrument_task(process_workflow_generation_task)
_execute_workflow_by_id = instrument_task(execute_workflow_by_id)
_regenerate_workflow_steps = instrument_task(regenerate_workflow_steps)
_generate_workflow_steps = instrument_task(generate_workflow_steps)
_process_gmail_emails_to_memory = instrument_task(process_gmail_emails_to_memory)
_process_onboarding_intelligence_task = instrument_task(process_onboarding_intelligence_task)
_store_memories_batch = instrument_task(store_memories_batch)
_cleanup_stuck_personalization = instrument_task(cleanup_stuck_personalization)
_sweep_idle_sandboxes = instrument_task(sweep_idle_sandboxes)
_prune_inactive_sessions = instrument_task(prune_inactive_sessions)
_execute_tracked_todo = instrument_task(execute_tracked_todo)
_safety_net_check_orphaned_todos = instrument_task(safety_net_check_orphaned_todos)
_maintenance_sweep_tracked_todos = instrument_task(maintenance_sweep_tracked_todos)

WorkerSettings.functions = [
    _process_reminder,
    _cleanup_expired_reminders,
    _check_inactive_users,
    _process_workflow_generation_task,
    _execute_workflow_by_id,
    _regenerate_workflow_steps,
    _generate_workflow_steps,
    _process_gmail_emails_to_memory,
    _process_onboarding_intelligence_task,
    _store_memories_batch,
    _cleanup_stuck_personalization,
    _sweep_idle_sandboxes,
    _prune_inactive_sessions,
    _execute_tracked_todo,
]

WorkerSettings.cron_jobs = [
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
    cron(
        _cleanup_stuck_personalization,
        minute={0, 30},  # Every 30 minutes
        second=0,
    ),
    cron(
        _sweep_idle_sandboxes,
        minute=0,  # Hourly
        second=0,
    ),
    cron(
        _prune_inactive_sessions,
        hour=3,  # Daily at 03:00 UTC
        minute=0,
        second=0,
    ),
    cron(_safety_net_check_orphaned_todos, minute={0, 30}, second=0),
    cron(
        _maintenance_sweep_tracked_todos,
        hour={0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22},
        minute=15,
        second=0,
    ),
]

WorkerSettings.on_startup = startup
WorkerSettings.on_shutdown = shutdown
