from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException

from app.api.v1.dependencies.google_scope_dependencies import require_integration_user_id
from app.decorators import tiered_rate_limit
from app.models.composio_schemas.gmail import GmailResourceId
from app.models.mail_models import (
    GmailMessagesResponse,
    GmailSearchFilters,
    SendDraftResponse,
    SendEmailForm,
    SendEmailWithAttachmentsResponse,
)
from app.services.analytics_service import capture
from app.services.mail.mail_service import (
    EmailContent,
    search_messages,
    send_draft,
    send_email,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.mail import EmailReplied, EmailSent
from shared.py.wide_events import log

router = APIRouter()


def _build_gmail_query(filters: GmailSearchFilters) -> str:
    """Translate the advanced-search filters into one Gmail query string."""
    parts: list[str] = [filters.query] if filters.query else []
    prefixed = {
        "from:": filters.sender,
        "to:": filters.recipient,
        "subject:": filters.subject,
        "filename:": filters.attachment_type,
        "after:": filters.date_from,
        "before:": filters.date_to,
        "label:": filters.label,
    }
    parts += [f"{prefix}{value}" for prefix, value in prefixed.items() if value]
    if filters.has_attachment is not None:
        parts.append("has:attachment" if filters.has_attachment else "-has:attachment")
    if filters.is_read is not None:
        parts.append("is:read" if filters.is_read else "is:unread")
    return " ".join(parts)


@router.get("/gmail/search", summary="Advanced search for Gmail messages")
async def search_emails(
    # Bound as a dependency, not Query(): FastAPI 0.139 does not flatten
    # query-models through include_router, so Query() 422s every request;
    # Depends() binds each field as its own flattened query param.
    filters: Annotated[GmailSearchFilters, Depends()],
    max_results: int = 20,
    page_token: str | None = None,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailMessagesResponse:
    """
    Search Gmail messages with advanced query parameters.
    Note: max_results is capped at 20 to avoid Composio payload size limits.

    Returns a list of messages matching the search criteria and a next page token if more results are available.
    """
    log.set(operation="search_emails", user={"id": user_id})
    try:
        # Cap max_results to avoid Composio 413 payload-too-large errors
        max_results = min(max_results, 20)

        gmail_query = _build_gmail_query(filters)

        response = await search_messages(
            user_id=user_id,
            query=gmail_query,
            max_results=max_results,
            page_token=page_token,
        )

        log.set(
            operation="search_emails",
            result_count=len(response.messages),
            has_attachment=filters.has_attachment,
            label=filters.label,
            outcome="success",
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/gmail/send", summary="Send an email using Gmail API")
@tiered_rate_limit("mail_actions")
async def send_email_route(
    form: Annotated[SendEmailForm, Form()],
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> SendEmailWithAttachmentsResponse:
    """
    Send an email using the Gmail API.

    - **to**: Recipient email addresses (comma-separated)
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional CC recipients (comma-separated)
    - **bcc**: Optional BCC recipients (comma-separated)
    - **attachments**: Optional files to attach to the email
    """
    try:
        # Parse recipients
        to_list = [email.strip() for email in form.to.split(",") if email.strip()]
        cc_list = [email.strip() for email in form.cc.split(",")] if form.cc else None
        bcc_list = [email.strip() for email in form.bcc.split(",")] if form.bcc else None

        # Send the email using the new async function
        sent_message = await send_email(
            user_id=user_id,
            to=to_list[0],
            content=EmailContent(
                subject=form.subject,
                body=form.body,
                extra_recipients=to_list[1:],
                cc_list=cc_list,
                bcc_list=bcc_list,
            ),
            attachments=form.attachments,
            thread_id=form.thread_id,
        )

        if not sent_message.successful:
            raise HTTPException(
                status_code=500,
                detail=sent_message.error or "Failed to send email",
            )

        attachment_count = len(form.attachments) if form.attachments else 0
        capture(
            UserId(user_id),
            EmailReplied(has_attachments=bool(form.attachments), attachment_count=attachment_count)
            if form.thread_id
            else EmailSent(
                has_attachments=bool(form.attachments), attachment_count=attachment_count
            ),
        )
        log.set(
            operation="send_email",
            thread_id=form.thread_id,
            has_attachment=bool(form.attachments),
            attachments_count=len(form.attachments) if form.attachments else 0,
            outcome="success",
        )
        # Gmail owns the schema of the Composio envelope's ``data``; this is the boundary read.
        return SendEmailWithAttachmentsResponse(
            message_id=GmailResourceId.model_validate(sent_message.data or {}).id,
            status="Email sent successfully",
            attachments_count=len(form.attachments) if form.attachments else 0,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e!s}") from e


@router.post("/gmail/drafts/{draft_id}/send", summary="Send a draft email")
@tiered_rate_limit("mail_actions")
async def send_draft_route(
    draft_id: str, user_id: str = Depends(require_integration_user_id("gmail"))
) -> SendDraftResponse:
    """
    Send an existing Gmail draft email.

    - **draft_id**: ID of the draft to send

    Returns the sent message data.
    """
    log.set(operation="send_draft", email_id=draft_id)
    try:
        # Send draft using the new async function
        sent_message = await send_draft(user_id=user_id, draft_id=draft_id)

        if sent_message.successful:
            thread_id = sent_message.thread_id or ""
            capture(UserId(user_id), EmailSent())
            log.set(
                operation="send_draft",
                email_id=draft_id,
                thread_id=thread_id,
                outcome="success",
            )
            return SendDraftResponse(
                message_id=sent_message.id or "",
                thread_id=thread_id,
                status="Draft sent successfully",
                successful=True,
            )
        log.set(outcome="failed")
        raise HTTPException(
            status_code=500,
            detail=sent_message.error or "Failed to send draft",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
