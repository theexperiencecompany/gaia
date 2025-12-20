from arq import cron

from app.workers.config.worker_settings import WorkerSettings
from app.workers.lifecycle import shutdown, startup
from app.workers.tasks import (
    check_inactive_users,
    cleanup_expired_reminders,
    cleanup_stuck_personalization,
    execute_workflow_by_id,
    generate_workflow_steps,
    process_email_task,
    process_gmail_emails_to_memory,
    process_personalization_task,
    process_reminder,
    process_workflow_generation_task,
    store_memories_batch,
    regenerate_workflow_steps,
)

# Configure the worker settings with all task functions and lifecycle hooks
WorkerSettings.functions = [
    process_reminder,
    process_email_task,
    cleanup_expired_reminders,
    check_inactive_users,
    process_workflow_generation_task,
    execute_workflow_by_id,
    regenerate_workflow_steps,
    generate_workflow_steps,
    process_gmail_emails_to_memory,
    process_personalization_task,
    store_memories_batch,
    cleanup_stuck_personalization,
]

WorkerSettings.cron_jobs = [
    cron(
        cleanup_expired_reminders,
        hour=0,  # At midnight
        minute=0,
        second=0,
    ),
    cron(
        check_inactive_users,
        hour=9,  # At 9 AM
        minute=0,
        second=0,
    ),
    cron(
        cleanup_stuck_personalization,
        minute={0, 30},  # Every 30 minutes
        second=0,
    ),
]

WorkerSettings.on_startup = startup
WorkerSettings.on_shutdown = shutdown
