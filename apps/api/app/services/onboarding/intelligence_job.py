"""Lifecycle management for the onboarding ARQ jobs.

Stores active job ids on `users.onboarding.intelligence_job_id` (the main
intelligence pipeline) and `users.onboarding.workflows_job_id` (the deferred
workflows phase of split-mode onboarding) so that re-enqueueing or resetting
the onboarding flow can abort any in-flight job instead of letting multiple
parallel pipelines emit events on the same WebSocket. Without this, repeatedly
resetting + completing onboarding fan-outs into N concurrent pipelines whose
interleaved stage events corrupt the frontend's stage cursor.
"""

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms
from bson import ObjectId

from app.constants.log_tags import LogTag
from app.constants.onboarding import (
    INTELLIGENCE_JOB_FIELD,
    INTELLIGENCE_TASK,
    WORKFLOWS_JOB_FIELD,
    WORKFLOWS_TASK,
)
from app.db.mongodb.collections import todos_collection, users_collection
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

# Each helper below is parameterized by `field` so the same logic serves both
# job slots (intelligence and workflows). The public wrappers at the bottom bind
# `field` to INTELLIGENCE_JOB_FIELD / WORKFLOWS_JOB_FIELD (app/constants/onboarding.py).


async def _get_active_job_id(user_id: str, field: str) -> str | None:
    # `field` is a dotted path ("onboarding.intelligence_job_id"); the projection
    # returns the nested doc, so strip the prefix to index into it.
    doc = await users_collection.find_one({"_id": ObjectId(user_id)}, {field: 1})
    if not doc:
        return None
    return (doc.get("onboarding") or {}).get(field.removeprefix("onboarding."))


async def _clear_active_job_id(user_id: str, field: str) -> None:
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$unset": {field: ""}},
    )


async def _set_active_job_id(user_id: str, job_id: str, field: str) -> None:
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {field: job_id}},
    )


async def _clear_active_job_id_if_matches(user_id: str, job_id: str, field: str) -> None:
    # Compare-and-clear: the `field: job_id` filter means we only unset when the
    # stored id is still OUR job. If a concurrent reset already wrote a newer id,
    # the filter misses and we leave that newer job's id untouched.
    await users_collection.update_one(
        {"_id": ObjectId(user_id), field: job_id},
        {"$unset": {field: ""}},
    )


async def clear_active_intelligence_job(user_id: str, job_id: str) -> None:
    """Compare-and-clear so a concurrent reset's newer job id is not orphaned."""
    await _clear_active_job_id_if_matches(user_id, job_id, INTELLIGENCE_JOB_FIELD)


async def clear_active_workflows_job(user_id: str, job_id: str) -> None:
    """Compare-and-clear the workflows-phase job id."""
    await _clear_active_job_id_if_matches(user_id, job_id, WORKFLOWS_JOB_FIELD)


async def _is_job_live(user_id: str, field: str) -> bool:
    job_id = await _get_active_job_id(user_id, field)
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
            job_field=field,
            error=str(e)[:200],
        )
        return False
    return status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress)


async def is_intelligence_job_live(user_id: str) -> bool:
    """Return whether the user has an intelligence ARQ job queued, deferred, or in_progress."""
    return await _is_job_live(user_id, INTELLIGENCE_JOB_FIELD)


async def is_workflows_job_live(user_id: str) -> bool:
    """Return whether the user has a workflows-phase ARQ job queued, deferred, or in_progress."""
    return await _is_job_live(user_id, WORKFLOWS_JOB_FIELD)


async def _abort_active_job(user_id: str, field: str) -> bool:
    # Signal ARQ to abort a still-running job before we enqueue a replacement,
    # so a re-submit can't leave two pipelines emitting to the same WebSocket.
    job_id = await _get_active_job_id(user_id, field)
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
            f"{LogTag.ONBOARDING} onboarding job aborted",
            user_id=user_id,
            job_id=job_id,
            job_field=field,
            prev_status=status.value,
        )

    await _clear_active_job_id(user_id, field)
    return aborted


async def abort_active_intelligence_job(user_id: str) -> bool:
    """Abort the user's in-flight intelligence job, if one exists. Returns True
    if a job was aborted. Always clears the stored job id."""
    return await _abort_active_job(user_id, INTELLIGENCE_JOB_FIELD)


async def abort_active_workflows_job(user_id: str) -> bool:
    """Abort the user's in-flight workflows-phase job, if one exists. Returns
    True if a job was aborted. Always clears the stored job id."""
    return await _abort_active_job(user_id, WORKFLOWS_JOB_FIELD)


async def _purge_stale_onboarding_todos(user_id: str) -> int:
    try:
        result = await todos_collection.delete_many({"user_id": user_id, "labels": "onboarding"})
        return result.deleted_count
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} intelligence_job failed to purge stale onboarding todos",
            user_id=user_id,
            error=str(e)[:200],
        )
        return 0


async def enqueue_intelligence_job(user_id: str) -> str | None:
    """Enqueue the intelligence pipeline, aborting any in-flight job first.
    Returns the new job id, or None if enqueue failed."""
    await abort_active_intelligence_job(user_id)
    purged = await _purge_stale_onboarding_todos(user_id)
    if purged:
        log.info(
            f"{LogTag.ONBOARDING} intelligence_job purged stale onboarding todos",
            user_id=user_id,
            purged=purged,
        )

    pool = await RedisPoolManager.get_pool()
    job = await pool.enqueue_job(INTELLIGENCE_TASK, user_id)
    if job is None:
        log.error(f"{LogTag.ONBOARDING} intelligence_job enqueue returned no job", user_id=user_id)
        return None

    await _set_active_job_id(user_id, job.job_id, INTELLIGENCE_JOB_FIELD)
    log.info(
        f"{LogTag.ONBOARDING} intelligence_job enqueued",
        user_id=user_id,
        job_id=job.job_id,
    )
    return job.job_id


async def enqueue_workflows_job(user_id: str) -> str | None:
    """Enqueue the workflows-phase job, aborting any previous one first.
    Does NOT purge onboarding todos — the early phase just created them."""
    await abort_active_workflows_job(user_id)

    pool = await RedisPoolManager.get_pool()
    job = await pool.enqueue_job(WORKFLOWS_TASK, user_id)
    if job is None:
        log.error(f"{LogTag.ONBOARDING} workflows_job enqueue returned no job", user_id=user_id)
        return None

    await _set_active_job_id(user_id, job.job_id, WORKFLOWS_JOB_FIELD)
    log.info(
        f"{LogTag.ONBOARDING} workflows_job enqueued",
        user_id=user_id,
        job_id=job.job_id,
    )
    return job.job_id
