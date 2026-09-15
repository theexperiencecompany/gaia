"""Enqueue side of signup's outbound ESP deliveries.

The job itself lives in ``app/workers/tasks/signup_email_tasks.py``; this is the
one place its name and its per-user job id are derived, because the two callers
must agree on both. Signup enqueues here, and the recovery sweep re-enqueues
here for anyone whose delivery stamps are still missing — if their ids ever
diverged, a sweep overlapping a still-queued signup job would send the welcome
email twice.

It sits on the service side rather than beside the task for the same reason
``onboarding/intelligence_job`` does: importing ``app.workers.tasks`` from
``oauth_service`` runs that package's ``__init__``, which reaches back into the
OAuth service through the nurture tasks and closes an import cycle.
"""

from arq.connections import ArqRedis
from arq.jobs import Job

from app.constants.email import SIGNUP_EMAIL_JOB_ID_TEMPLATE, SIGNUP_EMAIL_TASK
from app.workers.queue import enqueue_worker_job


def signup_email_job_id(user_id: str) -> str:
    """One job id per user: the id is what makes a duplicate enqueue a no-op."""
    return SIGNUP_EMAIL_JOB_ID_TEMPLATE.format(user_id=user_id)


async def enqueue_signup_emails(pool: ArqRedis, user_id: str) -> Job | None:
    """Queue one user's signup deliveries, deduped against an existing job.

    Only the user id is queued: the stored row is the single source of the
    address and the name, so a sweep re-enqueue cannot disagree with signup
    about either. Returns ``None`` when ARQ deduped it, like ``enqueue_worker_job``.
    """
    return await enqueue_worker_job(
        pool, SIGNUP_EMAIL_TASK, user_id, _job_id=signup_email_job_id(user_id)
    )
