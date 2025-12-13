from app.config.loggers import mail_webhook_logger as logger
from app.utils.redis_utils import RedisPoolManager


async def queue_email_processing(user_id: str, email_data: dict) -> dict:
    """
    Queue an email for background processing using unified queue service.

    Args:
        user_id (str): The user ID from the webhook
        email_data (dict): The email data from webhook

    Returns:
        dict: Response message indicating success
    """
    logger.info(
        f"Queueing email processing: user_id={user_id}, message_id={email_data.get('message_id', 'unknown')}"
    )

    try:
        # Use unified Redis pool manager
        pool = await RedisPoolManager.get_pool()

        # Enqueue the email processing task
        job = await pool.enqueue_job(
            "process_email_task",
            user_id,
            email_data,
        )

        if job:
            logger.info(
                f"Successfully queued email processing task with job ID: {job.job_id}"
            )
            return {
                "status": "success",
                "message": "Email processing started successfully.",
                "job_id": job.job_id,
            }
        else:
            logger.error("Failed to enqueue email processing task")
            return {"status": "error", "message": "Failed to start email processing."}

    except Exception as e:
        logger.error(f"Error queuing email processing: {str(e)}")
        return {
            "status": "error",
            "message": f"Error starting email processing: {str(e)}",
        }
