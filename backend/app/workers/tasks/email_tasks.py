"""
Email-related ARQ tasks.
"""

from datetime import datetime, timezone

from app.api.v1.middleware import RateLimitExceededException
from app.config.loggers import arq_worker_logger as logger
from app.db.mongodb.collections import mail_collection, workflows_collection
from app.services.mail.email_importance_service import (
    process_email_comprehensive_analysis,
)
from app.services.workflow.filter_service import filter_workflows_for_email
from app.services.workflow.trigger_matching_service import find_matching_workflows
from app.utils.email_utils import (
    convert_composio_to_gmail_format,
    extract_date,
    extract_labels,
    extract_sender,
    extract_string_content,
    extract_subject,
)
from app.workers.tasks.workflow_tasks import execute_workflow_as_chat


async def _perform_email_analysis(email_data: dict, user_id: str) -> None:
    """
    Perform email importance analysis and store results in database.
    Moved from process_email.py to unify email processing flow.

    Args:
        email_data: Email data from webhook
        user_id: User ID
    """
    try:
        # Convert Composio format to Gmail format for consistent parsing
        gmail_message = convert_composio_to_gmail_format(email_data)

        # Extract email information using robust parsing utilities
        content = extract_string_content(gmail_message)
        subject = extract_subject(gmail_message) or email_data.get("subject", "")
        sender = extract_sender(gmail_message) or email_data.get("sender", "")
        date = extract_date(gmail_message) or email_data.get("message_timestamp", "")
        labels = extract_labels(gmail_message)
        message_id = email_data.get("message_id", "")

        # Process email with comprehensive analysis (importance + semantic labels)
        analysis_result = await process_email_comprehensive_analysis(
            subject=subject, sender=sender, date=date, content=content
        )

        if analysis_result:
            # Store analysis in database
            email_doc = {
                "user_id": user_id,
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date,
                "labels": labels,  # Include Gmail labels
                "analyzed_at": datetime.now(timezone.utc),
                "content_preview": (content[:500] if content else ""),
                "is_important": analysis_result.is_important,
                "importance_level": analysis_result.importance_level,
                "summary": analysis_result.summary,
                "semantic_labels": analysis_result.semantic_labels,
            }

            await mail_collection.update_one(
                {"user_id": user_id, "message_id": message_id},
                {"$set": email_doc},
                upsert=True,
            )
        else:
            logger.error(f"Failed to analyze email {message_id} for user {user_id}")

    except Exception as e:
        logger.error(
            f"Error analyzing email {email_data.get('message_id', 'unknown')}: {str(e)}",
            exc_info=True,
        )


async def process_email_task(ctx: dict, user_id: str, email_data: dict) -> str:
    """
    Email processing task - handles workflow triggers and basic email processing.

    Args:
        ctx: ARQ context
        user_id: User ID from webhook
        email_data: Email data from webhook

    Returns:
        Processing result message
    """
    try:
        workflow_executions = []

        # Step 1: Perform email analysis and store in database
        await _perform_email_analysis(email_data, user_id)

        # Step 2: Find workflow matches
        matching_workflows = await find_matching_workflows(user_id)
        workflows_to_execute = []  # Initialize to ensure it's always defined

        # Apply intelligent LLM-based filtering before execution
        if matching_workflows:
            filtered_results = await filter_workflows_for_email(
                email_data, matching_workflows, user_id
            )

            # Extract workflows that should be executed
            workflows_to_execute = [
                result["workflow"]
                for result in filtered_results
                if result["should_execute"]
            ]

            # Log filtering decisions for monitoring
            for result in filtered_results:
                decision = result["decision"]
                logger.info(
                    f"Workflow {result['workflow'].id} filter decision: "
                    f"should_execute={decision.should_process}, "
                    f"confidence={decision.confidence}, "
                    f"reason={decision.reasoning[:100]}..."
                )

            # Execute filtered workflows with rate limiting
            if workflows_to_execute:
                trigger_context = {
                    "type": "gmail",
                    "email_data": email_data,
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                }

                for workflow in workflows_to_execute:
                    try:
                        from app.workers.tasks.workflow_tasks import (
                            create_workflow_completion_notification,
                        )

                        # Execute workflow
                        execution_messages = await execute_workflow_as_chat(
                            workflow, {"user_id": user_id}, trigger_context
                        )

                        # Store messages and send notification
                        await create_workflow_completion_notification(
                            workflow, execution_messages, user_id
                        )

                        # Update workflow statistics
                        await workflows_collection.update_one(
                            {"_id": workflow.id, "user_id": user_id},
                            {
                                "$inc": {
                                    "total_executions": 1,
                                    "successful_executions": 1,
                                },
                                "$set": {
                                    "last_executed_at": datetime.now(timezone.utc)
                                },
                            },
                        )

                        workflow_executions.append(
                            {
                                "workflow_id": workflow.id,
                                "status": "success",
                                "messages_count": len(execution_messages),
                            }
                        )

                    except RateLimitExceededException as rate_error:
                        logger.warning(
                            f"Rate limit exceeded for workflow {workflow.id}: {rate_error}"
                        )
                        workflow_executions.append(
                            {
                                "workflow_id": workflow.id,
                                "status": "rate_limited",
                                "error": str(rate_error),
                            }
                        )
                        try:
                            await workflows_collection.update_one(
                                {"_id": workflow.id, "user_id": user_id},
                                {"$inc": {"total_executions": 1}},
                            )
                        except Exception as e:
                            logger.debug(f"Failed to update workflow stats: {e}")

                    except Exception as workflow_error:
                        logger.error(
                            f"Workflow {workflow.id} failed: {workflow_error}",
                            exc_info=True,
                        )
                        workflow_executions.append(
                            {
                                "workflow_id": workflow.id,
                                "status": "error",
                                "error": str(workflow_error),
                            }
                        )
                        try:
                            await workflows_collection.update_one(
                                {"_id": workflow.id, "user_id": user_id},
                                {"$inc": {"total_executions": 1}},
                            )
                        except Exception as e:
                            logger.debug(f"Failed to update workflow stats: {e}")
        successful_executions = len(
            [w for w in workflow_executions if w["status"] == "success"]
        )
        failed_executions = len(
            [w for w in workflow_executions if w["status"] == "error"]
        )
        rate_limited_executions = len(
            [w for w in workflow_executions if w["status"] == "rate_limited"]
        )

        return f"Email processed successfully: {len(matching_workflows) if matching_workflows else 0} workflows found, {len(workflows_to_execute)} passed filtering, {len(workflow_executions)} executed (✅ {successful_executions} success, ❌ {failed_executions} failed, ⚠️ {rate_limited_executions} rate limited)"

    except Exception as e:
        error_msg = f"Failed to process email for user {user_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise
