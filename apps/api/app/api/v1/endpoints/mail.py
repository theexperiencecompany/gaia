from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.mail_prompts import EMAIL_COMPOSER
from app.api.v1.dependencies.google_scope_dependencies import (
    require_integration,
    require_integration_user_id,
)
from app.constants.log_tags import LogTag
from app.decorators import tiered_rate_limit
from app.models.mail_models import (
    ApplyLabelRequest,
    ArchiveEmailsResponse,
    BulkEmailImportanceSummariesResponse,
    ComposedEmailOutput,
    DraftMutationResponse,
    DraftRequest,
    EmailActionRequest,
    EmailImportanceSummariesResponse,
    EmailImportanceSummaryResponse,
    EmailReadStatusRequest,
    EmailRequest,
    GmailDeletionResponse,
    GmailDraftResource,
    GmailDraftsResponse,
    GmailLabelResource,
    GmailLabelsResponse,
    GmailMessageResponse,
    GmailMessagesResponse,
    GmailSearchFilters,
    GmailThreadResponse,
    LabelRequest,
    MarkAsReadResponse,
    MarkAsUnreadResponse,
    ModifyLabelsResponse,
    MoveToInboxResponse,
    SendDraftResponse,
    SendEmailForm,
    SendEmailRequest,
    SendEmailResponse,
    SendEmailWithAttachmentsResponse,
    StarEmailsResponse,
    TrashEmailsResponse,
    UnstarEmailsResponse,
    UntrashEmailsResponse,
)
from app.services.analytics_service import AnalyticsEvents, capture_context_event
from app.services.mail.email_importance_service import (
    get_bulk_email_importance_summaries as get_bulk_importance_summaries_service,
    get_email_importance_summaries as get_importance_summaries_service,
    get_single_email_importance_summary as get_single_importance_summary_service,
)
from app.services.mail.mail_service import (
    EmailContent,
    LabelChanges,
    apply_labels,
    archive_messages,
    create_draft,
    create_label,
    delete_draft,
    delete_label,
    fetch_thread,
    get_draft,
    get_email_by_id as get_email_by_id_service,
    list_drafts,
    list_labels as list_labels_service,
    mark_messages_as_read,
    mark_messages_as_unread,
    move_to_inbox,
    remove_labels,
    search_messages,
    send_draft,
    send_email,
    star_messages,
    trash_messages,
    unstar_messages,
    untrash_messages,
    update_draft,
    update_label as update_label_service,
)
from app.utils.embedding_utils import search_notes_by_similarity
from app.utils.user_preferences_utils import format_writing_style_for_prompt
from shared.py.wide_events import log

router = APIRouter()


