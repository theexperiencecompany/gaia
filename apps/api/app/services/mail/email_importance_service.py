"""Simple email processing with Gemini for background tasks."""

from typing import Any

from app.constants.log_tags import LogTag
from app.db.repositories.mail import mail_repository
from app.models.mail_models import (
    BulkEmailImportanceSummariesResponse,
    EmailImportanceSummariesResponse,
    EmailImportanceSummaryResponse,
    MailDocument,
)
from shared.py.wide_events import MailContext, log


def _mail_dict(summary: MailDocument) -> dict[str, Any]:
    """JSON-safe email-summary dict the read endpoints return (string ``_id``)."""
    return {**summary.model_dump(mode="json", exclude={"id"}), "_id": summary.id}


async def get_email_importance_summaries(
    user_id: str, limit: int = 50, important_only: bool = False
) -> EmailImportanceSummariesResponse:
    """Get email importance summaries for a user."""
    log.set(user={"id": user_id}, mail=MailContext(operation="summarize"))
    try:
        summaries = await mail_repository.list_for_user(
            user_id, important_only=important_only, limit=limit
        )
        emails = [_mail_dict(summary) for summary in summaries]

        log.set_ns("mail", result_count=len(emails), success=True)
        return EmailImportanceSummariesResponse(
            status="success",
            emails=emails,
            count=len(emails),
            filtered_by_importance=important_only,
        )
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error retrieving email summaries for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def get_single_email_importance_summary(
    user_id: str, message_id: str
) -> EmailImportanceSummaryResponse | None:
    """Get the importance summary for a specific email."""
    log.set(user={"id": user_id}, mail=MailContext(operation="summarize"))
    try:
        summary = await mail_repository.get_by_message(user_id, message_id)
        if summary is None:
            log.set_ns("mail", result_count=0, success=True)
            return None

        log.set_ns("mail", result_count=1, success=True)
        return EmailImportanceSummaryResponse(status="success", email=_mail_dict(summary))
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error retrieving email summary",
            user_id=user_id,
            message_id=message_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def get_bulk_email_importance_summaries(
    user_id: str, message_ids: list[str]
) -> BulkEmailImportanceSummariesResponse:
    """Get importance summaries for multiple emails in bulk, indexed by message_id."""
    log.set(
        user={"id": user_id},
        mail=MailContext(operation="summarize", message_count=len(message_ids)),
    )
    try:
        summaries = await mail_repository.list_by_message_ids(user_id, message_ids)
        email_summaries = {summary.message_id: _mail_dict(summary) for summary in summaries}

        found_message_ids = set(email_summaries.keys())
        missing_message_ids = set(message_ids) - found_message_ids

        log.set_ns("mail", result_count=len(found_message_ids), success=True)
        return BulkEmailImportanceSummariesResponse(
            status="success",
            emails=email_summaries,
            found_count=len(found_message_ids),
            missing_count=len(missing_message_ids),
            found_message_ids=list(found_message_ids),
            missing_message_ids=list(missing_message_ids),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error retrieving bulk email summaries for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
