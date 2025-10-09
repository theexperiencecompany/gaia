"""
Gmail-specific hooks using the enhanced decorator system.

These hooks implement writer functionality for frontend streaming
and response processing for raw Gmail API data.
"""

from typing import Any

from app.config.loggers import app_logger as logger
from app.agents.templates.mail_templates import (
    detailed_message_template,
    draft_template,
    process_get_thread_response,
    process_list_drafts_response,
    process_list_messages_response,
)
from composio.types import ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from .registry import register_after_hook, register_before_hook

# ====================== BEFORE EXECUTE HOOKS ======================
# These hooks send progress/streaming data to frontend before tool execution


@register_before_hook(tools=["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"])
def gmail_compose_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle email composition response and streaming data."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        recipients = [
            arguments.get("recipient_email", ""),
            *arguments.get("extra_recipients", []),
        ]

        # Build the email compose data with draft_id
        emails_data = [
            {
                "to": recipients,
                "subject": arguments.get("subject", ""),
                "body": arguments.get("body", ""),
                "thread_id": arguments.get("thread_id", ""),
                "bcc": arguments.get("bcc", []),
                "cc": arguments.get("cc", []),
                "is_html": arguments.get("is_html", False),
            }
        ]
        # Check if the operation was successful
        if tool == "GMAIL_CREATE_EMAIL_DRAFT":
            # Send compose data to frontend with draft_id
            payload = {
                "email_compose_data": emails_data,
            }
            writer(payload)

        elif tool == "GMAIL_SEND_EMAIL":
            # Send email sent data to frontend
            payload = {"email_sent_data": emails_data}
            writer(payload)

        return params

    except Exception as e:
        logger.error(f"Error in gmail_compose_after_hook: {e}")
        return params