@router.get("/gmail/labels", summary="List Gmail Labels")
async def list_labels(
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailLabelsResponse:
    log.set(operation="get_labels")
    try:
        result = await list_labels_service(user_id=user_id)

        if result.success:
            log.set(
                operation="get_labels",
                result_count=result.count,
                outcome="success",
            )
            return GmailLabelsResponse(labels=result.labels, count=result.count)
        raise HTTPException(status_code=500, detail=result.error or "Failed to list labels")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/gmail/messages")
async def list_messages(
    max_results: int = 20,
    pageToken: str | None = None,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailMessagesResponse:
    try:
        # Use the new search_messages function with inbox filter
        response = await search_messages(
            user_id=user_id,
            query="in:inbox",
            max_results=max_results,
            page_token=pageToken,
        )

        log.set(
            operation="list_emails",
            result_count=len(response.messages),
            folder="inbox",
            outcome="success",
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/gmail/message/{message_id}", summary="Get Gmail Message by ID")
async def get_email_by_id(
    message_id: str,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailMessageResponse:
    """
    Get a Gmail message by its ID.

    - **message_id**: The ID of the Gmail message to retrieve
    """
    log.set(operation="get_email", email_id=message_id)
    try:
        # Use the get_email_by_id service function
        result = await get_email_by_id_service(user_id=user_id, message_id=message_id)

        if result.success:
            log.set(
                operation="get_email",
                email_id=message_id,
                outcome="success",
            )
            return GmailMessageResponse(
                message=result.message,
                status="Message retrieved successfully",
            )
        error_msg = result.error or "Failed to retrieve message"
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
    # query-models through include_router, so a Query()-bound model 422s every
    # request expecting a JSON `filters=` param. Depends() binds each field
    # as its own flattened query param.
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


@router.post("/mail/ai/compose")
@tiered_rate_limit("mail_actions")
async def process_email(
    request: EmailRequest,
    current_user: dict[str, Any] = Depends(require_integration("gmail")),
) -> ComposedEmailOutput:
    log.set(mail={"operation": "compose"})
    try:
        user_id = current_user.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="User ID is required")
        log.set(user={"id": str(user_id)})

        notes = await search_notes_by_similarity(input_text=request.prompt, user_id=str(user_id))

        writing_style_data = current_user.get("onboarding", {}).get("writing_style")
        learned_style_block = format_writing_style_for_prompt(writing_style_data)

        prompt = EMAIL_COMPOSER.format(
            sender_name=current_user.get("name") or "none",
            subject=request.subject or "empty",
            body=request.body or "empty",
            writing_style=request.writingStyle or "Professional",
            content_length=request.contentLength or "None",
            clarity_option=request.clarityOption or "None",
            notes=(
                "- ".join(note.get("content", "") for note in notes)
                if notes
                else "No relevant notes found."
            ),
            prompt=request.prompt,
            learned_writing_style=learned_style_block,
        )

        result = await ainvoke_structured(
            ComposedEmailOutput,
            prompt,
            label="mail_compose",
            config=metered_config(str(user_id)),
        )
        capture_context_event(AnalyticsEvents.EMAIL_COMPOSED)
        return result
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

        capture_context_event(
            AnalyticsEvents.EMAIL_REPLIED if form.thread_id else AnalyticsEvents.EMAIL_SENT,
            {
                "has_attachments": bool(form.attachments),
                "attachment_count": len(form.attachments) if form.attachments else 0,
            },
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
            message_id=(sent_message.data or {}).get("id"),
            status="Email sent successfully",
            attachments_count=len(form.attachments) if form.attachments else 0,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e!s}") from e


@router.post(
    "/gmail/send-json",
    summary="Send an email using JSON payload",
    responses={500: {"description": "Gmail rejected the send, or the send failed upstream"}},
)
@tiered_rate_limit("mail_actions")
async def send_email_json(
    request: SendEmailRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> SendEmailResponse:
    """
    Send an email using the Gmail API with JSON payload (no attachments).

    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients
    """
    try:
        # Send the email using the new async function
        sent_message = await send_email(
            user_id=user_id,
            to=request.to[0],
            content=EmailContent(
                subject=request.subject,
                body=request.body,
                extra_recipients=request.to[1:],
                cc_list=request.cc,
                bcc_list=request.bcc,
            ),
        )

        if not sent_message.successful:
            raise HTTPException(
                status_code=500,
                detail=sent_message.error or "Failed to send email",
            )

        capture_context_event(AnalyticsEvents.EMAIL_SENT, {"recipient_count": len(request.to)})
        log.set(
            operation="send_email",
            has_attachment=False,
            outcome="success",
        )
        return SendEmailResponse(
            message_id=(sent_message.data or {}).get("id"),
            status="Email sent successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e!s}") from e


@router.post("/gmail/mark-as-read", summary="Mark emails as read")
@tiered_rate_limit("mail_actions")
async def mark_as_read(
    request: EmailReadStatusRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> MarkAsReadResponse:
    """
    Mark Gmail messages as read by removing the UNREAD label.

    - **message_ids**: List of Gmail message IDs to mark as read

    Returns a list of IDs that were successfully marked as read.
    """
    try:
        # Mark messages as read using the new async function
        modified_messages = await mark_messages_as_read(
            user_id=user_id, message_ids=request.message_ids
        )

        log.set(
            operation="mark_read",
            result_count=len(modified_messages),
            outcome="success",
        )
        return MarkAsReadResponse(
            success=True,
            marked_as_read=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages marked as read",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to mark messages as read: {e!s}"
        ) from e


@router.post("/gmail/mark-as-unread", summary="Mark emails as unread")
@tiered_rate_limit("mail_actions")
async def mark_as_unread(
    request: EmailReadStatusRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> MarkAsUnreadResponse:
    """
    Mark Gmail messages as unread by adding the UNREAD label.

    - **message_ids**: List of Gmail message IDs to mark as unread

    Returns a list of IDs that were successfully marked as unread.
    """
    try:
        # Mark messages as unread using the new async function
        modified_messages = await mark_messages_as_unread(
            user_id=user_id, message_ids=request.message_ids
        )

        log.set(
            operation="mark_unread",
            result_count=len(modified_messages),
            outcome="success",
        )
        return MarkAsUnreadResponse(
            success=True,
            marked_as_unread=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages marked as unread",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to mark messages as unread: {e!s}"
        ) from e


@router.post("/gmail/star", summary="Star emails")
@tiered_rate_limit("mail_actions")
async def star_emails(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> StarEmailsResponse:
    """
    Star Gmail messages by adding the STARRED label.

    - **message_ids**: List of Gmail message IDs to star

    Returns a list of IDs that were successfully starred.
    """
    try:
        # Star messages using the new async function
        modified_messages = await star_messages(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="star_emails",
            result_count=len(modified_messages),
            outcome="success",
        )
        return StarEmailsResponse(
            success=True,
            starred=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages starred",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to star messages: {e!s}") from e


@router.post("/gmail/unstar", summary="Unstar emails")
@tiered_rate_limit("mail_actions")
async def unstar_emails(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> UnstarEmailsResponse:
    """
    Unstar Gmail messages by removing the STARRED label.

    - **message_ids**: List of Gmail message IDs to unstar

    Returns a list of IDs that were successfully unstarred.
    """
    try:
        # Unstar messages using the new async function
        modified_messages = await unstar_messages(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="unstar_emails",
            result_count=len(modified_messages),
            outcome="success",
        )
        return UnstarEmailsResponse(
            success=True,
            unstarred=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages unstarred",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unstar messages: {e!s}") from e


@router.post("/gmail/trash", summary="Move emails to trash")
@tiered_rate_limit("mail_actions")
async def trash_emails(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> TrashEmailsResponse:
    """
    Move Gmail messages to trash.

    - **message_ids**: List of Gmail message IDs to move to trash

    Returns a list of IDs that were successfully moved to trash.
    """
    try:
        # Trash messages using the new async function
        modified_messages = await trash_messages(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="delete_email",
            result_count=len(modified_messages),
            outcome="success",
        )
        return TrashEmailsResponse(
            success=True,
            trashed=[msg["id"] for msg in modified_messages],
            count=len(modified_messages),
            status="Messages moved to trash",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to move messages to trash: {e!s}"
        ) from e


@router.post("/gmail/untrash", summary="Restore emails from trash")
@tiered_rate_limit("mail_actions")
async def untrash_emails(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> UntrashEmailsResponse:
    """
    Restore Gmail messages from trash.

    - **message_ids**: List of Gmail message IDs to restore from trash

    Returns a list of IDs that were successfully restored from trash.
    """
    try:
        # Restore messages using the new async function
        modified_messages = await untrash_messages(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="untrash_emails",
            result_count=len(modified_messages),
            outcome="success",
        )
        return UntrashEmailsResponse(
            success=True,
            restored=[msg["id"] for msg in modified_messages],
            count=len(modified_messages),
            status="Messages restored from trash",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to restore messages from trash: {e!s}"
        ) from e


@router.post("/gmail/archive", summary="Archive emails")
@tiered_rate_limit("mail_actions")
async def archive_emails(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> ArchiveEmailsResponse:
    """
    Archive Gmail messages by removing the INBOX label.

    - **message_ids**: List of Gmail message IDs to archive

    Returns a list of IDs that were successfully archived.
    """
    try:
        # Archive messages using the new async function
        modified_messages = await archive_messages(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="archive_email",
            result_count=len(modified_messages),
            outcome="success",
        )
        return ArchiveEmailsResponse(
            success=True,
            archived=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages archived",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive messages: {e!s}") from e


@router.post("/gmail/move-to-inbox", summary="Move emails to inbox")
@tiered_rate_limit("mail_actions")
async def move_emails_to_inbox(
    request: EmailActionRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> MoveToInboxResponse:
    """
    Move Gmail messages to inbox by adding the INBOX label.

    - **message_ids**: List of Gmail message IDs to move to inbox

    Returns a list of IDs that were successfully moved to inbox.
    """
    try:
        # Move messages to inbox using the new async function
        modified_messages = await move_to_inbox(user_id=user_id, message_ids=request.message_ids)

        log.set(
            operation="move_email",
            folder="inbox",
            result_count=len(modified_messages),
            outcome="success",
        )
        return MoveToInboxResponse(
            success=True,
            moved_to_inbox=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Messages moved to inbox",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to move messages to inbox: {e!s}"
        ) from e


@router.get("/gmail/thread/{thread_id}", summary="Get complete email thread")
async def get_thread(
    thread_id: str, user_id: str = Depends(require_integration_user_id("gmail"))
) -> GmailThreadResponse:
    """
    Fetch a complete email thread with all messages.

    - **thread_id**: The Gmail thread ID to fetch

    Returns the thread with all its messages in chronological order.
    """
    try:
        # Get thread using the new async function
        thread = await fetch_thread(user_id=user_id, thread_id=thread_id)
        messages_count = len(thread.messages or [])

        log.set(
            operation="get_thread",
            thread_id=thread_id,
            result_count=messages_count,
            outcome="success",
        )
        return GmailThreadResponse(
            thread_id=thread_id,
            messages_count=messages_count,
            thread=thread.as_payload(),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch email thread: {e!s}") from e


@router.post("/gmail/labels", summary="Create a new Gmail label")
@tiered_rate_limit("mail_actions")
async def create_label_route(
    request: LabelRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailLabelResource:
    """
    Create a new Gmail label.

    - **name**: Name of the label
    - **label_list_visibility**: Whether the label appears in the label list
    - **message_list_visibility**: Whether the label appears in the message list
    - **background_color**: Background color of the label (hex code)
    - **text_color**: Text color of the label (hex code)

    Returns the created label data — the Gmail payload verbatim.
    """
    try:
        # Create label using the new async function
        new_label = await create_label(
            user_id=user_id,
            name=request.name,
            label_list_visibility=request.label_list_visibility or "labelShow",
            message_list_visibility=request.message_list_visibility or "show",
        )
        log.set(
            operation="create_label",
            label=request.name,
            outcome="success",
        )
        return GmailLabelResource.model_validate(new_label.as_payload())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/gmail/labels/{label_id}", summary="Update an existing Gmail label")
@tiered_rate_limit("mail_actions")
async def update_label_route(
    label_id: str,
    request: LabelRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailLabelResource:
    """
    Update an existing Gmail label.

    - **label_id**: ID of the label to update
    - **name**: New name for the label
    - **label_list_visibility**: Whether the label appears in the label list
    - **message_list_visibility**: Whether the label appears in the message list
    - **background_color**: Background color of the label (hex code)
    - **text_color**: Text color of the label (hex code)

    Returns the updated label data — the Gmail payload verbatim.
    """
    try:
        # Update label using the new async function
        updated_label = await update_label_service(
            user_id=user_id,
            label_id=label_id,
            changes=LabelChanges(
                name=request.name,
                label_list_visibility=request.label_list_visibility,
                message_list_visibility=request.message_list_visibility,
                background_color=request.background_color,
                text_color=request.text_color,
            ),
        )
        log.set(
            operation="update_label",
            label=label_id,
            outcome="success",
        )
        return GmailLabelResource.model_validate(updated_label.as_payload())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/gmail/labels/{label_id}", summary="Delete a Gmail label")
@tiered_rate_limit("mail_actions")
async def delete_label_route(
    label_id: str, user_id: str = Depends(require_integration_user_id("gmail"))
) -> GmailDeletionResponse:
    """
    Delete a Gmail label.

    - **label_id**: ID of the label to delete

    Returns a success message.
    """
    log.set(operation="delete_label", label=label_id)
    try:
        # Delete label using the new async function
        success = await delete_label(user_id=user_id, label_id=label_id)
        if success:
            log.set(operation="delete_label", label=label_id, outcome="success")
            return GmailDeletionResponse(status="success", message="Label deleted successfully")
        # Reported as a 200 to the client, so log.error is the only trace this failure leaves.
        log.error(f"{LogTag.MAIL} Label deletion reported failure", label=label_id)
        log.set(outcome="failed")
        return GmailDeletionResponse(status="error", message="Failed to delete label")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/gmail/messages/apply-label", summary="Apply labels to messages")
@tiered_rate_limit("mail_actions")
async def apply_labels_route(
    request: ApplyLabelRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> ModifyLabelsResponse:
    """
    Apply one or more labels to specified messages.

    - **message_ids**: List of message IDs
    - **label_ids**: List of label IDs to apply

    Returns a list of modified messages.
    """
    try:
        # Apply labels using the new async function
        modified_messages = await apply_labels(
            user_id=user_id,
            message_ids=request.message_ids,
            label_ids=request.label_ids,
        )

        log.set(
            operation="apply_label",
            result_count=len(modified_messages),
            outcome="success",
        )
        return ModifyLabelsResponse(
            success=True,
            modified_messages=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Labels applied successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/gmail/messages/remove-label", summary="Remove labels from messages")
@tiered_rate_limit("mail_actions")
async def remove_labels_route(
    request: ApplyLabelRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> ModifyLabelsResponse:
    """
    Remove one or more labels from specified messages.

    - **message_ids**: List of message IDs
    - **label_ids**: List of label IDs to remove

    Returns a list of modified messages.
    """
    try:
        # Remove labels using the new async function
        modified_messages = await remove_labels(
            user_id=user_id,
            message_ids=request.message_ids,
            label_ids=request.label_ids,
        )

        log.set(
            operation="remove_label",
            result_count=len(modified_messages),
            outcome="success",
        )
        return ModifyLabelsResponse(
            success=True,
            modified_messages=[msg.id for msg in modified_messages],
            count=len(modified_messages),
            status="Labels removed successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/gmail/drafts", summary="Create a new draft email")
@tiered_rate_limit("mail_actions")
async def create_draft_route(
    request: DraftRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> DraftMutationResponse:
    """
    Create a new Gmail draft email.

    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients

    Returns the created draft data.
    """
    try:
        # Create draft using the new async function
        draft = await create_draft(
            user_id=user_id,
            to_list=request.to,
            subject=request.subject,
            body=request.body,
            cc_list=request.cc,
            bcc_list=request.bcc,
        )
        message_id = (draft.message or {}).get("id")

        log.set(
            operation="create_draft",
            email_id=message_id,
            outcome="success",
        )
        return DraftMutationResponse(
            draft_id=draft.id,
            message_id=message_id,
            status="Draft created successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/gmail/drafts", summary="List all draft emails")
async def list_drafts_route(
    max_results: int = 20,
    page_token: str | None = None,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> GmailDraftsResponse:
    """
    List all Gmail draft emails.

    - **max_results**: Maximum number of drafts to return
    - **page_token**: Token for pagination

    Returns a list of drafts and a next page token if more results are available.
    """
    try:
        # List drafts using the new async function
        drafts = await list_drafts(
            user_id=user_id,
            max_results=max_results,
            page_token=page_token,
        )

        log.set(
            operation="list_drafts",
            result_count=len(drafts.drafts),
            outcome="success",
        )
        return drafts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/gmail/drafts/{draft_id}", summary="Get a specific draft email")
async def get_draft_route(
    draft_id: str, user_id: str = Depends(require_integration_user_id("gmail"))
) -> GmailDraftResource:
    """
    Get a specific Gmail draft email.

    - **draft_id**: ID of the draft to retrieve

    Returns the draft data with message details — the Gmail payload verbatim.
    """
    try:
        # Get draft using the new async function
        draft = await get_draft(user_id=user_id, draft_id=draft_id)

        log.set(
            operation="get_draft",
            email_id=draft_id,
            outcome="success",
        )
        return GmailDraftResource.model_validate(draft.as_payload())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/gmail/drafts/{draft_id}", summary="Update a draft email")
@tiered_rate_limit("mail_actions")
async def update_draft_route(
    draft_id: str,
    request: DraftRequest,
    user_id: str = Depends(require_integration_user_id("gmail")),
) -> DraftMutationResponse:
    """
    Update an existing Gmail draft email.

    - **draft_id**: ID of the draft to update
    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients

    Returns the updated draft data.
    """
    try:
        # Update draft using the new async function
        updated_draft = await update_draft(
            user_id=user_id,
            draft_id=draft_id,
            to_list=request.to,
            content=EmailContent(
                subject=request.subject,
                body=request.body,
                cc_list=request.cc,
                bcc_list=request.bcc,
            ),
        )

        log.set(
            operation="update_draft",
            email_id=draft_id,
            outcome="success",
        )
        return DraftMutationResponse(
            draft_id=updated_draft.id,
            message_id=(updated_draft.message or {}).get("id"),
            status="Draft updated successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/gmail/drafts/{draft_id}", summary="Delete a draft email")
@tiered_rate_limit("mail_actions")
async def delete_draft_route(
    draft_id: str, user_id: str = Depends(require_integration_user_id("gmail"))
) -> GmailDeletionResponse:
    """
    Delete a Gmail draft email.

    - **draft_id**: ID of the draft to delete

    Returns a success message.
    """
    log.set(operation="delete_draft", email_id=draft_id)
    try:
        # Delete draft using the new async function
        success = await delete_draft(user_id=user_id, draft_id=draft_id)

        if success:
            log.set(operation="delete_draft", email_id=draft_id, outcome="success")
            return GmailDeletionResponse(status="success", message="Draft deleted successfully")
        # Reported as a 200 to the client, so log.error is the only trace this failure leaves.
        log.error(f"{LogTag.MAIL} Draft deletion reported failure", email_id=draft_id)
        log.set(outcome="failed")
        return GmailDeletionResponse(status="error", message="Failed to delete draft")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


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
            capture_context_event(AnalyticsEvents.EMAIL_SENT)
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


@router.get("/gmail/importance-summaries", summary="Get email importance summaries")
async def get_email_importance_summaries(
    limit: int = 50,
    important_only: bool = False,
    current_user: dict[str, Any] = Depends(require_integration("gmail")),
) -> EmailImportanceSummariesResponse:
    """
    Get email importance summaries for the current user.

    - **limit**: Maximum number of emails to return (default: 50)
    - **important_only**: If True, only return important emails (default: False)

    Returns list of email summaries with importance analysis.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found")

        # Use service function to get email summaries
        result = await get_importance_summaries_service(user_id, limit, important_only)
        log.set(
            operation="get_importance_summaries",
            important_only=important_only,
            outcome="success",
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving email summaries: {e!s}"
        ) from e


@router.get(
    "/gmail/importance-summary/{message_id}",
    summary="Get single email importance summary",
)
async def get_single_email_importance_summary(
    message_id: str, current_user: dict[str, Any] = Depends(require_integration("gmail"))
) -> EmailImportanceSummaryResponse:
    """
    Get importance summary for a specific email.

    - **message_id**: Gmail message ID

    Returns the importance analysis for the specified email.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found")

        # Use service function to get email summary
        result = await get_single_importance_summary_service(user_id, message_id)

        if result is None:
            raise HTTPException(status_code=404, detail="Email summary not found")

        log.set(
            operation="get_importance_summary",
            email_id=message_id,
            outcome="success",
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving email summary: {e!s}") from e


@router.post("/gmail/importance-summaries/bulk", summary="Get bulk email importance summaries")
async def get_bulk_email_importance_summaries(
    request: EmailActionRequest,
    current_user: dict[str, Any] = Depends(require_integration("gmail")),
) -> BulkEmailImportanceSummariesResponse:
    """
    Get importance summaries for multiple emails in bulk.

    - **message_ids**: List of Gmail message IDs

    Returns summaries for all available emails. Does not throw error for missing summaries.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found")

        # Use service function to get bulk email summaries
        result = await get_bulk_importance_summaries_service(user_id, request.message_ids)
        log.set(
            operation="get_bulk_importance_summaries",
            result_count=len(request.message_ids),
            outcome="success",
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving bulk email summaries: {e!s}"
        ) from e
