"""Unified workflow queue service for background job management."""

from datetime import datetime
import hashlib
import json

from app.constants.log_tags import LogTag
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


class WorkflowQueueService:
    """Unified service for managing all workflow job queues."""

    @staticmethod
    async def queue_workflow_generation(workflow_id: str, user_id: str) -> bool:
        """Queue workflow generation as a background task."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await enqueue_worker_job(pool, "generate_workflow_steps", workflow_id, user_id)

            if job:
                log.set(workflow={"id": workflow_id, "status": "generation_queued"})
                log.info(
                    f"{LogTag.WORKFLOW} Queued workflow generation for with job ID",
                    workflow_id=workflow_id,
                    job_id=job.job_id,
                )
                return True
            log.error(
                f"{LogTag.WORKFLOW} Failed to queue workflow generation for",
                workflow_id=workflow_id,
                user_id=user_id,
            )
            return False

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error queuing workflow generation for",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return False

    @staticmethod
    async def queue_workflow_execution(
        workflow_id: str,
        user_id: str,
        context: dict[str, object] | None = None,
        *,
        defer_until: datetime | None = None,
    ) -> bool:
        """Queue workflow execution as a background task, now or at defer_until.

        Uses a deterministic _job_id hashed from workflow + user + context so
        a duplicate enqueue collapses to one run while queued/executing (ARQ
        rejects a same-id job). keep_result=0 frees the id once the run
        finishes, so a later legitimate re-run is never blocked.
        """
        try:
            pool = await RedisPoolManager.get_pool()

            dedup_payload = json.dumps(
                {"workflow_id": workflow_id, "user_id": user_id, "context": context or {}},
                sort_keys=True,
                default=str,
            )
            job_id = (
                "execute_workflow_by_id:" + hashlib.sha256(dedup_payload.encode()).hexdigest()[:32]
            )

            job = await enqueue_worker_job(
                pool,
                "execute_workflow_by_id",
                workflow_id,
                context or {},
                _job_id=job_id,
                _defer_until=defer_until,
            )

            if job is None:
                # A job with this id is already queued or running — the duplicate
                # enqueue was deduped. That's the intended outcome, not a failure.
                log.info(
                    f"{LogTag.WORKFLOW} Workflow execution already queued; deduped duplicate enqueue",
                    workflow_id=workflow_id,
                    job_id=job_id,
                )
                return True

            log.set(
                workflow={"id": workflow_id, "status": "execution_queued"},
                arq_job_id=job.job_id,
                queue_mode="deferred" if defer_until else "immediate",
                defer_until=defer_until.isoformat() if defer_until else None,
            )
            log.info(
                f"{LogTag.WORKFLOW} Queued workflow execution for with job ID",
                workflow_id=workflow_id,
                job_id=job.job_id,
            )
            return True

        except Exception as e:
            log.error(
                f"{LogTag.WORKFLOW} Error queuing workflow execution for",
                workflow_id=workflow_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )
            return False
