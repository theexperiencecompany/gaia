"""Lifecycle of the Gmail personalization ARQ job.

The job id is a function of the user, so ARQ's own enqueue dedup is the
once-at-a-time guarantee: while a run for the user is queued or in flight, a
second enqueue (a Gmail reconnect, a racing request, the stuck-user sweep) is
refused by Redis atomically and the live run keeps going. Nothing is stored on
the user document and nothing is aborted to make room; two pipelines can never
emit stage events onto the same WebSocket because the second never starts.
"""

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms

from app.constants.log_tags import LogTag
from app.constants.onboarding import INTELLIGENCE_TASK
from app.db.repositories.users import user_repository
from app.models.user_models import OnboardingSubdocument
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log

LIVE_STATUSES = frozenset({JobStatus.queued, JobStatus.deferred, JobStatus.in_progress})


def personalization_job_id(user_id: str) -> str:
    """One job id per user: the id is the claim."""
    return f"{INTELLIGENCE_TASK}:{user_id}"


def personalization_already_ran(onboarding: OnboardingSubdocument) -> bool:
    """Whether the Gmail personalization pipeline has already run for this user.

    Users who completed the pre-relocation onboarding carry holo-card fields but
    no marker; ``house`` stands in as the marker for them.
    """
    return bool(onboarding.gmail_personalization_at or onboarding.house)


async def _job_status(user_id: str) -> JobStatus | None:
    pool = await RedisPoolManager.get_pool()
    job = Job(personalization_job_id(user_id), redis=pool)
    try:
        return await job.status()
    except Exception as e:
        log.warning(
            f"{LogTag.ONBOARDING} job status check failed, treating as dead",
            user_id=user_id,
            job_id=job.job_id,
            error=str(e)[:200],
        )
        return None


async def is_intelligence_job_live(user_id: str) -> bool:
    """Whether the user's personalization job is queued, deferred, or in progress."""
    return await _job_status(user_id) in LIVE_STATUSES


async def abort_active_intelligence_job(user_id: str) -> bool:
    """Abort the user's in-flight personalization job, if one exists (an
    onboarding reset must not let it finish writing the card it is tearing
    down). Returns True if a job was aborted."""
    status = await _job_status(user_id)
    if status not in LIVE_STATUSES:
        return False
    pool = await RedisPoolManager.get_pool()
    job_id = personalization_job_id(user_id)
    # ARQ watches this sorted set; adding the job id requests cooperative abort.
    await pool.zadd(abort_jobs_ss, {job_id: timestamp_ms()})
    log.info(
        f"{LogTag.ONBOARDING} personalization job aborted",
        user_id=user_id,
        job_id=job_id,
        prev_status=status.value if status else None,
    )
    return True


async def enqueue_gmail_personalization(user_id: str) -> str | None:
    """Enqueue the Gmail personalization pipeline once per user.

    Returns the job id, which is also the id of a run already queued or in
    flight (the caller's connect is served by that run). Returns None when the
    pipeline has already run for this user (a reconnect must not redo it) or
    the enqueue failed.
    """
    user = await user_repository.get(user_id)
    if user is None:
        log.warning(
            f"{LogTag.ONBOARDING} personalization enqueue skipped — user not found",
            user_id=user_id,
        )
        return None
    if personalization_already_ran(user.onboarding or OnboardingSubdocument()):
        log.info(
            f"{LogTag.ONBOARDING} personalization enqueue skipped — already ran",
            user_id=user_id,
        )
        return None

    job_id = personalization_job_id(user_id)
    pool = await RedisPoolManager.get_pool()
    job = await enqueue_worker_job(pool, INTELLIGENCE_TASK, user_id, _job_id=job_id)
    if job is not None:
        log.info(
            f"{LogTag.ONBOARDING} personalization job enqueued",
            user_id=user_id,
            job_id=job_id,
        )
        return job_id
    if await is_intelligence_job_live(user_id):
        log.info(
            f"{LogTag.ONBOARDING} personalization already running, reconnect joins it",
            user_id=user_id,
            job_id=job_id,
        )
        return job_id
    log.error(f"{LogTag.ONBOARDING} personalization enqueue returned no job", user_id=user_id)
    return None
