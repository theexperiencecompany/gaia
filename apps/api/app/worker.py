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
    process_personalization_task,
    process_reminder,
    process_workflow_generation_task,
    store_memories_batch,
    regenerate_workflow_steps,
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
_process_personalization_task = instrument_task(process_personalization_task)
_store_memories_batch = instrument_task(store_memories_batch)
_cleanup_stuck_personalization = instrument_task(cleanup_stuck_personalization)

WorkerSettings.functions = [
    _process_reminder,
    _cleanup_expired_reminders,
    _check_inactive_users,
    _process_workflow_generation_task,
    _execute_workflow_by_id,
    _regenerate_workflow_steps,
    _generate_workflow_steps,
    _process_gmail_emails_to_memory,
    _process_personalization_task,
    _store_memories_batch,
    _cleanup_stuck_personalization,
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
]

WorkerSettings.on_startup = startup
WorkerSettings.on_shutdown = shutdown
