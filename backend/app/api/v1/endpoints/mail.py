import json
from typing import Any, List, Optional

from app.agents.prompts.mail_prompts import EMAIL_COMPOSER
from app.api.v1.dependencies.google_scope_dependencies import require_integration
from app.decorators import tiered_rate_limit
from app.models.mail_models import (
    ApplyLabelRequest,
    DraftRequest,
    EmailActionRequest,
    EmailReadStatusRequest,
    EmailRequest,
    EmailSummaryRequest,
    LabelRequest,
    SendEmailRequest,
)
from app.services.mail.email_importance_service import (
    get_bulk_email_importance_summaries as get_bulk_importance_summaries_service,
)
from app.services.mail.email_importance_service import (
    get_email_importance_summaries as get_importance_summaries_service,
)
from app.services.mail.email_importance_service import (
    get_single_email_importance_summary as get_single_importance_summary_service,
)
from app.services.mail.mail_service import (
    apply_labels,
    archive_messages,
    create_draft,
    create_label,
    delete_draft,
    delete_label,
    fetch_thread,
    get_draft,
    list_drafts,
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
    update_label,
)
from app.services.mail.mail_service import (
    get_email_by_id as get_email_by_id_service,
)
from app.services.mail.mail_service import (
    list_labels as list_labels_service,
)
from app.utils.chat_utils import do_prompt_no_stream
from app.utils.embedding_utils import search_notes_by_similarity
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

router = APIRouter()


