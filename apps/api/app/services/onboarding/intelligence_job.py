"""Lifecycle management for the onboarding intelligence ARQ job.

Stores the active job id on `users.onboarding.intelligence_job_id` so that
re-enqueueing or resetting the onboarding flow can abort any in-flight job
instead of letting multiple parallel pipelines emit events on the same
WebSocket. Without this, repeatedly resetting + completing onboarding
fan-outs into N concurrent pipelines whose interleaved stage events corrupt
the frontend's stage cursor.
"""

from typing import Optional

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms
from bson import ObjectId
from shared.py.wide_events import log

from app.db.mongodb.collections import todos_collection, users_collection
from app.utils.redis_utils import RedisPoolManager


_INTELLIGENCE_TASK = "process_onboarding_intelligence_task"


async def _get_active_job_id(user_id: str) -> Optional[str]:
    doc = await users_collection.find_one(
        {"_id": ObjectId(user_id)},
        {"onboarding.intelligence_job_id": 1},
    )
    if not doc:
        return None
    return (doc.get("onboarding") or {}).get("intelligence_job_id")


async def _clear_active_job_id(user_id: str) -> None:
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$unset": {"onboarding.intelligence_job_id": ""}},
    )


async def clear_active_intelligence_job(user_id: str, job_id: str) -> None:
    """Clear the stored active job id, but only if it still points at `job_id`
    (compare-and-clear so a concurrent reset's newer job id is not orphaned)."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id), "onboarding.intelligence_job_id": job_id},
        {"$unset": {"onboarding.intelligence_job_id": ""}},
    )


async def _set_active_job_id(user_id: str, job_id: str) -> None:
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.intelligence_job_id": job_id}},
    )


async def is_intelligence_job_live(user_id: str) -> bool:
    """Return True iff the user has an ARQ job queued, deferred, or in_progress."""
    job_id = await _get_active_job_id(user_id)
    if not job_id:
        return False
    pool = await RedisPoolManager.get_pool()
    job = Job(job_id, redis=pool)
    try:
        status = await job.status()
    except Exception as e:
        log.warning(
            "[intelligence_job] status check failed, treating as dead",
            user_id=user_id,
            job_id=job_id,
            error=str(e)[:200],
        )
        return False
    return status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress)


async def abort_active_intelligence_job(user_id: str) -> bool:
    """Abort the user's in-flight intelligence job, if one exists. Returns True
    iff a job was aborted. Always clears the stored job id."""
    job_id = await _get_active_job_id(user_id)
    if not job_id:
        return False

    pool = await RedisPoolManager.get_pool()
    job = Job(job_id, redis=pool)
    status = await job.status()
    aborted = False
    if status in (JobStatus.queued, JobStatus.deferred, JobStatus.in_progress):
        await pool.zadd(abort_jobs_ss, {job_id: timestamp_ms()})
        aborted = True
        log.info(
            "[intelligence_job] aborted",
            user_id=user_id,
            job_id=job_id,
            prev_status=status.value,
        )

    await _clear_active_job_id(user_id)
    return aborted


async def _purge_stale_onboarding_todos(user_id: str) -> int:
    try:
        result = await todos_collection.delete_many(
            {"user_id": user_id, "labels": "onboarding"}
        )
        return result.deleted_count
    except Exception as e:
        log.warning(
            "[intelligence_job] failed to purge stale onboarding todos",
            user_id=user_id,
            error=str(e)[:200],
        )
        return 0


async def enqueue_intelligence_job(user_id: str) -> Optional[str]:
    """Enqueue the intelligence pipeline, aborting any in-flight job first.
    Returns the new job id, or None if enqueue failed."""
    await abort_active_intelligence_job(user_id)
    purged = await _purge_stale_onboarding_todos(user_id)
    if purged:
        log.info(
            "[intelligence_job] purged stale onboarding todos",
            user_id=user_id,
            purged=purged,
        )

    pool = await RedisPoolManager.get_pool()
    job = await pool.enqueue_job(_INTELLIGENCE_TASK, user_id)
    if job is None:
        log.error("[intelligence_job] enqueue returned no job", user_id=user_id)
        return None

    await _set_active_job_id(user_id, job.job_id)
    log.info(
        "[intelligence_job] enqueued",
        user_id=user_id,
        job_id=job.job_id,
    )
    return job.job_id
