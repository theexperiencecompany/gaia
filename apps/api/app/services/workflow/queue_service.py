"""Unified workflow queue service for background job management."""

import hashlib
import json

from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log


class WorkflowQueueService:
    """Unified service for managing all workflow job queues."""

    @staticmethod
    async def queue_workflow_generation(workflow_id: str, user_id: str) -> bool:
        """Queue workflow generation as a background task."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job("generate_workflow_steps", workflow_id, user_id)

            if job:
                log.set(workflow={"id": workflow_id, "status": "generation_queued"})
                log.info(f"Queued workflow generation for {workflow_id} with job ID {job.job_id}")
                return True
            log.error(f"Failed to queue workflow generation for {workflow_id}")
            return False

        except Exception as e:
            log.error(f"Error queuing workflow generation for {workflow_id}: {e!s}")
            return False

    @staticmethod
    async def queue_workflow_execution(
        workflow_id: str, user_id: str, context: dict | None = None
    ) -> bool:
        """Queue workflow execution as a background task.

        Uses a deterministic ``_job_id`` hashed from workflow + user + context so
        a duplicate enqueue collapses to one run while queued/executing (ARQ
        rejects a same-id job). ``keep_result=0`` frees the id once the run
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

            job = await pool.enqueue_job(
                "execute_workflow_by_id", workflow_id, context or {}, _job_id=job_id
            )

            if job is None:
                # A job with this id is already queued or running — the duplicate
                # enqueue was deduped. That's the intended outcome, not a failure.
                log.info(
                    f"Workflow execution already queued for {workflow_id}; "
                    f"deduped duplicate enqueue (job ID {job_id})"
                )
                return True

            log.set(
                workflow={"id": workflow_id, "status": "execution_queued"},
                arq_job_id=job.job_id,
                queue_mode="immediate",
                defer_seconds=0,
            )
            log.info(f"Queued workflow execution for {workflow_id} with job ID {job.job_id}")
            return True

        except Exception as e:
            log.error(f"Error queuing workflow execution for {workflow_id}: {e!s}")
            return False

    @staticmethod
    async def queue_todo_workflow_generation(
        todo_id: str, user_id: str, title: str, description: str = ""
    ) -> bool:
        """Queue todo workflow generation as a background task.

        This triggers process_workflow_generation_task which:
        1. Creates workflow with is_todo_workflow=True
        2. Links it to the todo
        3. Broadcasts WebSocket event when complete
        """
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job(
                "process_workflow_generation_task",
                todo_id,
                user_id,
                title,
                description,
            )

            if job:
                # Set a Redis flag to indicate workflow generation is pending
                # This allows status endpoint to return is_generating=true
                # Note: ArqRedis pool IS the redis connection
                await pool.set(
                    f"todo_workflow_generating:{todo_id}",
                    "1",
                    ex=300,  # 5 minute TTL
                )

                log.info(f"Queued todo workflow generation for {todo_id} with job ID {job.job_id}")
                return True
            log.error(f"Failed to queue todo workflow generation for {todo_id}")
            return False

        except Exception as e:
            log.error(f"Error queuing todo workflow generation for {todo_id}: {e!s}")
            return False

    @staticmethod
    async def is_workflow_generating(todo_id: str) -> bool:
        """Check if workflow generation is in progress for a todo."""
        try:
            pool = await RedisPoolManager.get_pool()
            result = await pool.get(f"todo_workflow_generating:{todo_id}")
            return result is not None
        except Exception:
            return False

    @staticmethod
    async def clear_workflow_generating_flag(todo_id: str) -> None:
        """Clear the workflow generating flag after completion."""
        try:
            pool = await RedisPoolManager.get_pool()
            await pool.delete(f"todo_workflow_generating:{todo_id}")
        except Exception as e:
            log.warning(f"Failed to clear generating flag for {todo_id}: {e}")