@register_before_hook(tools=["GMAIL_FETCH_EMAILS", "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_fetch_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle email fetching progress."""
    try:
        arguments = params.get("arguments", {})

        if tool == "GMAIL_FETCH_EMAILS":
            arguments["label_ids"] = (
                ["INBOX"] if not arguments.get("label_ids") else arguments["label_ids"]
            )
        arguments["format"] = "full"

        params["arguments"] = arguments
    except Exception as e:
        logger.error(f"Error in gmail_fetch_before_hook: {e}")

    return params


# ====================== AFTER EXECUTE HOOKS ======================
# These hooks process responses and send data to frontend after tool execution


@register_after_hook(tools=["GMAIL_FETCH_EMAILS"])
def gmail_fetch_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process email fetch response and send data to frontend."""
    try:
        writer = get_stream_writer()

        # Process the raw response to minimize data for LLM
        processed_response = process_list_messages_response(response["data"])

        if writer and processed_response.get("messages"):
            # Transform to EmailFetchData format for frontend
            email_fetch_data = []
            for msg in processed_response["messages"]:
                email_fetch_data.append(
                    {
                        "from": msg.get("from", ""),
                        "subject": msg.get("subject", ""),
                        "time": msg.get("time", ""),
                        "thread_id": msg.get("threadId", ""),
                        "is_read": msg.get("isRead", True),
                        "has_attachment": msg.get("hasAttachment", False),
                        "labels": msg.get("labels", []),
                    }
                )

            # Send email data to frontend
            payload = {
                "email_fetch_data": email_fetch_data,
                "nextPageToken": processed_response.get("nextPageToken"),
                "resultSize": processed_response.get("resultSize", 0),
            }
            writer(payload)

        # Return processed response for LLM
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_fetch_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_message_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process single message response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw message data to detailed but clean format
        processed_response = detailed_message_template(response["data"])
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_message_detail_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_THREAD_ID"])
def gmail_thread_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process thread response and send data to frontend."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response["data"]:
            return response["data"]

        # Process the raw thread response
        processed_response = process_get_thread_response(response["data"])

        if writer and processed_response.get("messages"):
            # Transform to EmailThreadData format for frontend
            thread_messages = []
            for msg in processed_response["messages"]:
                thread_messages.append(
                    {
                        "id": msg.get("id", ""),
                        "from": msg.get("from", ""),
                        "subject": msg.get("subject", ""),
                        "time": msg.get("time", ""),
                        "snippet": msg.get("snippet", ""),
                        "body": msg.get("body", ""),
                        "content": msg.get("content", ""),
                    }
                )

            # Send thread data to frontend
            payload = {
                "email_thread_data": {
                    "thread_id": processed_response.get("id"),
                    "messages": thread_messages,
                    "messages_count": processed_response.get("messageCount", 0),
                }
            }
            writer(payload)

        # Return processed response for LLM
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_thread_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_LIST_DRAFTS"])
def gmail_drafts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process drafts list response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Process the raw drafts response
        processed_response = process_list_drafts_response(response["data"])
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_drafts_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_GET_DRAFT"])
def gmail_draft_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process single draft response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw draft data to clean format
        processed_response = draft_template(response["data"])
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_draft_detail_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_FETCH_ATTACHMENT"])
def gmail_attachment_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process attachment response to extract metadata only."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Extract only metadata, not the base64 content
        processed_response = {
            "attachmentId": response["data"].get("attachmentId", ""),
            "filename": response["data"].get("filename", ""),
            "mimeType": response["data"].get("mimeType", ""),
            "size": response["data"].get("size", 0),
            "message": "Attachment content available but not displayed to preserve context",
        }

        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_attachment_after_hook: {e}")
        return response["data"]


# ====================== PROGRESS HOOKS FOR OTHER OPERATIONS ======================


@register_before_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle draft sending progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        payload = {"progress": "Sending draft..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_send_draft_before_hook: {e}")

    return params


@register_before_hook(tools=["GMAIL_TRASH_MESSAGE", "GMAIL_UNTRASH_MESSAGE"])
def gmail_trash_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle message trash/untrash progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        action = (
            "Moving to trash"
            if tool == "GMAIL_TRASH_MESSAGE"
            else "Restoring from trash"
        )

        payload = {"progress": f"{action}..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_trash_before_hook for {tool}: {e}")

    return params


@register_before_hook(
    tools=["GMAIL_CREATE_LABEL", "GMAIL_UPDATE_LABEL", "GMAIL_DELETE_LABEL"]
)
def gmail_label_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle label management progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        arguments = params.get("arguments", {})

        if tool == "GMAIL_CREATE_LABEL":
            name = arguments.get("name", "")
            payload = {"progress": f"Creating label: {name}..."}
        elif tool == "GMAIL_UPDATE_LABEL":
            payload = {"progress": "Updating label..."}
        elif tool == "GMAIL_DELETE_LABEL":
            payload = {"progress": "Deleting label..."}
        else:
            return params

        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_label_before_hook for {tool}: {e}")

    return params


@register_before_hook(tools=["GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL_REMOVE_LABEL"])
def gmail_modify_labels_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle message label modification progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        arguments = params.get("arguments", {})
        message_ids = arguments.get("message_ids", [])
        label_ids = arguments.get("label_ids", [])

        action = (
            "Adding labels to"
            if tool == "GMAIL_ADD_LABEL_TO_EMAIL"
            else "Removing labels from"
        )
        message_count = len(message_ids) if isinstance(message_ids, list) else 1

        payload = {
            "progress": f"{action} {message_count} message(s) with {len(label_ids) if isinstance(label_ids, list) else 1} label(s)..."
        }
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_modify_labels_before_hook for {tool}: {e}")

    return params


@register_before_hook(tools=["GMAIL_UPDATE_DRAFT", "GMAIL_DELETE_DRAFT"])
def gmail_draft_management_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle draft management progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        action = "Updating" if tool == "GMAIL_UPDATE_DRAFT" else "Deleting"
        payload = {"progress": f"{action} draft..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_draft_management_before_hook for {tool}: {e}")

    return params


@register_before_hook(tools=["GMAIL_LIST_DRAFTS"])
def gmail_list_drafts_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle drafts listing progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        arguments = params.get("arguments", {})
        max_results = arguments.get("max_results", 20)

        payload = {"progress": f"Fetching drafts (max {max_results} results)..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_list_drafts_before_hook: {e}")

    return params


@register_before_hook(tools=["GMAIL_GET_DRAFT"])
def gmail_get_draft_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle single draft fetching progress."""
    try:
        writer = get_stream_writer()
        if not writer:
            return params

        payload = {"progress": "Fetching draft..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_get_draft_before_hook: {e}")

    return params


# ====================== ADDITIONAL AFTER HOOKS FOR RESPONSE PROCESSING ======================


@register_after_hook(tools=["GMAIL_FETCH_EMAIL_BY_ID"])
def gmail_fetch_by_id_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process single email fetch response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw message data to detailed but clean format
        processed_response = detailed_message_template(response["data"])
        return processed_response

    except Exception as e:
        logger.error(f"Error in gmail_fetch_by_id_after_hook: {e}")
        return response["data"]


# Removed duplicate after hooks - now handled by gmail_compose_after_hook above


@register_after_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process draft sending response."""
    try:
        writer = get_stream_writer()

        if writer and response["data"].get("successful", True):
            # Send email sent data to frontend
            message_data = response["data"].get("message", {})

            payload = {
                "email_sent_data": {
                    "message_id": response["data"].get("id", ""),
                    "message": "Draft sent successfully!",
                    "timestamp": response["data"].get("timestamp", ""),
                    "recipients": message_data.get("to", []),
                    "subject": message_data.get("subject", ""),
                }
            }
            writer(payload)

        # Keep the response minimal for LLM
        if "successful" in response["data"] and response["data"]["successful"]:
            return {
                "id": response["data"].get("id", ""),
                "successful": True,
                "message": "Draft sent successfully",
            }
        else:
            return response["data"]

    except Exception as e:
        logger.error(f"Error in gmail_send_draft_after_hook: {e}")
        return response["data"]
