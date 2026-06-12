import json
from typing import Any

from fastapi import UploadFile

from app.services.composio.composio_service import (
    get_composio_service,
)
from app.utils.general_utils import transform_gmail_message
from shared.py.wide_events import log


def get_gmail_tool(tool_name: str, user_id: str):
    """Get a specific Gmail tool by name via ComposioService, or None if not found."""
    log.set(mail_gmail_tool=tool_name, mail_user_id=user_id)
    composio_service = get_composio_service()

    try:
        return composio_service.get_tool(
            tool_name, use_before_hook=False, use_after_hook=False, user_id=user_id
        )
    except Exception as e:
        log.error(f"Error getting Gmail tool {tool_name}: {e}")
        return None


async def invoke_gmail_tool(
    user_id: str, tool_name: str, parameters: dict[str, Any]
) -> dict[str, Any]:
    """Invoke a specific Gmail tool with the given parameters."""
    try:
        tool = get_gmail_tool(tool_name, user_id)

        if not tool:
            return {"error": f"Tool {tool_name} not found", "successful": False}

        result = await tool.ainvoke(parameters)
        return result
    except Exception as e:
        log.error(f"Error invoking Gmail tool {tool_name} for user {user_id}: {e}")
        return {"error": str(e), "successful": False}


def _process_attachments(attachments: list[UploadFile]) -> list[dict[str, Any]]:
    """Process UploadFile objects into format expected by Composio."""
    processed = [
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
    extra_recipients: list[str] = [],
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
    attachments: list[UploadFile] | None = None,
) -> dict[str, Any]:
    """Send an email via Composio Gmail tools.

    Uses GMAIL_REPLY_TO_THREAD when thread_id is given, else GMAIL_SEND_EMAIL.
    Body is always delivered as HTML; the Composio before-hook converts Markdown
    so Gmail renders formatting instead of literal ``**`` / ``###``.
    """
    log.set(
        mail_user_id=user_id,
        mail_recipient=to,
        mail_subject=subject,
        mail_is_reply=bool(thread_id),
        mail_thread_id=thread_id,
        mail_has_attachments=bool(attachments),
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
            "extra_recipients": extra_recipients,
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
            parameters["attachments"] = _process_attachments(attachments)

        log.info(
            f"Using {tool_name} to {'reply to thread ' + (thread_id or '') if is_reply else 'send new email to ' + to}"
        )

        return await invoke_gmail_tool(user_id, tool_name, parameters)

    except Exception as e:
        log.error(f"Error sending email for user {user_id}: {e}")
        return {"error": str(e), "successful": False}


async def modify_message_labels(
    user_id: str,
    message_ids: list[str],
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Modify the labels of Gmail messages via Composio Gmail tools."""
    if not add_labels and not remove_labels:
        return []

    add_labels = add_labels or []
    remove_labels = remove_labels or []
    results = []

    # Add labels if specified
    if add_labels:
        try:
            add_params = {
                "message_ids": message_ids,
                "label_ids": add_labels,
            }
            add_result = await invoke_gmail_tool(user_id, "GMAIL_ADD_LABEL_TO_EMAIL", add_params)
            if add_result.get("successful", True):
                results.extend(add_result.get("messages", []))
        except Exception as e:
            log.error(f"Error adding labels {add_labels} to messages: {e}")

    # Remove labels if specified
    if remove_labels:
        try:
            remove_params = {
                "message_ids": message_ids,
                "label_ids": remove_labels,
            }
            remove_result = await invoke_gmail_tool(user_id, "GMAIL_REMOVE_LABEL", remove_params)
            if remove_result.get("successful", True):
                # Only extend if we didn't already get results from adding labels
                if not add_labels:
                    results.extend(remove_result.get("messages", []))
        except Exception as e:
            log.error(f"Error removing labels {remove_labels} from messages: {e}")

    return results


async def mark_messages_as_read(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Mark Gmail messages as read by removing the UNREAD label."""
    return await modify_message_labels(user_id, message_ids, remove_labels=["UNREAD"])


async def mark_messages_as_unread(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Mark Gmail messages as unread by adding the UNREAD label."""
    return await modify_message_labels(user_id, message_ids, add_labels=["UNREAD"])


async def star_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Star Gmail messages by adding the STARRED label."""
    log.info(f"Starring {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, add_labels=["STARRED"])


async def unstar_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Unstar Gmail messages by removing the STARRED label."""
    log.info(f"Unstarring {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=["STARRED"])


async def trash_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Move Gmail messages to trash."""
    log.info(f"Moving {len(message_ids)} messages to trash")
    results = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(user_id, "GMAIL_TRASH_MESSAGE", parameters)
            if result.get("successful", True):
                results.append(result)
            else:
                log.error(f"Error trashing message {message_id}: {result.get('error')}")
        except Exception as e:
            log.error(f"Error trashing message {message_id}: {e}")

    return results


async def untrash_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Restore Gmail messages from trash."""
    log.info(f"Restoring {len(message_ids)} messages from trash")
    results = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(user_id, "GMAIL_UNTRASH_MESSAGE", parameters)
            if result.get("successful", True):
                results.append(result)
            else:
                log.error(f"Error untrashing message {message_id}: {result.get('error')}")
        except Exception as e:
            log.error(f"Error untrashing message {message_id}: {e}")

    return results


async def archive_messages(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Archive Gmail messages by removing the INBOX label."""
    log.info(f"Archiving {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=["INBOX"])


async def move_to_inbox(user_id: str, message_ids: list[str]) -> list[dict[str, Any]]:
    """Move Gmail messages to inbox by adding the INBOX label."""
    log.info(f"Moving {len(message_ids)} messages to inbox")
    return await modify_message_labels(user_id, message_ids, add_labels=["INBOX"])


async def fetch_thread(user_id: str, thread_id: str) -> dict[str, Any]:
    """Fetch a complete email thread with all messages."""
    log.info(f"Fetching thread with ID: {thread_id}")
    try:
        parameters = {
            "thread_id": thread_id,
        }

        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", parameters)

        if result.get("successful", True):
            thread = result

            # Transform messages in the thread for easier frontend processing
            if "messages" in thread:
                thread["messages"] = [transform_gmail_message(msg) for msg in thread["messages"]]

                # Sort messages by date (oldest first)
                thread["messages"].sort(key=lambda msg: int(msg.get("internalDate", 0)))

            return thread
        log.error(f"Error from GMAIL_FETCH_MESSAGE_BY_THREAD_ID: {result.get('error')}")
        return {"messages": []}

    except Exception as error:
        log.error(f"Error fetching thread {thread_id}: {error}")
        return {"messages": []}


async def search_messages(
    user_id: str,
    query: str | None = None,
    max_results: int = 20,
    page_token: str | None = None,
    format: str | None = None,
    include_payload: bool | None = None,
    verbose: bool | None = None,
) -> dict[str, Any]:
    """
    Search Gmail messages using Composio Gmail tool.

    Pass format="metadata" with include_payload=False and verbose=False to
    skip body decode and bypass GMAIL_FULL_FETCH_HARD_LIMIT.
    """
    try:
        parameters: dict[str, Any] = {
            "query": query or "",
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token
        if format is not None:
            parameters["format"] = format
        if include_payload is not None:
            parameters["include_payload"] = include_payload
        if verbose is not None:
            parameters["verbose"] = verbose

        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_EMAILS", parameters)

        if result.get("successful", True):
            # Transform messages if needed
            data = result.get("data", {})
            messages = data.get("messages", [])
            return {
                "messages": [transform_gmail_message(msg) for msg in messages],
                "nextPageToken": data.get("nextPageToken"),
            }
        return {"messages": [], "nextPageToken": None}

    except Exception:
        return {"messages": [], "nextPageToken": None}


async def create_label(
    user_id: str,
    name: str,
    label_list_visibility: str = "labelShow",
    message_list_visibility: str = "show",
    background_color: str | None = None,
    text_color: str | None = None,
) -> dict[str, Any]:
    """Create a new Gmail label."""
    log.info(f"Creating new label: {name}")
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

        result = await invoke_gmail_tool(user_id, "GMAIL_CREATE_LABEL", parameters)
        return result
    except Exception as error:
        log.error(f"Error creating label {name}: {error}")
        return {"error": str(error), "successful": False}


async def update_label(
    user_id: str,
    label_id: str,
    name: str | None = None,
    label_list_visibility: str | None = None,
    message_list_visibility: str | None = None,
    background_color: str | None = None,
    text_color: str | None = None,
) -> dict[str, Any]:
    """Update an existing Gmail label."""
    log.info(f"Updating label {label_id}")
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

        result = await invoke_gmail_tool(user_id, "GMAIL_PATCH_LABEL", parameters)
        return result
    except Exception as error:
        log.error(f"Error updating label {label_id}: {error}")
        return {"error": str(error), "successful": False}


async def delete_label(user_id: str, label_id: str) -> bool:
    """Delete a Gmail label."""
    log.info(f"Deleting label {label_id}")
    try:
        parameters = {"label_id": label_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_LABEL", parameters)
        return result.get("successful", True)
    except Exception as error:
        log.error(f"Error deleting label {label_id}: {error}")
        return False


async def apply_labels(
    user_id: str, message_ids: list[str], label_ids: list[str]
) -> list[dict[str, Any]]:
    """Apply one or more labels to the specified messages."""
    log.info(f"Applying labels {label_ids} to {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, add_labels=label_ids)


async def remove_labels(
    user_id: str, message_ids: list[str], label_ids: list[str]
) -> list[dict[str, Any]]:
    """Remove one or more labels from the specified messages."""
    log.info(f"Removing labels {label_ids} from {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=label_ids)


async def create_draft(
    user_id: str,
    to_list: list[str],
    subject: str,
    body: str,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new Gmail draft.

    Body is always sent as HTML; the Composio before-hook converts Markdown.
    """
    log.info(f"Creating draft email to {to_list} with subject: {subject}")
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

        result = await invoke_gmail_tool(user_id, "GMAIL_CREATE_EMAIL_DRAFT", parameters)
        return result
    except Exception as error:
        log.error(f"Error creating draft: {error}")
        return {"error": str(error), "successful": False}


async def list_drafts(
    user_id: str, max_results: int = 20, page_token: str | None = None
) -> dict[str, Any]:
    """List Gmail draft messages."""
    log.info(f"Listing drafts, max_results={max_results}")
    try:
        parameters: dict[str, Any] = {
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token

        result = await invoke_gmail_tool(user_id, "GMAIL_LIST_DRAFTS", parameters)

        if result.get("successful", True):
            drafts = result.get("drafts", [])

            # Transform draft messages if needed
            detailed_drafts = []
            for draft in drafts:
                if "message" in draft:
                    draft["message"] = transform_gmail_message(draft["message"])
                detailed_drafts.append(draft)

            return {
                "drafts": detailed_drafts,
                "nextPageToken": result.get("nextPageToken"),
            }
        log.error(f"Error from GMAIL_LIST_DRAFTS: {result.get('error')}")
        return {"drafts": [], "nextPageToken": None}

    except Exception as error:
        log.error(f"Error listing drafts: {error}")
        return {"drafts": [], "nextPageToken": None}


async def get_draft(user_id: str, draft_id: str) -> dict[str, Any]:
    """Get a specific Gmail draft."""
    log.info(f"Fetching draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_GET_DRAFT", parameters)

        if result.get("successful", True):
            # Transform the message data if present
            if "message" in result:
                result["message"] = transform_gmail_message(result["message"])
            return result
        log.error(f"Error from GMAIL_GET_DRAFT: {result.get('error')}")
        return {"error": result.get("error"), "successful": False}

    except Exception as error:
        log.error(f"Error fetching draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def update_draft(
    user_id: str,
    draft_id: str,
    to_list: list[str],
    subject: str,
    body: str,
    cc_list: list[str] | None = None,
    bcc_list: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing Gmail draft.

    Body is always sent as HTML; the Composio before-hook converts Markdown.
    """
    log.info(f"Updating draft {draft_id}")
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

        if result.get("successful", True):
            return result
        log.error(f"Error from GMAIL_UPDATE_DRAFT: {result.get('error')}")
        return {"error": result.get("error"), "successful": False}

    except Exception as error:
        log.error(f"Error updating draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def delete_draft(user_id: str, draft_id: str) -> bool:
    """Delete a Gmail draft."""
    log.info(f"Deleting draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_DRAFT", parameters)
        return result.get("successful", True)
    except Exception as error:
        log.error(f"Error deleting draft {draft_id}: {error}")
        return False


async def send_draft(user_id: str, draft_id: str) -> dict[str, Any]:
    """Send an existing Gmail draft."""
    log.info(f"Sending draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_SEND_DRAFT", parameters)

        if result.get("successful", True):
            return result
        log.error(f"Error from GMAIL_SEND_DRAFT: {result.get('error')}")
        return {"error": result.get("error"), "successful": False}

    except Exception as error:
        log.error(f"Error sending draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def list_labels(user_id: str) -> dict[str, Any]:
    """List all Gmail labels."""
    log.info(f"Listing Gmail labels for user {user_id}")
    try:
        parameters: dict[str, Any] = {}  # No parameters needed for listing labels
        result = await invoke_gmail_tool(user_id, "GMAIL_LIST_LABELS", parameters)

        if result.get("successful", True):
            labels = result.get("labels", [])
            return {
                "success": True,
                "labels": labels,
                "count": len(labels),
            }
        log.error(f"Error from GMAIL_LIST_LABELS: {result.get('error')}")
        return {
            "success": False,
            "error": result.get("error"),
            "labels": [],
        }

    except Exception as error:
        log.error(f"Error listing Gmail labels: {error}")
        return {
            "success": False,
            "error": str(error),
            "labels": [],
        }


async def get_email_by_id(user_id: str, message_id: str) -> dict[str, Any]:
    """Get a Gmail message by its ID."""
    log.info(f"Fetching email with ID: {message_id}")
    try:
        parameters = {"message_id": message_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", parameters)

        if result.get("successful", True):
            # Transform the message data for easier frontend processing
            transformed_message = transform_gmail_message(result)
            return {
                "success": True,
                "message": transformed_message,
            }
        log.error(f"Error from GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID: {result.get('error')}")
        return {
            "success": False,
            "error": result.get("error"),
            "message": None,
        }

    except Exception as error:
        log.error(f"Error fetching email {message_id}: {error}")
        return {
            "success": False,
            "error": str(error),
            "message": None,
        }
