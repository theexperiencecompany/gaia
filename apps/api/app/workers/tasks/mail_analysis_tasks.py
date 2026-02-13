"""ARQ worker tasks for email analysis and smart reply generation."""

from app.config.loggers import worker_logger as logger


async def process_email_analysis_and_replies(
    ctx: dict, user_id: str, message_id: str, email_data: dict
) -> str:
    """Background task: run comprehensive analysis + smart reply generation."""
    from app.services.mail.email_importance_service import (
        analyze_email_on_demand,
        get_or_generate_smart_replies,
    )

    results = {"analysis": False, "smart_replies": False}

    try:
        analysis = await analyze_email_on_demand(user_id, message_id, email_data)
        if analysis:
            results["analysis"] = True
            logger.info(f"Analysis completed for message {message_id}")
    except Exception as e:
        logger.error(f"Analysis failed for message {message_id}: {e}")

    try:
        replies = await get_or_generate_smart_replies(user_id, message_id, email_data)
        if replies:
            results["smart_replies"] = True
            logger.info(f"Smart replies generated for message {message_id}")
    except Exception as e:
        logger.error(f"Smart reply generation failed for message {message_id}: {e}")

    return (
        f"Email processing for {message_id}: "
        f"analysis={'ok' if results['analysis'] else 'failed'}, "
        f"replies={'ok' if results['smart_replies'] else 'failed'}"
    )
