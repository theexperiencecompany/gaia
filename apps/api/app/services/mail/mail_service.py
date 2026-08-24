import asyncio
import json
from typing import Any

from fastapi import UploadFile
from langchain_core.tools import StructuredTool

from app.constants.log_tags import LogTag
from app.models.mail_models import (
    GmailAttachmentPayload,
    GmailDraftsResponse,
    GmailEmailResult,
    GmailFetchEmailsData,
    GmailLabelsResult,
    GmailMessageResource,
    GmailMessagesResponse,
    GmailToolResult,
)
from app.services.composio.composio_service import (
    get_composio_service,
)
from app.utils.general_utils import transform_gmail_message
from shared.py.wide_events import MailContext, log


def get_gmail_tool(tool_name: str, user_id: str) -> StructuredTool | None:
    """Get a specific Gmail tool by name via ComposioService, or None if not found."""
    log.set(user={"id": user_id}, mail=MailContext(provider="gmail"))
    composio_service = get_composio_service()

    try:
        return composio_service.get_tool(
            tool_name, use_before_hook=False, use_after_hook=False, user_id=user_id
        )
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error getting Gmail tool",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
            user_id=user_id,
        )
        return None


async def invoke_gmail_tool(
    user_id: str, tool_name: str, parameters: dict[str, Any]
) -> GmailToolResult:
    """Invoke a specific Gmail tool with the given parameters.

    ``parameters`` stays a loose mapping on purpose: every Gmail tool accepts a
    different argument set, and Composio validates it against the tool's own schema.
    """
    try:
        tool = get_gmail_tool(tool_name, user_id)

        if not tool:
            return GmailToolResult(error=f"Tool {tool_name} not found", successful=False)

        result = await tool.ainvoke(parameters)
        # BaseTool.ainvoke is typed Any (arbitrary tool output); this is the
        # provider boundary, so validate Composio's response before it travels on.
        return GmailToolResult.model_validate(result)
    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error invoking Gmail tool for user",
            tool_name=tool_name,
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return GmailToolResult(error=str(e), successful=False)


def _process_attachments(attachments: list[UploadFile]) -> list[GmailAttachmentPayload]:
    """Process UploadFile objects into format expected by Composio."""
    processed: list[GmailAttachmentPayload] = [
        {
            "filename": att.filename,
            "content": att.file.read(),
            "content_type": att.content_type,
        }
        for att in attachments
    ]
    # Reset file pointers
    for att in attachments:
        att.file.seek(0)
    return processed