@router.get("/gmail/labels", summary="List Gmail Labels")
async def list_labels(
    current_user: dict = Depends(require_integration("gmail")),
):
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Use the list_labels service function
        result = await list_labels_service(user_id=str(user_id))

        if result.get("success"):
            return {
                "labels": result.get("labels", []),
                "count": result.get("count", 0),
            }
        else:
            raise HTTPException(
                status_code=500, detail=result.get("error", "Failed to list labels")
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/messages")
async def list_messages(
    max_results: int = 20,
    pageToken: Optional[str] = None,
    current_user: dict = Depends(require_integration("gmail")),
):
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Use the new search_messages function with inbox filter
        search_results = await search_messages(
            user_id=str(user_id),
            query="in:inbox",
            max_results=max_results,
            page_token=pageToken,
        )

        return {
            "messages": search_results.get("messages", []),
            "nextPageToken": search_results.get("nextPageToken"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/message/{message_id}", summary="Get Gmail Message by ID")
async def get_email_by_id(
    message_id: str,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Get a Gmail message by its ID.

    - **message_id**: The ID of the Gmail message to retrieve
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Use the get_email_by_id service function
        result = await get_email_by_id_service(
            user_id=str(user_id), message_id=message_id
        )

        if result.get("success"):
            return {
                "message": result.get("message"),
                "status": "Message retrieved successfully",
            }
        else:
            error_msg = result.get("error", "Failed to retrieve message")
            if "not found" in error_msg.lower():
                raise HTTPException(status_code=404, detail=error_msg)
            else:
                raise HTTPException(status_code=500, detail=error_msg)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/search", summary="Advanced search for Gmail messages")
async def search_emails(
    query: Optional[str] = None,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    subject: Optional[str] = None,
    has_attachment: Optional[bool] = None,
    attachment_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    label: Optional[str] = None,
    is_read: Optional[bool] = None,
    max_results: int = 20,
    page_token: Optional[str] = None,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Search Gmail messages with advanced query parameters.

    - **query**: Free text search query
    - **sender**: Filter by sender email
    - **recipient**: Filter by recipient email
    - **subject**: Filter by subject
    - **has_attachment**: Filter for messages with attachments
    - **attachment_type**: Filter by attachment type (e.g., pdf, doc)
    - **date_from**: Filter messages after this date (YYYY/MM/DD)
    - **date_to**: Filter messages before this date (YYYY/MM/DD)
    - **label**: Filter by label
    - **is_read**: Filter by read/unread status
    - **max_results**: Maximum number of results to return
    - **page_token**: Token for pagination

    Returns a list of messages matching the search criteria and a next page token if more results are available.
    """
    try:
        # Get user_id
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Build Gmail query string from parameters
        query_parts = []

        if query:
            query_parts.append(f"{query}")
        if sender:
            query_parts.append(f"from:{sender}")
        if recipient:
            query_parts.append(f"to:{recipient}")
        if subject:
            query_parts.append(f"subject:{subject}")
        if has_attachment is not None:
            query_parts.append(
                "has:attachment" if has_attachment else "-has:attachment"
            )
        if attachment_type:
            query_parts.append(f"filename:{attachment_type}")
        if date_from:
            query_parts.append(f"after:{date_from}")
        if date_to:
            query_parts.append(f"before:{date_to}")
        if label:
            query_parts.append(f"label:{label}")
        if is_read is not None:
            query_parts.append("is:read" if is_read else "is:unread")

        # Combine all query parts
        gmail_query = " ".join(query_parts)

        search_results = await search_messages(
            user_id=str(user_id),
            query=gmail_query,
            max_results=max_results,
            page_token=page_token,
        )

        return search_results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mail/ai/compose")
@tiered_rate_limit("mail_actions")
async def process_email(
    request: EmailRequest,
    current_user: dict = Depends(require_integration("gmail")),
) -> Any:
    try:
        user_id = current_user.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="User ID is required")

        notes = await search_notes_by_similarity(
            input_text=request.prompt, user_id=str(user_id)
        )

        prompt = EMAIL_COMPOSER.format(
            sender_name=current_user.get("name") or "none",
            subject=request.subject or "empty",
            body=request.body or "empty",
            writing_style=request.writingStyle or "Professional",
            content_length=request.contentLength or "None",
            clarity_option=request.clarityOption or "None",
            notes="- ".join(notes) if notes else "No relevant notes found.",
            prompt=request.prompt,
        )

        result = await do_prompt_no_stream(
            prompt=prompt,
        )
        if isinstance(result, dict) and result.get("response"):
            try:
                parsed_result = json.loads(result["response"])
                subject = parsed_result.get("subject", "")
                body = parsed_result.get("body", "")

                return {"subject": subject, "body": body}
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to parse response {e}"
                )
        else:
            raise HTTPException(status_code=500, detail="Invalid response format")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gmail/send", summary="Send an email using Gmail API")
@tiered_rate_limit("mail_actions")
async def send_email_route(
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    thread_id: Optional[str] = Form(None),
    is_html: Optional[bool] = Form(False),
    cc: Optional[str] = Form(None),
    bcc: Optional[str] = Form(None),
    attachments: Optional[List[UploadFile]] = File(None),
    current_user: dict = Depends(require_integration("gmail")),
):
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
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Parse recipients
        to_list = [email.strip() for email in to.split(",") if email.strip()]
        cc_list = [email.strip() for email in cc.split(",")] if cc else None
        bcc_list = [email.strip() for email in bcc.split(",")] if bcc else None

        # Send the email using the new async function
        sent_message = await send_email(
            user_id=str(user_id),
            to=to_list[0],
            extra_recipients=to_list[1:],
            subject=subject,
            body=body,
            is_html=is_html or False,
            cc_list=cc_list,
            bcc_list=bcc_list,
            attachments=attachments,
            thread_id=thread_id,
        )

        return {
            "message_id": sent_message.get("id"),
            "status": "Email sent successfully",
            "attachments_count": len(attachments) if attachments else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.post("/gmail/send-json", summary="Send an email using JSON payload")
@tiered_rate_limit("mail_actions")
async def send_email_json(
    request: SendEmailRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Send an email using the Gmail API with JSON payload (no attachments).

    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Send the email using the new async function
        sent_message = await send_email(
            user_id=str(user_id),
            to=request.to[0],
            extra_recipients=request.to[1:],
            subject=request.subject,
            body=request.body,
            is_html=False,
            cc_list=request.cc,
            bcc_list=request.bcc,
            attachments=None,
        )

        return {
            "message_id": sent_message.get("id"),
            "status": "Email sent successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


@router.post("/gmail/summarize", summary="Summarize an email using LLM")
async def summarize_email(
    request: EmailSummaryRequest,
    current_user: dict = Depends(require_integration("gmail")),
) -> Any:
    """
    Summarize an email using the LLM service.

    - **message_id**: The Gmail message ID to summarize
    - **include_key_points**: Whether to include key points in the summary
    - **include_action_items**: Whether to include action items in the summary
    - **max_length**: Maximum length of the summary in words

    Returns a summary of the email with optional key points and action items.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Note: Getting email by ID for summarization would need a dedicated Composio tool
        # For now, return a placeholder response or implement with available tools
        # This endpoint needs to be implemented based on available Composio Gmail tools
        raise HTTPException(
            status_code=501,
            detail="Email summarization not yet implemented with Composio tools",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to summarize email: {str(e)}"
        )


@router.post("/gmail/mark-as-read", summary="Mark emails as read")
@tiered_rate_limit("mail_actions")
async def mark_as_read(
    request: EmailReadStatusRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Mark Gmail messages as read by removing the UNREAD label.

    - **message_ids**: List of Gmail message IDs to mark as read

    Returns a list of IDs that were successfully marked as read.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Mark messages as read using the new async function
        modified_messages = await mark_messages_as_read(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "marked_as_read": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages marked as read",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to mark messages as read: {str(e)}"
        )


@router.post("/gmail/mark-as-unread", summary="Mark emails as unread")
@tiered_rate_limit("mail_actions")
async def mark_as_unread(
    request: EmailReadStatusRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Mark Gmail messages as unread by adding the UNREAD label.

    - **message_ids**: List of Gmail message IDs to mark as unread

    Returns a list of IDs that were successfully marked as unread.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Mark messages as unread using the new async function
        modified_messages = await mark_messages_as_unread(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "marked_as_unread": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages marked as unread",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to mark messages as unread: {str(e)}"
        )


@router.post("/gmail/star", summary="Star emails")
@tiered_rate_limit("mail_actions")
async def star_emails(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Star Gmail messages by adding the STARRED label.

    - **message_ids**: List of Gmail message IDs to star

    Returns a list of IDs that were successfully starred.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Star messages using the new async function
        modified_messages = await star_messages(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "starred": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages starred",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to star messages: {str(e)}"
        )


@router.post("/gmail/unstar", summary="Unstar emails")
@tiered_rate_limit("mail_actions")
async def unstar_emails(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Unstar Gmail messages by removing the STARRED label.

    - **message_ids**: List of Gmail message IDs to unstar

    Returns a list of IDs that were successfully unstarred.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Unstar messages using the new async function
        modified_messages = await unstar_messages(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "unstarred": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages unstarred",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to unstar messages: {str(e)}"
        )


@router.post("/gmail/trash", summary="Move emails to trash")
@tiered_rate_limit("mail_actions")
async def trash_emails(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Move Gmail messages to trash.

    - **message_ids**: List of Gmail message IDs to move to trash

    Returns a list of IDs that were successfully moved to trash.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Trash messages using the new async function
        modified_messages = await trash_messages(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "trashed": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages moved to trash",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to move messages to trash: {str(e)}"
        )


@router.post("/gmail/untrash", summary="Restore emails from trash")
@tiered_rate_limit("mail_actions")
async def untrash_emails(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Restore Gmail messages from trash.

    - **message_ids**: List of Gmail message IDs to restore from trash

    Returns a list of IDs that were successfully restored from trash.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Restore messages using the new async function
        modified_messages = await untrash_messages(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "restored": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages restored from trash",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to restore messages from trash: {str(e)}"
        )


@router.post("/gmail/archive", summary="Archive emails")
@tiered_rate_limit("mail_actions")
async def archive_emails(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Archive Gmail messages by removing the INBOX label.

    - **message_ids**: List of Gmail message IDs to archive

    Returns a list of IDs that were successfully archived.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Archive messages using the new async function
        modified_messages = await archive_messages(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "archived": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages archived",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to archive messages: {str(e)}"
        )


@router.post("/gmail/move-to-inbox", summary="Move emails to inbox")
@tiered_rate_limit("mail_actions")
async def move_emails_to_inbox(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Move Gmail messages to inbox by adding the INBOX label.

    - **message_ids**: List of Gmail message IDs to move to inbox

    Returns a list of IDs that were successfully moved to inbox.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Move messages to inbox using the new async function
        modified_messages = await move_to_inbox(
            user_id=str(user_id), message_ids=request.message_ids
        )

        return {
            "success": True,
            "moved_to_inbox": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Messages moved to inbox",
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to move messages to inbox: {str(e)}"
        )


@router.get("/gmail/thread/{thread_id}", summary="Get complete email thread")
async def get_thread(
    thread_id: str, current_user: dict = Depends(require_integration("gmail"))
):
    """
    Fetch a complete email thread with all messages.

    - **thread_id**: The Gmail thread ID to fetch

    Returns the thread with all its messages in chronological order.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get thread using the new async function
        thread = await fetch_thread(user_id=str(user_id), thread_id=thread_id)

        return {
            "thread_id": thread_id,
            "messages_count": len(thread.get("messages", [])),
            "thread": thread,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch email thread: {str(e)}"
        )


@router.post("/gmail/labels", summary="Create a new Gmail label")
@tiered_rate_limit("mail_actions")
async def create_label_route(
    request: LabelRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Create a new Gmail label.

    - **name**: Name of the label
    - **label_list_visibility**: Whether the label appears in the label list
    - **message_list_visibility**: Whether the label appears in the message list
    - **background_color**: Background color of the label (hex code)
    - **text_color**: Text color of the label (hex code)

    Returns the created label data.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Create label using the new async function
        new_label = await create_label(
            user_id=str(user_id),
            name=request.name,
            label_list_visibility=request.label_list_visibility or "labelShow",
            message_list_visibility=request.message_list_visibility or "show",
        )
        return new_label
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/gmail/labels/{label_id}", summary="Update an existing Gmail label")
@tiered_rate_limit("mail_actions")
async def update_label_route(
    label_id: str,
    request: LabelRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Update an existing Gmail label.

    - **label_id**: ID of the label to update
    - **name**: New name for the label
    - **label_list_visibility**: Whether the label appears in the label list
    - **message_list_visibility**: Whether the label appears in the message list
    - **background_color**: Background color of the label (hex code)
    - **text_color**: Text color of the label (hex code)

    Returns the updated label data.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Update label using the new async function
        updated_label = await update_label(
            user_id=str(user_id),
            label_id=label_id,
            name=request.name,
            label_list_visibility=request.label_list_visibility,
            message_list_visibility=request.message_list_visibility,
        )
        return updated_label
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/gmail/labels/{label_id}", summary="Delete a Gmail label")
@tiered_rate_limit("mail_actions")
async def delete_label_route(
    label_id: str, current_user: dict = Depends(require_integration("gmail"))
):
    """
    Delete a Gmail label.

    - **label_id**: ID of the label to delete

    Returns a success message.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Delete label using the new async function
        success = await delete_label(user_id=str(user_id), label_id=label_id)
        if success:
            return {"status": "success", "message": "Label deleted successfully"}
        else:
            return {"status": "error", "message": "Failed to delete label"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gmail/messages/apply-label", summary="Apply labels to messages")
@tiered_rate_limit("mail_actions")
async def apply_labels_route(
    request: ApplyLabelRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Apply one or more labels to specified messages.

    - **message_ids**: List of message IDs
    - **label_ids**: List of label IDs to apply

    Returns a list of modified messages.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Apply labels using the new async function
        modified_messages = await apply_labels(
            user_id=str(user_id),
            message_ids=request.message_ids,
            label_ids=request.label_ids,
        )

        return {
            "success": True,
            "modified_messages": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Labels applied successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gmail/messages/remove-label", summary="Remove labels from messages")
@tiered_rate_limit("mail_actions")
async def remove_labels_route(
    request: ApplyLabelRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Remove one or more labels from specified messages.

    - **message_ids**: List of message IDs
    - **label_ids**: List of label IDs to remove

    Returns a list of modified messages.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Remove labels using the new async function
        modified_messages = await remove_labels(
            user_id=str(user_id),
            message_ids=request.message_ids,
            label_ids=request.label_ids,
        )

        return {
            "success": True,
            "modified_messages": [msg["id"] for msg in modified_messages],
            "count": len(modified_messages),
            "status": "Labels removed successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gmail/drafts", summary="Create a new draft email")
@tiered_rate_limit("mail_actions")
async def create_draft_route(
    request: DraftRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Create a new Gmail draft email.

    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients
    - **is_html**: Whether the body is HTML content

    Returns the created draft data.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Create draft using the new async function
        draft = await create_draft(
            user_id=str(user_id),
            sender=current_user.get("email", ""),  # Use user's email from current_user
            to_list=request.to,
            subject=request.subject,
            body=request.body,
            is_html=request.is_html if request.is_html is not None else False,
            cc_list=request.cc,
            bcc_list=request.bcc,
        )

        return {
            "draft_id": draft.get("id"),
            "message_id": draft.get("message", {}).get("id"),
            "status": "Draft created successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/drafts", summary="List all draft emails")
async def list_drafts_route(
    max_results: int = 20,
    page_token: Optional[str] = None,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    List all Gmail draft emails.

    - **max_results**: Maximum number of drafts to return
    - **page_token**: Token for pagination

    Returns a list of drafts and a next page token if more results are available.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # List drafts using the new async function
        drafts = await list_drafts(
            user_id=str(user_id),
            max_results=max_results,
            page_token=page_token,
        )

        return drafts
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/drafts/{draft_id}", summary="Get a specific draft email")
async def get_draft_route(
    draft_id: str, current_user: dict = Depends(require_integration("gmail"))
):
    """
    Get a specific Gmail draft email.

    - **draft_id**: ID of the draft to retrieve

    Returns the draft data with message details.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Get draft using the new async function
        draft = await get_draft(user_id=str(user_id), draft_id=draft_id)

        return draft
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/gmail/drafts/{draft_id}", summary="Update a draft email")
@tiered_rate_limit("mail_actions")
async def update_draft_route(
    draft_id: str,
    request: DraftRequest,
    current_user: dict = Depends(require_integration("gmail")),
):
    """
    Update an existing Gmail draft email.

    - **draft_id**: ID of the draft to update
    - **to**: List of recipient email addresses
    - **subject**: Email subject
    - **body**: Email body
    - **cc**: Optional list of CC recipients
    - **bcc**: Optional list of BCC recipients
    - **is_html**: Whether the body is HTML content

    Returns the updated draft data.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Update draft using the new async function
        updated_draft = await update_draft(
            user_id=str(user_id),
            draft_id=draft_id,
            sender=current_user.get("email", ""),  # Use user's email from current_user
            to_list=request.to,
            subject=request.subject,
            body=request.body,
            is_html=request.is_html if request.is_html is not None else False,
            cc_list=request.cc,
            bcc_list=request.bcc,
        )

        return {
            "draft_id": updated_draft.get("id"),
            "message_id": updated_draft.get("message", {}).get("id"),
            "status": "Draft updated successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/gmail/drafts/{draft_id}", summary="Delete a draft email")
@tiered_rate_limit("mail_actions")
async def delete_draft_route(
    draft_id: str, current_user: dict = Depends(require_integration("gmail"))
):
    """
    Delete a Gmail draft email.

    - **draft_id**: ID of the draft to delete

    Returns a success message.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Delete draft using the new async function
        success = await delete_draft(user_id=str(user_id), draft_id=draft_id)

        if success:
            return {"status": "success", "message": "Draft deleted successfully"}
        else:
            return {"status": "error", "message": "Failed to delete draft"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/gmail/drafts/{draft_id}/send", summary="Send a draft email")
@tiered_rate_limit("mail_actions")
async def send_draft_route(
    draft_id: str, current_user: dict = Depends(require_integration("gmail"))
):
    """
    Send an existing Gmail draft email.

    - **draft_id**: ID of the draft to send

    Returns the sent message data.
    """
    try:
        user_id = current_user.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="User ID not found")

        # Send draft using the new async function
        sent_message = await send_draft(user_id=str(user_id), draft_id=draft_id)

        if sent_message.get("successful", True):
            return {
                "message_id": sent_message.get("id", ""),
                "thread_id": sent_message.get("threadId", ""),
                "status": "Draft sent successfully",
                "successful": True,
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=sent_message.get("error", "Failed to send draft"),
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gmail/importance-summaries", summary="Get email importance summaries")
async def get_email_importance_summaries(
    limit: int = 50,
    important_only: bool = False,
    current_user: dict = Depends(require_integration("gmail")),
) -> dict:
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
        return await get_importance_summaries_service(user_id, limit, important_only)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving email summaries: {str(e)}"
        )


@router.get(
    "/gmail/importance-summary/{message_id}",
    summary="Get single email importance summary",
)
async def get_single_email_importance_summary(
    message_id: str, current_user: dict = Depends(require_integration("gmail"))
) -> dict:
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

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving email summary: {str(e)}"
        )


@router.post(
    "/gmail/importance-summaries/bulk", summary="Get bulk email importance summaries"
)
async def get_bulk_email_importance_summaries(
    request: EmailActionRequest,
    current_user: dict = Depends(require_integration("gmail")),
) -> dict:
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
        return await get_bulk_importance_summaries_service(user_id, request.message_ids)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving bulk email summaries: {str(e)}"
        )
