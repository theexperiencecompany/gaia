import json
import time
from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.services.composio.composio_service import (
    get_composio_service,
)
from app.utils.general_utils import transform_gmail_message
from fastapi import UploadFile


def get_gmail_tool(tool_name: str, user_id: str):
    """
    Get a specific Gmail tool by name with caching using ComposioService.

    Args:
        tool_name: Name of the Gmail tool to retrieve

    Returns:
        The specific Gmail tool or None if not found
    """
    composio_service = get_composio_service()

    try:
        return composio_service.get_tool(
            tool_name, use_before_hook=False, use_after_hook=False, user_id=user_id
        )
    except Exception as e:
        logger.error(f"Error getting Gmail tool {tool_name}: {e}")
        return None


async def invoke_gmail_tool(
    user_id: str, tool_name: str, parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Invoke a specific Gmail tool with the given parameters asynchronously.

    Args:
        user_id: User ID for Composio authentication
        tool_name: Name of the Gmail tool to invoke
        parameters: Parameters to pass to the tool

    Returns:
        Response from the tool execution
    """
    try:
        tool = get_gmail_tool(tool_name, user_id)

        if not tool:
            return {"error": f"Tool {tool_name} not found", "successful": False}

        result = await tool.ainvoke(parameters)
        return result
    except Exception as e:
        logger.error(f"Error invoking Gmail tool {tool_name} for user {user_id}: {e}")
        return {"error": str(e), "successful": False}


def _process_attachments(attachments: List[UploadFile]) -> List[Dict[str, Any]]:
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
    thread_id: Optional[str] = None,
    is_html: bool = False,
    extra_recipients: List[str] = [],
    cc_list: Optional[List[str]] = None,
    bcc_list: Optional[List[str]] = None,
    attachments: Optional[List[UploadFile]] = None,
) -> Dict[str, Any]:
    """
    Send an email using Composio Gmail tools.

    Automatically chooses between GMAIL_SEND_EMAIL (for new emails) and
    GMAIL_REPLY_TO_THREAD (when thread_id is provided) to handle both
    new emails and thread replies appropriately.

    Args:
        user_id: User ID for Composio authentication
        to: Primary recipient email address
        subject: Email subject
        body: Email body content
        thread_id: Optional thread ID - if provided, uses GMAIL_REPLY_TO_THREAD
        is_html: Whether the body is HTML content
        extra_recipients: Additional recipient email addresses
        cc_list: Optional list of CC recipients
        bcc_list: Optional list of BCC recipients
        attachments: Optional list of files to attach

    Returns:
        Sent message data from the appropriate Composio Gmail tool
    """
    try:
        # Determine tool and body parameter name
        is_reply = bool(thread_id)
        tool_name = "GMAIL_REPLY_TO_THREAD" if is_reply else "GMAIL_SEND_EMAIL"
        body_param = "message_body" if is_reply else "body"

        # Build parameters
        parameters: Dict[str, Any] = {
            "recipient_email": to,
            "extra_recipients": extra_recipients,
            body_param: body,
            "subject": subject,
            "is_html": is_html,
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

        logger.info(
            f"Using {tool_name} to {'reply to thread ' + (thread_id or '') if is_reply else 'send new email to ' + to}"
        )

        return await invoke_gmail_tool(user_id, tool_name, parameters)

    except Exception as e:
        logger.error(f"Error sending email for user {user_id}: {e}")
        return {"error": str(e), "successful": False}


async def fetch_detailed_messages(
    user_id: str, messages: List[Dict[str, Any]], batch_size: int = 20, delay: float = 2
) -> List[Dict[str, Any]]:
    """
    Fetch detailed Gmail messages using Composio tools while handling rate limits.

    Args:
        user_id: User ID for Composio authentication
        messages: List of message metadata (each containing 'id')
        batch_size: Number of messages per batch (default: 20)
        delay: Time in seconds to wait between batch executions

    Returns:
        List of detailed message objects
    """

    detailed_messages = []
    total_messages = len(messages)

    for i in range(0, total_messages, batch_size):
        batch_messages = messages[i : i + batch_size]

        # Process each message in the current batch
        for message in batch_messages:
            message_id = message.get("id")
            if not message_id:
                continue

            try:
                parameters = {"message_id": message_id}
                result = await invoke_gmail_tool(
                    user_id, "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", parameters
                )

                if result.get("successful", True):
                    detailed_messages.append(result)
                else:
                    logger.error(
                        f"Error fetching message {message_id}: {result.get('error')}"
                    )

            except Exception as e:
                logger.error(f"Error fetching message {message_id}: {e}")

        # Rate limiting: wait between batches
        if i + batch_size < total_messages and delay > 0:
            time.sleep(delay)

    return detailed_messages


async def modify_message_labels(
    user_id: str,
    message_ids: List[str],
    add_labels: Optional[List[str]] = None,
    remove_labels: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Modify the labels of Gmail messages using Composio Gmail tools.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to modify
        add_labels: Labels to add to the messages
        remove_labels: Labels to remove from the messages

    Returns:
        List of modified messages
    """
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
            add_result = await invoke_gmail_tool(
                user_id, "GMAIL_ADD_LABEL_TO_EMAIL", add_params
            )
            if add_result.get("successful", True):
                results.extend(add_result.get("messages", []))
        except Exception as e:
            logger.error(f"Error adding labels {add_labels} to messages: {e}")

    # Remove labels if specified
    if remove_labels:
        try:
            remove_params = {
                "message_ids": message_ids,
                "label_ids": remove_labels,
            }
            remove_result = await invoke_gmail_tool(
                user_id, "GMAIL_REMOVE_LABEL", remove_params
            )
            if remove_result.get("successful", True):
                # Only extend if we didn't already get results from adding labels
                if not add_labels:
                    results.extend(remove_result.get("messages", []))
        except Exception as e:
            logger.error(f"Error removing labels {remove_labels} from messages: {e}")

    return results


async def mark_messages_as_read(
    user_id: str, message_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Mark Gmail messages as read by removing the UNREAD label using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to mark as read

    Returns:
        List of modified messages
    """
    return await modify_message_labels(user_id, message_ids, remove_labels=["UNREAD"])


async def mark_messages_as_unread(
    user_id: str, message_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Mark Gmail messages as unread by adding the UNREAD label using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to mark as unread

    Returns:
        List of modified messages
    """
    return await modify_message_labels(user_id, message_ids, add_labels=["UNREAD"])


async def star_messages(user_id: str, message_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Star Gmail messages by adding the STARRED label.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to star

    Returns:
        List of modified messages
    """
    logger.info(f"Starring {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, add_labels=["STARRED"])


async def unstar_messages(user_id: str, message_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Unstar Gmail messages by removing the STARRED label.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to unstar

    Returns:
        List of modified messages
    """
    logger.info(f"Unstarring {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=["STARRED"])


async def trash_messages(user_id: str, message_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Move Gmail messages to trash.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to trash

    Returns:
        List of modified messages
    """
    logger.info(f"Moving {len(message_ids)} messages to trash")
    results = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(user_id, "GMAIL_TRASH_MESSAGE", parameters)
            if result.get("successful", True):
                results.append(result)
            else:
                logger.error(
                    f"Error trashing message {message_id}: {result.get('error')}"
                )
        except Exception as e:
            logger.error(f"Error trashing message {message_id}: {e}")

    return results


async def untrash_messages(
    user_id: str, message_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Restore Gmail messages from trash.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to restore from trash

    Returns:
        List of modified messages
    """
    logger.info(f"Restoring {len(message_ids)} messages from trash")
    results = []

    for message_id in message_ids:
        try:
            parameters = {"message_id": message_id}
            result = await invoke_gmail_tool(
                user_id, "GMAIL_UNTRASH_MESSAGE", parameters
            )
            if result.get("successful", True):
                results.append(result)
            else:
                logger.error(
                    f"Error untrashing message {message_id}: {result.get('error')}"
                )
        except Exception as e:
            logger.error(f"Error untrashing message {message_id}: {e}")

    return results


async def archive_messages(
    user_id: str, message_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Archive Gmail messages by removing the INBOX label.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to archive

    Returns:
        List of modified messages
    """
    logger.info(f"Archiving {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=["INBOX"])


async def move_to_inbox(user_id: str, message_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Move Gmail messages to inbox by adding the INBOX label.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs to move to inbox

    Returns:
        List of modified messages
    """
    logger.info(f"Moving {len(message_ids)} messages to inbox")
    return await modify_message_labels(user_id, message_ids, add_labels=["INBOX"])


async def fetch_thread(user_id: str, thread_id: str) -> Dict[str, Any]:
    """
    Fetch a complete email thread with all messages using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        thread_id: ID of the thread to fetch

    Returns:
        Thread data including all messages
    """
    logger.info(f"Fetching thread with ID: {thread_id}")
    try:
        parameters = {
            "thread_id": thread_id,
        }

        result = await invoke_gmail_tool(
            user_id, "GMAIL_FETCH_MESSAGE_BY_THREAD_ID", parameters
        )

        if result.get("successful", True):
            thread = result

            # Transform messages in the thread for easier frontend processing
            if "messages" in thread:
                thread["messages"] = [
                    transform_gmail_message(msg) for msg in thread["messages"]
                ]

                # Sort messages by date (oldest first)
                thread["messages"].sort(key=lambda msg: int(msg.get("internalDate", 0)))

            return thread
        else:
            logger.error(
                f"Error from GMAIL_FETCH_MESSAGE_BY_THREAD_ID: {result.get('error')}"
            )
            return {"messages": []}

    except Exception as error:
        logger.error(f"Error fetching thread {thread_id}: {error}")
        return {"messages": []}


async def search_messages(
    user_id: str,
    query: Optional[str] = None,
    max_results: int = 20,
    page_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search Gmail messages using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        query: Search query in Gmail's search syntax
        max_results: Maximum number of results to return
        page_token: Token for pagination

    Returns:
        Dict containing messages and next page token
    """
    try:
        parameters = {
            "query": query or "",
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token

        result = await invoke_gmail_tool(user_id, "GMAIL_FETCH_EMAILS", parameters)

        if result.get("successful", True):
            # Transform messages if needed
            data = result.get("data", {})
            messages = data.get("messages", [])
            return {
                "messages": [transform_gmail_message(msg) for msg in messages],
                "nextPageToken": data.get("nextPageToken"),
            }
        else:
            return {"messages": [], "nextPageToken": None}

    except Exception:
        return {"messages": [], "nextPageToken": None}


async def create_label(
    user_id: str,
    name: str,
    label_list_visibility: str = "labelShow",
    message_list_visibility: str = "show",
    background_color: Optional[str] = None,
    text_color: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new Gmail label using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        name: Name of the label
        label_list_visibility: Whether the label appears in the label list
        message_list_visibility: Whether the label appears in the message list
        background_color: Background color of the label (hex code)
        text_color: Text color of the label (hex code)

    Returns:
        Created label data
    """
    logger.info(f"Creating new label: {name}")
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
        logger.error(f"Error creating label {name}: {error}")
        return {"error": str(error), "successful": False}


async def update_label(
    user_id: str,
    label_id: str,
    name: Optional[str] = None,
    label_list_visibility: Optional[str] = None,
    message_list_visibility: Optional[str] = None,
    background_color: Optional[str] = None,
    text_color: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Update an existing Gmail label using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        label_id: ID of the label to update
        name: New name for the label
        label_list_visibility: Whether the label appears in the label list
        message_list_visibility: Whether the label appears in the message list
        background_color: Background color of the label (hex code)
        text_color: Text color of the label (hex code)

    Returns:
        Updated label data
    """
    logger.info(f"Updating label {label_id}")
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
        logger.error(f"Error updating label {label_id}: {error}")
        return {"error": str(error), "successful": False}


async def delete_label(user_id: str, label_id: str) -> bool:
    """
    Delete a Gmail label.

    Args:
        user_id: User ID for Composio authentication
        label_id: ID of the label to delete

    Returns:
        True if successful
    """
    logger.info(f"Deleting label {label_id}")
    try:
        parameters = {"label_id": label_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_LABEL", parameters)
        return result.get("successful", True)
    except Exception as error:
        logger.error(f"Error deleting label {label_id}: {error}")
        return False


async def apply_labels(
    user_id: str, message_ids: List[str], label_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Apply one or more labels to specified messages.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs
        label_ids: List of label IDs to apply

    Returns:
        List of modified messages
    """
    logger.info(f"Applying labels {label_ids} to {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, add_labels=label_ids)


async def remove_labels(
    user_id: str, message_ids: List[str], label_ids: List[str]
) -> List[Dict[str, Any]]:
    """
    Remove one or more labels from specified messages.

    Args:
        user_id: User ID for Composio authentication
        message_ids: List of message IDs
        label_ids: List of label IDs to remove

    Returns:
        List of modified messages
    """
    logger.info(f"Removing labels {label_ids} from {len(message_ids)} messages")
    return await modify_message_labels(user_id, message_ids, remove_labels=label_ids)


async def create_draft(
    user_id: str,
    sender: str,
    to_list: List[str],
    subject: str,
    body: str,
    is_html: bool = False,
    cc_list: Optional[List[str]] = None,
    bcc_list: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Create a new Gmail draft using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        sender: Email address of the sender
        to_list: Email addresses of recipients
        subject: Email subject
        body: Email body
        is_html: Whether the body is HTML content
        cc_list: Email addresses for CC
        bcc_list: Email addresses for BCC

    Returns:
        Created draft data
    """
    logger.info(f"Creating draft email to {to_list} with subject: {subject}")
    try:
        parameters: Dict[str, Any] = {
            "to": to_list,
            "subject": subject,
            "body": body,
        }

        # Add optional parameters if provided
        if cc_list:
            parameters["cc"] = cc_list
        if bcc_list:
            parameters["bcc"] = bcc_list
        if is_html:
            parameters["html"] = True

        result = await invoke_gmail_tool(
            user_id, "GMAIL_CREATE_EMAIL_DRAFT", parameters
        )
        return result
    except Exception as error:
        logger.error(f"Error creating draft: {error}")
        return {"error": str(error), "successful": False}


async def list_drafts(
    user_id: str, max_results: int = 20, page_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    List Gmail draft messages using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        max_results: Maximum number of drafts to return
        page_token: Token for pagination

    Returns:
        Dict containing drafts and next page token
    """
    logger.info(f"Listing drafts, max_results={max_results}")
    try:
        parameters: Dict[str, Any] = {
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
        else:
            logger.error(f"Error from GMAIL_LIST_DRAFTS: {result.get('error')}")
            return {"drafts": [], "nextPageToken": None}

    except Exception as error:
        logger.error(f"Error listing drafts: {error}")
        return {"drafts": [], "nextPageToken": None}


async def get_draft(user_id: str, draft_id: str) -> Dict[str, Any]:
    """
    Get a specific Gmail draft.

    Args:
        user_id: User ID for Composio authentication
        draft_id: ID of the draft to retrieve

    Returns:
        Draft data with message details
    """
    logger.info(f"Fetching draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_GET_DRAFT", parameters)

        if result.get("successful", True):
            # Transform the message data if present
            if "message" in result:
                result["message"] = transform_gmail_message(result["message"])
            return result
        else:
            logger.error(f"Error from GMAIL_GET_DRAFT: {result.get('error')}")
            return {"error": result.get("error"), "successful": False}

    except Exception as error:
        logger.error(f"Error fetching draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def update_draft(
    user_id: str,
    draft_id: str,
    sender: str,
    to_list: List[str],
    subject: str,
    body: str,
    is_html: bool = False,
    cc_list: Optional[List[str]] = None,
    bcc_list: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Update an existing Gmail draft.

    Args:
        user_id: User ID for Composio authentication
        draft_id: ID of the draft to update
        sender: Email address of the sender
        to_list: Email addresses of recipients
        subject: Email subject
        body: Email body
        is_html: Whether the body is HTML content
        cc_list: Email addresses for CC
        bcc_list: Email addresses for BCC

    Returns:
        Updated draft data
    """
    logger.info(f"Updating draft {draft_id}")
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
        else:
            logger.error(f"Error from GMAIL_UPDATE_DRAFT: {result.get('error')}")
            return {"error": result.get("error"), "successful": False}

    except Exception as error:
        logger.error(f"Error updating draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def delete_draft(user_id: str, draft_id: str) -> bool:
    """
    Delete a Gmail draft.

    Args:
        user_id: User ID for Composio authentication
        draft_id: ID of the draft to delete

    Returns:
        True if successful
    """
    logger.info(f"Deleting draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_DELETE_DRAFT", parameters)
        return result.get("successful", True)
    except Exception as error:
        logger.error(f"Error deleting draft {draft_id}: {error}")
        return False


async def send_draft(user_id: str, draft_id: str) -> Dict[str, Any]:
    """
    Send an existing Gmail draft.

    Args:
        user_id: User ID for Composio authentication
        draft_id: ID of the draft to send

    Returns:
        Sent message data
    """
    logger.info(f"Sending draft {draft_id}")
    try:
        parameters = {"draft_id": draft_id}
        result = await invoke_gmail_tool(user_id, "GMAIL_SEND_DRAFT", parameters)

        if result.get("successful", True):
            return result
        else:
            logger.error(f"Error from GMAIL_SEND_DRAFT: {result.get('error')}")
            return {"error": result.get("error"), "successful": False}

    except Exception as error:
        logger.error(f"Error sending draft {draft_id}: {error}")
        return {"error": str(error), "successful": False}


async def list_labels(user_id: str) -> Dict[str, Any]:
    """
    List all Gmail labels using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication

    Returns:
        Dict containing labels list
    """
    logger.info(f"Listing Gmail labels for user {user_id}")
    try:
        parameters: Dict[str, Any] = {}  # No parameters needed for listing labels
        result = await invoke_gmail_tool(user_id, "GMAIL_LIST_LABELS", parameters)

        if result.get("successful", True):
            labels = result.get("labels", [])
            return {
                "success": True,
                "labels": labels,
                "count": len(labels),
            }
        else:
            logger.error(f"Error from GMAIL_LIST_LABELS: {result.get('error')}")
            return {
                "success": False,
                "error": result.get("error"),
                "labels": [],
            }

    except Exception as error:
        logger.error(f"Error listing Gmail labels: {error}")
        return {
            "success": False,
            "error": str(error),
            "labels": [],
        }


async def get_email_by_id(user_id: str, message_id: str) -> Dict[str, Any]:
    """
    Get a Gmail message by its ID using Composio Gmail tool.

    Args:
        user_id: User ID for Composio authentication
        message_id: Gmail message ID to retrieve

    Returns:
        Gmail message data
    """
    logger.info(f"Fetching email with ID: {message_id}")
    try:
        parameters = {"message_id": message_id}
        result = await invoke_gmail_tool(
            user_id, "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", parameters
        )

        if result.get("successful", True):
            # Transform the message data for easier frontend processing
            transformed_message = transform_gmail_message(result)
            return {
                "success": True,
                "message": transformed_message,
            }
        else:
            logger.error(
                f"Error from GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID: {result.get('error')}"
            )
            return {
                "success": False,
                "error": result.get("error"),
                "message": None,
            }

    except Exception as error:
        logger.error(f"Error fetching email {message_id}: {error}")
        return {
            "success": False,
            "error": str(error),
            "message": None,
        }


async def get_contact_list(user_id: str, max_results=100):
    """
    Extract a list of unique contacts (email addresses and names) from the user's Gmail history.

    Args:
        user_id: User ID for Composio authentication
        max_results: Maximum number of messages to analyze (default: 100)

    Returns:
        List of unique contacts with their email addresses and names
    """
    try:
        # Get messages from inbox, sent, and all mail to maximize contact discovery
        query = "in:inbox OR in:sent OR in:all"

        # First, get message IDs using search
        search_params = {"query": query, "max_results": max_results}

        search_result = await invoke_gmail_tool(
            user_id, "GMAIL_FETCH_EMAILS", search_params
        )

        if not search_result.get("successful", True):
            logger.error(f"Error searching for messages: {search_result.get('error')}")
            return []

        messages = search_result.get("messages", [])

        # Use a dictionary to track unique contacts
        contacts = {}

        # Process each message to extract contacts
        for msg_data in messages:
            msg_id = msg_data.get("id")
            if not msg_id:
                continue

            # Fetch full message details
            msg_params = {"message_id": msg_id}
            msg_result = await invoke_gmail_tool(
                user_id, "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", msg_params
            )

            if not msg_result.get("successful", True):
                continue

            msg = msg_result

            # Extract headers
            headers = {}
            if "payload" in msg and "headers" in msg["payload"]:
                headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

            # Extract email addresses from From, To, Cc, and Reply-To fields
            for field in ["From", "To", "Cc", "Reply-To"]:
                if field in headers and headers[field]:
                    # Split multiple addresses in a single field
                    addresses = headers[field].split(",")

                    for address in addresses:
                        address = address.strip()
                        if not address:
                            continue

                        # Parse name and email from address string
                        name = ""
                        email = address

                        # Handle format: "Name <email@example.com>"
                        if "<" in address and ">" in address:
                            name = address.split("<")[0].strip()
                            email = address.split("<")[1].split(">")[0].strip()

                        # Only add if it's a valid email address
                        if "@" in email and "." in email:
                            # Add to contacts dict, using email as key to ensure uniqueness
                            contacts[email] = {"name": name, "email": email}

        # Convert dictionary to list for return
        contact_list = list(contacts.values())

        # Sort contacts alphabetically by name, then email
        contact_list.sort(key=lambda x: (x["name"] if x["name"] else x["email"]))

        return contact_list

    except Exception as e:
        logger.error(f"Error getting contact list: {str(e)}")
        return []