async def send_email(
    user_id: str,
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    extra_recipients: list[str] | None = None,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
    attachments: list[UploadFile] | None = None,
) -> GmailToolResult:
    """Send an email via Composio Gmail tools.

    Uses GMAIL_REPLY_TO_THREAD when thread_id is given, else GMAIL_SEND_EMAIL.
    Body is always delivered as HTML; the Composio before-hook converts Markdown
    so Gmail renders formatting instead of literal ``**`` / ``###``.
    """
    log.set(
        user={"id": user_id},
        mail=MailContext(operation="send", provider="gmail"),
    )
    try:
        # Determine tool and body parameter name
        is_reply = bool(thread_id)
        tool_name = "GMAIL_REPLY_TO_THREAD" if is_reply else "GMAIL_SEND_EMAIL"
        body_param = "message_body" if is_reply else "body"

        # Build parameters. The Composio before-hook (gmail_compose_before_hook)
        # normalises body → HTML and sets is_html=True for every compose tool,
        # so callers can hand us either Markdown or HTML and Gmail will render
        # consistently.
        parameters: dict[str, Any] = {
            "recipient_email": to,
            "extra_recipients": extra_recipients or [],
            body_param: body,
            "subject": subject,
        }

        # Add thread_id for replies
        if is_reply:
            parameters["thread_id"] = thread_id

        # Add optional parameters
        if cc_list:
            parameters["cc"] = cc_list
        if bcc_list:
            parameters["bcc"] = bcc_list
        if attachments:
            parameters["attachments"] = await asyncio.to_thread(_process_attachments, attachments)

        log.info(
            f"{LogTag.MAIL} Sending email via Gmail tool",
            tool_name=tool_name,
            is_reply=is_reply,
            thread_id=thread_id,
            to=to,
        )

        result = await invoke_gmail_tool(user_id, tool_name, parameters)
        if not result.successful:
            log.error(
                f"{LogTag.MAIL} Error from tool",
                tool_name=tool_name,
                error=result.error,
            )
        log.set_ns("mail", success=result.successful)
        return result

    except Exception as e:
        log.error(
            f"{LogTag.MAIL} Error sending email for user",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        log.set_ns("mail", success=False)
        return GmailToolResult(error=str(e), successful=False)


async def modify_message_labels(
    user_id: str,
    message_ids: list[str],
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> list[GmailMessageResource]:
    """Modify the labels of Gmail messages via Composio Gmail tools."""
    if not add_labels and not remove_labels:
        return []

    add_labels = add_labels or []
    remove_labels = remove_labels or []
    results: list[GmailMessageResource] = []

    # Add labels if specified
    if add_labels:
        try:
            add_params = {
                "message_ids": message_ids,
                "label_ids": add_labels,
            }
            add_result = await invoke_gmail_tool(user_id, "GMAIL_ADD_LABEL_TO_EMAIL", add_params)
            if add_result.successful:
                results.extend(
                    GmailMessageResource.model_validate(msg) for msg in add_result.messages or []
                )
        except Exception as e:
            log.error(
                f"{LogTag.MAIL} Error adding labels to messages",
                add_labels=add_labels,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    # Remove labels if specified
    if remove_labels:
        try:
            remove_params = {
                "message_ids": message_ids,
                "label_ids": remove_labels,
            }
            remove_result = await invoke_gmail_tool(user_id, "GMAIL_REMOVE_LABEL", remove_params)
            if remove_result.successful:
                # Only extend if we didn't already get results from adding labels
                if not add_labels:
                    results.extend(
                        GmailMessageResource.model_validate(msg)
                        for msg in remove_result.messages or []
                    )
        except Exception as e:
            log.error(
                f"{LogTag.MAIL} Error removing labels from messages",
                remove_labels=remove_labels,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    return results


async def mark_messages_as_read(user_id: str, message_ids: list[str]) -> list[GmailMessageResource]:
    """Mark Gmail messages as read by removing the UNREAD label."""
    return await modify_message_labels(user_id, message_ids, remove_labels=["UNREAD"])


async def mark_messages_as_unread(
    user_id: str, message_ids: list[str]
) -> list[GmailMessageResource]:
    """Mark Gmail messages as unread by adding the UNREAD label."""
    return await modify_message_labels(user_id, message_ids, add_labels=["UNREAD"])


async def star_messages(user_id: str, message_ids: list[str]) -> list[GmailMessageResource]:
    """Star Gmail messages by adding the STARRED label."""
    log.info(f"{LogTag.MAIL} Starring messages", message_ids_count=len(message_ids))
    return await modify_message_labels(user_id, message_ids, add_labels=["STARRED"])


async def unstar_messages(user_id: str, message_ids: list[str]) -> list[GmailMessageResource]:
    """Unstar Gmail messages by removing the STARRED label."""
    log.info(f"{LogTag.MAIL} Unstarring messages", message_ids_count=len(message_ids))
    return await modify_message_labels(user_id, message_ids, remove_labels=["STARRED"])


async def trash_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Move Gmail messages to trash.

    Each entry is the raw Composio envelope, not a Gmail message resource, so it
    stays an untyped payload: the route reads ``msg["id"]`` off it, which the
    envelope does not carry. Returning a real message resource here would change
    what the route receives, so that mismatch is left for a deliberate fix.
    """
    log.info(f"{LogTag.MAIL} Moving messages to trash", message_ids_count=len(message_ids))
    results: list[dict[str, Any]] = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(user_id, "GMAIL_TRASH_MESSAGE", parameters)
            if result.successful:
                results.append(result.as_payload())
            else:
                log.error(
                    f"{LogTag.MAIL} Error trashing message",
                    message_id=message_id,
                    error=result.error,
                )
        except Exception as e:
            log.error(
                f"{LogTag.MAIL} Error trashing message",
                message_id=message_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    return results


async def untrash_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Restore Gmail messages from trash — entries are raw envelopes, see ``trash_messages``."""
    log.info(f"{LogTag.MAIL} Restoring messages from trash", message_ids_count=len(message_ids))
    results: list[dict[str, Any]] = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(user_id, "GMAIL_UNTRASH_MESSAGE", parameters)
            if result.successful:
                results.append(result.as_payload())
            else:
                log.error(
                    f"{LogTag.MAIL} Error untrashing message",
                    message_id=message_id,
                    error=result.error,
                )
        except Exception as e:
            log.error(
                f"{LogTag.MAIL} Error untrashing message",
                message_id=message_id,
                error=str(e),
                error_type=type(e).__name__,
                user_id=user_id,
            )

    return results


async def archive_messages(user_id: str, message_ids: list[str]) -> list[GmailMessageResource]:
    """Archive Gmail messages by removing the INBOX label."""
    log.info(f"{LogTag.MAIL} Archiving messages", message_ids_count=len(message_ids))
    return await modify_message_labels(user_id, message_ids, remove_labels=["INBOX"])


async def move_to_inbox(user_id: str, message_ids: list[str]) -> list[GmailMessageResource]:
    """Move Gmail messages to inbox by adding the INBOX label."""
    log.info(f"{LogTag.MAIL} Moving messages to inbox", message_ids_count=len(message_ids))
    return await modify_message_labels(user_id, message_ids, add_labels=["INBOX"])


async def fetch_thread(user_id: str, thread_id: str) -> GmailToolResult:
    """Fetch a complete email thread with all messages."""
    log.set(user={"id": user_id}, mail=MailContext(operation="fetch", provider="gmail"))
    log.info(f"{LogTag.MAIL} Fetching thread with ID", thread_id=thread_id)
    try:
        parameters = {
            "thread_id": thread_id,
        }

        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", parameters)

        if result.successful:
            # Transform messages in the thread for easier frontend processing
            if result.messages is not None:
                messages = [transform_gmail_message(msg) for msg in result.messages]

                # Sort messages by date (oldest first)
                messages.sort(key=lambda msg: int(msg.get("internalDate", 0)))
                result.messages = messages

            log.set_ns("mail", message_count=len(result.messages or []), success=True)
            return result
        log.error(f"{LogTag.MAIL} Error from GMAIL_FETCH_MESSAGE_BY_THREAD_ID", error=result.error)
        log.set_ns("mail", success=False)
        return GmailToolResult(messages=[])

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error fetching thread",
            thread_id=thread_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        log.set_ns("mail", success=False)
        return GmailToolResult(messages=[])


async def search_messages(
    user_id: str,
    query: str | None = None,
    max_results: int = 20,
    page_token: str | None = None,
    message_format: str | None = None,
    include_payload: bool | None = None,
    verbose: bool | None = None,
) -> GmailMessagesResponse:
    """
    Search Gmail messages using Composio Gmail tool.

    Pass message_format="metadata" with include_payload=False and verbose=False to
    skip body decode and bypass GMAIL_FULL_FETCH_HARD_LIMIT.
    """
    log.set(user={"id": user_id}, mail=MailContext(operation="fetch", provider="gmail"))
    try:
        parameters: dict[str, Any] = {
            "query": query or "",
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token
        if message_format is not None:
            parameters["format"] = message_format
        if include_payload is not None:
            parameters["include_payload"] = include_payload
        if verbose is not None:
            parameters["verbose"] = verbose

        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_EMAILS", parameters)

        if result.successful:
            data = GmailFetchEmailsData.model_validate(result.data or {})
            log.set_ns("mail", result_count=len(data.messages), success=True)
            return GmailMessagesResponse(
                messages=[transform_gmail_message(msg) for msg in data.messages],
                next_page_token=data.next_page_token,
            )
        log.set_ns("mail", success=False)
        return GmailMessagesResponse(messages=[])

    except Exception:
        log.set_ns("mail", success=False)
        return GmailMessagesResponse(messages=[])


async def create_label(
    user_id: str,
    name: str,
    label_list_visibility: str = "labelShow",
    message_list_visibility: str = "show",
    background_color: str | None = None,
    text_color: str | None = None,
) -> GmailToolResult:
    """Create a new Gmail label."""
    log.info(f"{LogTag.MAIL} Creating new label", name=name)
    try:
        parameters = {
            "name": name,
            "label_list_visibility": label_list_visibility,
            "message_list_visibility": message_list_visibility,
        }

        # Add color parameters if provided
        if background_color or text_color:
            color_data = {}
            if background_color:
                color_data["background_color"] = background_color
            if text_color:
                color_data["text_color"] = text_color
            parameters["color"] = json.dumps(color_data)

        return await invoke_gmail_tool(user_id, "GMAIL_CREATE_LABEL", parameters)
    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error creating label",
            name=name,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailToolResult(error=str(error), successful=False)


async def update_label(
    user_id: str,
    label_id: str,
    name: str | None = None,
    label_list_visibility: str | None = None,
    message_list_visibility: str | None = None,
    background_color: str | None = None,
    text_color: str | None = None,
) -> GmailToolResult:
    """Update an existing Gmail label."""
    log.info(f"{LogTag.MAIL} Updating label", label_id=label_id)
    try:
        parameters = {
            "label_id": label_id,
        }

        # Add parameters if provided
        if name:
            parameters["name"] = name
        if label_list_visibility:
            parameters["label_list_visibility"] = label_list_visibility
        if message_list_visibility:
            parameters["message_list_visibility"] = message_list_visibility

        # Add color parameters if provided
        if background_color or text_color:
            color_data = {}
            if background_color:
                color_data["background_color"] = background_color
            if text_color:
                color_data["text_color"] = text_color
            parameters["color"] = json.dumps(color_data)

        return await invoke_gmail_tool(user_id, "GMAIL_PATCH_LABEL", parameters)
    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error updating label",
            label_id=label_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailToolResult(error=str(error), successful=False)


async def delete_label(user_id: str, label_id: str) -> bool:
    """Delete a Gmail label."""
    log.info(f"{LogTag.MAIL} Deleting label", label_id=label_id)
    try:
        parameters = {"label_id": label_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_LABEL", parameters)
        return result.successful
    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error deleting label",
            label_id=label_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return False


async def apply_labels(
    user_id: str, message_ids: list[str], label_ids: list[str]
) -> list[GmailMessageResource]:
    """Apply one or more labels to the specified messages."""
    log.info(
        f"{LogTag.MAIL} Applying labels to messages",
        label_ids=label_ids,
        message_ids_count=len(message_ids),
    )
    return await modify_message_labels(user_id, message_ids, add_labels=label_ids)


async def remove_labels(
    user_id: str, message_ids: list[str], label_ids: list[str]
) -> list[GmailMessageResource]:
    """Remove one or more labels from the specified messages."""
    log.info(
        f"{LogTag.MAIL} Removing labels from messages",
        label_ids=label_ids,
        message_ids_count=len(message_ids),
    )
    return await modify_message_labels(user_id, message_ids, remove_labels=label_ids)


async def create_draft(
    user_id: str,
    to_list: list[str],
    subject: str,
    body: str,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
) -> GmailToolResult:
    """Create a new Gmail draft.

    Body is always sent as HTML; the Composio before-hook converts Markdown.
    """
    log.info(f"{LogTag.MAIL} Creating draft email", to=to_list)
    try:
        parameters: dict[str, Any] = {
            "to": to_list,
            "subject": subject,
            "body": body,
        }

        # Add optional parameters if provided
        if cc_list:
            parameters["cc"] = cc_list
        if bcc_list:
            parameters["bcc"] = bcc_list

        return await invoke_gmail_tool(user_id, "GMAIL_CREATE_EMAIL_DRAFT", parameters)
    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error creating draft",
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailToolResult(error=str(error), successful=False)


async def list_drafts(
    user_id: str, max_results: int = 20, page_token: str | None = None
) -> GmailDraftsResponse:
    """List Gmail draft messages."""
    log.info(f"{LogTag.MAIL} Listing drafts, max_results", max_results=max_results)
    try:
        parameters: dict[str, Any] = {
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token

        result = await invoke_gmail_tool(user_id, "GMAIL_LIST_DRAFTS", parameters)

        if result.successful:
            # Transform draft messages if needed
            detailed_drafts = []
            for draft in result.drafts or []:
                if "message" in draft:
                    draft["message"] = transform_gmail_message(draft["message"])
                detailed_drafts.append(draft)

            return GmailDraftsResponse(
                drafts=detailed_drafts,
                next_page_token=result.next_page_token,
            )
        log.error(f"{LogTag.MAIL} Error from GMAIL_LIST_DRAFTS", error=result.error)
        return GmailDraftsResponse(drafts=[])

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error listing drafts",
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailDraftsResponse(drafts=[])


async def get_draft(user_id: str, draft_id: str) -> GmailToolResult:
    """Get a specific Gmail draft."""
    log.info(f"{LogTag.MAIL} Fetching draft", draft_id=draft_id)
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_GET_DRAFT", parameters)

        if result.successful:
            # Transform the message data if present
            if result.message is not None:
                result.message = transform_gmail_message(result.message)
            return result
        log.error(f"{LogTag.MAIL} Error from GMAIL_GET_DRAFT", error=result.error)
        return GmailToolResult(error=result.error, successful=False)

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error fetching draft",
            draft_id=draft_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailToolResult(error=str(error), successful=False)


async def update_draft(
    user_id: str,
    draft_id: str,
    to_list: list[str],
    subject: str,
    body: str,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
) -> GmailToolResult:
    """Update an existing Gmail draft.

    Body is always sent as HTML; the Composio before-hook converts Markdown.
    """
    log.info(f"{LogTag.MAIL} Updating draft", draft_id=draft_id)
    try:
        parameters = {
            "draft_id": draft_id,
            "to": to_list,
            "subject": subject,
            "body": body,
        }

        # Add optional parameters if provided
        if cc_list:
            parameters["cc"] = cc_list
        if bcc_list:
            parameters["bcc"] = bcc_list

        result = await invoke_gmail_tool(user_id, "GMAIL_UPDATE_DRAFT", parameters)

        if result.successful:
            return result
        log.error(f"{LogTag.MAIL} Error from GMAIL_UPDATE_DRAFT", error=result.error)
        return GmailToolResult(error=result.error, successful=False)

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error updating draft",
            draft_id=draft_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailToolResult(error=str(error), successful=False)


async def delete_draft(user_id: str, draft_id: str) -> bool:
    """Delete a Gmail draft."""
    log.info(f"{LogTag.MAIL} Deleting draft", draft_id=draft_id)
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_DRAFT", parameters)
        return result.successful
    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error deleting draft",
            draft_id=draft_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return False


async def send_draft(user_id: str, draft_id: str) -> GmailToolResult:
    """Send an existing Gmail draft."""
    log.set(user={"id": user_id}, mail=MailContext(operation="send", provider="gmail"))
    log.info(f"{LogTag.MAIL} Sending draft", draft_id=draft_id)
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_SEND_DRAFT", parameters)

        if result.successful:
            log.set_ns("mail", success=True)
            return result
        log.error(f"{LogTag.MAIL} Error from GMAIL_SEND_DRAFT", error=result.error)
        log.set_ns("mail", success=False)
        return GmailToolResult(error=result.error, successful=False)

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error sending draft",
            draft_id=draft_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        log.set_ns("mail", success=False)
        return GmailToolResult(error=str(error), successful=False)


async def list_labels(user_id: str) -> GmailLabelsResult:
    """List all Gmail labels."""
    log.info(f"{LogTag.MAIL} Listing Gmail labels for user", user_id=user_id)
    try:
        parameters: dict[str, Any] = {}  # No parameters needed for listing labels
        result = await invoke_gmail_tool(user_id, "GMAIL_LIST_LABELS", parameters)

        if result.successful:
            labels = result.labels or []
            return GmailLabelsResult(
                success=True,
                labels=labels,
                count=len(labels),
            )
        log.error(f"{LogTag.MAIL} Error from GMAIL_LIST_LABELS", error=result.error)
        return GmailLabelsResult(success=False, error=result.error)

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error listing Gmail labels",
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        return GmailLabelsResult(success=False, error=str(error))


async def get_email_by_id(user_id: str, message_id: str) -> GmailEmailResult:
    """Get a Gmail message by its ID."""
    log.set(user={"id": user_id}, mail=MailContext(operation="fetch", provider="gmail"))
    log.info(f"{LogTag.MAIL} Fetching email with ID", message_id=message_id)
    try:
        parameters = {"message_id": message_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", parameters)

        if result.successful:
            # Transform the message data for easier frontend processing
            transformed_message = transform_gmail_message(result.as_payload())
            log.set_ns("mail", result_count=1, success=True)
            return GmailEmailResult(success=True, message=transformed_message)
        log.error(f"{LogTag.MAIL} Error from GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", error=result.error)
        log.set_ns("mail", success=False)
        return GmailEmailResult(success=False, error=result.error)

    except Exception as error:
        log.error(
            f"{LogTag.MAIL} Error fetching email",
            message_id=message_id,
            error=str(error),
            error_type=type(error).__name__,
            user_id=user_id,
        )
        log.set_ns("mail", success=False)
        return GmailEmailResult(success=False, error=str(error))
