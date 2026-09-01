"""Lifecycle management for the Gmail personalization ARQ job.

Stores the active job id on `users.onboarding.intelligence_job_id` so that
re-enqueueing or resetting can abort an in-flight job instead of letting
multiple parallel pipelines emit events on the same WebSocket. Without this,
repeatedly reconnecting Gmail fan-outs into N concurrent pipelines whose
interleaved stage events corrupt the frontend's stage cursor.
"""

from typing import Any

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms

from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    GMAIL_PERSONALIZATION_MARKER,
    INTELLIGENCE_JOB_FIELD,
    INTELLIGENCE_TASK,
    LEGACY_PERSONALIZATION_MARKER,
)
from app.db.repositories.users import user_repository
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


def personalization_already_ran(onboarding: dict[str, Any]) -> bool:
    """Whether the Gmail personalization pipeline has already run for this user.

    ``onboarding`` is the raw ``UserDocument.onboarding`` subdocument, which is
    schemaless by design (``extra="allow"``), so this reads it by key. Users who
    completed the pre-relocation onboarding carry holo-card fields but no
    marker; the legacy field stands in for them.
    """
    return bool(
        onboarding.get(GMAIL_PERSONALIZATION_MARKER)
        or onboarding.get(LEGACY_PERSONALIZATION_MARKER)
    )


async def _get_active_job_id(user_id: str) -> str | None:
    user = await user_repository.get(user_id)
    if user is None:
        return None
    # INTELLIGENCE_JOB_FIELD is the dotted path; index the subdocument with its tail.
    value = (user.onboarding or {}).get(INTELLIGENCE_JOB_FIELD.removeprefix("onboarding."))
    return value if isinstance(value, str) else None


async def clear_active_intelligence_job(user_id: str, job_id: str) -> None:
    """Compare-and-clear so a concurrent reset's newer job id is not orphaned.

    Only unsets when the stored id is still OUR job; if a concurrent reset
    already wrote a newer id, the guard misses and that id is left untouched.
    """
    await user_repository.clear_active_job_if_matches(user_id, INTELLIGENCE_JOB_FIELD, job_id)


async def is_intelligence_job_live(user_id: str) -> bool:
    """Return whether the user has a personalization ARQ job queued, deferred, or in_progress."""
    job_id = await _get_active_job_id(user_id)
    if not job_id:
        return False
    pool = await RedisPoolManager.get_pool()
    job = Job(job_id, redis=pool)
    try:
        status = await job.status()
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} job status check failed, treating as dead",
            user_id=user_id,
            job_id=job_id,
            error=str(e)[:200],
        )
        return False
    return status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress)


async def abort_active_intelligence_job(user_id: str) -> bool:
    """Abort the user's in-flight personalization job, if one exists. Returns
    True if a job was aborted. Always clears the stored job id."""
    job_id = await _get_active_job_id(user_id)
    if not job_id:
        return False

    pool = await RedisPoolManager.get_pool()
    job = Job(job_id, redis=pool)
    status = await job.status()
    aborted = False
    if status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress):
        # ARQ watches this sorted set; adding the job id requests cooperative abort.
        await pool.zadd(abort_jobs_ss, {job_id: timestamp_ms()})
        aborted = True
        log.info(
            f"{LogTag.ONBOARDING} personalization job aborted",
            user_id=user_id,
            job_id=job_id,
            prev_status=status.value,
        )

    await user_repository.clear_active_job(user_id, INTELLIGENCE_JOB_FIELD)
    return aborted


async def enqueue_gmail_personalization(user_id: str) -> str | None:
    """Enqueue the Gmail personalization pipeline, aborting any in-flight job first.

    Returns the new job id, or None when the pipeline has already run for this
    user (a reconnect must not redo it) or the enqueue failed.
    """
    user = await user_repository.get(user_id)
    if user is None:
        log.warning(
            f"{LogTag.ONBOARDING} personalization enqueue skipped — user not found",
            user_id=user_id,
        )
        return None
    if personalization_already_ran(user.onboarding or {}):
        log.info(
            f"{LogTag.ONBOARDING} personalization enqueue skipped — already ran",
            user_id=user_id,
        )
        return None

    await abort_active_intelligence_job(user_id)

    pool = await RedisPoolManager.get_pool()
    job = await enqueue_worker_job(pool, INTELLIGENCE_TASK, user_id)
    if job is None:
        log.error(
            f"{LogTag.ONBOARDING} personalization enqueue returned no job", user_id=user_id
        )
        return None

    await user_repository.set_active_job(user_id, INTELLIGENCE_JOB_FIELD, job.job_id)
    log.info(
        f"{LogTag.ONBOARDING} personalization job enqueued",
        user_id=user_id,
        job_id=job.job_id,
    )
    return job.job_id
