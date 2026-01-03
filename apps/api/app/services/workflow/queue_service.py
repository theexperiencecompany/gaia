"""Unified workflow queue service for background job management."""

from datetime import datetime
from typing import Optional

from app.config.loggers import general_logger as logger
from app.utils.redis_utils import RedisPoolManager


class WorkflowQueueService:
    """Unified service for managing all workflow job queues."""

    @staticmethod
    async def queue_workflow_generation(workflow_id: str, user_id: str) -> bool:
        """Queue workflow generation as a background task."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job(
                "generate_workflow_steps", workflow_id, user_id
            )

            if job:
                logger.info(
                    f"Queued workflow generation for {workflow_id} with job ID {job.job_id}"
                )
                return True
            else:
                logger.error(f"Failed to queue workflow generation for {workflow_id}")
                return False

        except Exception as e:
            logger.error(
                f"Error queuing workflow generation for {workflow_id}: {str(e)}"
            )
            return False

    @staticmethod
    async def queue_workflow_execution(
        workflow_id: str, user_id: str, context: Optional[dict] = None
    ) -> bool:
        """Queue workflow execution as a background task."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job(
                "execute_workflow_by_id", workflow_id, context or {}
            )

            if job:
                logger.info(
                    f"Queued workflow execution for {workflow_id} with job ID {job.job_id}"
                )
                return True
            else:
                logger.error(f"Failed to queue workflow execution for {workflow_id}")
                return False

        except Exception as e:
            logger.error(
                f"Error queuing workflow execution for {workflow_id}: {str(e)}"
            )
            return False

    @staticmethod
    async def queue_scheduled_workflow_execution(
        workflow_id: str, scheduled_at: datetime, context: Optional[dict] = None
    ) -> bool:
        """Queue a scheduled workflow execution with defer_until."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job(
                "execute_workflow_by_id",
                workflow_id,
                context or {},
                _defer_until=scheduled_at,
            )

            if job:
                logger.info(
                    f"Queued scheduled workflow execution for {workflow_id} at {scheduled_at} with job ID {job.job_id}"
                )
                return True
            else:
                logger.error(
                    f"Failed to queue scheduled workflow execution for {workflow_id}"
                )
                return False

        except Exception as e:
            logger.error(
                f"Error queuing scheduled workflow execution for {workflow_id}: {str(e)}"
            )
            return False

    @staticmethod
    async def queue_workflow_regeneration(
        workflow_id: str,
        user_id: str,
        regeneration_reason: str,
        force_different_tools: bool = True,
    ) -> bool:
        """Queue workflow step regeneration as a background task."""
        try:
            pool = await RedisPoolManager.get_pool()

            job = await pool.enqueue_job(
                "regenerate_workflow_steps",
                workflow_id,
                user_id,
                regeneration_reason,
                force_different_tools,
            )

            if job:
                logger.info(
                    f"Queued workflow regeneration for {workflow_id} with job ID {job.job_id}"
                )
                return True
            else:
                logger.error(f"Failed to queue workflow regeneration for {workflow_id}")
                return False

        except Exception as e:
            logger.error(
                f"Error queuing workflow regeneration for {workflow_id}: {str(e)}"
            )
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

                logger.info(
                    f"Queued todo workflow generation for {todo_id} with job ID {job.job_id}"
                )
                return True
            else:
                logger.error(f"Failed to queue todo workflow generation for {todo_id}")
                return False

        except Exception as e:
            logger.error(
                f"Error queuing todo workflow generation for {todo_id}: {str(e)}"
            )
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
            logger.warning(f"Failed to clear generating flag for {todo_id}: {e}")
