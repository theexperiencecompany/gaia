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
