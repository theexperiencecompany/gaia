"""
Gmail-specific hooks using the enhanced decorator system.

These hooks implement writer functionality for frontend streaming,
response processing for raw Gmail API data, and schema modifiers
for customizing tool descriptions and defaults.
"""

from typing import Any

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from app.agents.templates.mail_templates import (
    detailed_message_template,
    draft_template,
    process_get_thread_response,
    process_list_drafts_response,
    process_list_messages_response,
)
from app.config.loggers import app_logger as logger
from app.utils.markdown_utils import (
    convert_markdown_to_html,
    convert_markdown_to_plain_text,
    is_markdown_content,
)

from .registry import (
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
)

# ====================== SCHEMA MODIFIERS ======================
# These modifiers customize tool schemas before they are seen by agents


@register_schema_modifier(tools=["GMAIL_SEND_EMAIL"])
def gmail_send_email_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """
    Add draft-first workflow guidance to GMAIL_SEND_EMAIL description.

    This encourages agents to create drafts for user review before
    sending emails directly, unless explicitly instructed otherwise.
    """
    draft_guidance = (
        "\n\n⚠️ IMPORTANT WORKFLOW: Unless the user explicitly requests "
        "immediate sending, prefer creating a draft first using "
        "GMAIL_CREATE_EMAIL_DRAFT for user review. "
        "If a draft was already created in the current conversation, "
        "use GMAIL_SEND_DRAFT with the draft_id instead of this tool."
    )
    schema.description += draft_guidance
    return schema


@register_schema_modifier(
    tools=["GMAIL_FETCH_EMAILS", "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"]
)
def gmail_fetch_emails_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """
    Set sensible defaults for GMAIL_FETCH_EMAILS and GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID.

    - max_results: default to 10 (was 1)
    - label_ids: default to ["INBOX"]
    - format: default to "full"
    - Add Gmail search syntax tips to description
    """
    props = schema.input_parameters.get("properties", {})

    if tool == "GMAIL_FETCH_EMAILS":
        # Set max_results default to 10
        if "max_results" in props:
            props["max_results"]["default"] = 10

        # Set label_ids default to ["INBOX"]
        if "label_ids" in props:
            props["label_ids"]["default"] = ["INBOX"]

        # Add Gmail search syntax tips to description
        search_tips = (
            "\n\nGMAIL SEARCH SYNTAX (use in 'query' parameter):\n"
            "• from:sender@email.com - emails from specific sender\n"
            "• to:recipient@email.com - emails to specific recipient\n"
            "• subject:keyword - emails with keyword in subject\n"
            "• is:unread, is:read, is:starred - filter by status\n"
            "• has:attachment - emails with attachments\n"
            "• after:2024/01/01, before:2024/12/31 - date range\n"
            "• newer_than:7d, older_than:1m - relative dates\n"
            "• label:labelname - emails with specific label\n"
            "• in:inbox, in:sent, in:drafts - filter by folder"
        )
        schema.description += search_tips

    # Set format default to "full" for detailed content
    if "format" in props:
        props["format"]["default"] = "full"

    return schema


# ====================== BEFORE EXECUTE HOOKS ======================
# These hooks send progress/streaming data to frontend before tool execution


@register_before_hook(
    tools=[
        "GMAIL_SEND_EMAIL",
        "GMAIL_CREATE_EMAIL_DRAFT",
        "GMAIL_REPLY_TO_THREAD",
        "GMAIL_FORWARD_MESSAGE",
    ]
)
def gmail_compose_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle email composition response and streaming data."""
    try:
        writer = get_stream_writer()
        arguments = params.get("arguments", {})

        body = arguments.get("body", "")
        is_html = arguments.get("is_html", False)

        # Detect and convert markdown content
        if body and is_markdown_content(body):
            logger.info(
                f"Markdown detected in email body for {tool}, converting to {'HTML' if is_html else 'plain text'}"
            )

            if is_html:
                # Convert markdown to HTML
                converted_body = convert_markdown_to_html(body)
                arguments["body"] = converted_body
                logger.debug(f"Converted markdown to HTML for {tool}")
            else:
                # Convert markdown to plain text
                converted_body = convert_markdown_to_plain_text(body)
                arguments["body"] = converted_body
                logger.debug(f"Converted markdown to plain text for {tool}")

            # Update params with converted body
            params["arguments"] = arguments

        # Handle different recipient formats based on tool
        if tool == "GMAIL_FORWARD_MESSAGE":
            recipients = arguments.get("to_recipients", [])
            if isinstance(recipients, str):
                recipients = [recipients]
        else:
            extra_recipients = arguments.get("extra_recipients", [])
            if not isinstance(extra_recipients, list):
                extra_recipients = []
            recipients = [
                arguments.get("recipient_email", ""),
                *extra_recipients,
            ]

        # Build the email compose data
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

        # Check if the operation was successful and send appropriate payload
        if tool == "GMAIL_CREATE_EMAIL_DRAFT":
            # Send compose data to frontend with draft_id
            payload = {
                "email_compose_data": emails_data,
            }
            writer(payload)

        elif tool in [
            "GMAIL_SEND_EMAIL",
            "GMAIL_REPLY_TO_THREAD",
            "GMAIL_FORWARD_MESSAGE",
        ]:
            # Send email sent data to frontend
            payload = {"email_sent_data": emails_data}
            writer(payload)

        return params

    except Exception as e:
        logger.error(f"Error in gmail_compose_before_hook: {e}")
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

        if writer is not None and processed_response.get("messages"):
            # Transform to EmailFetchData format for frontend
            email_fetch_data = []
            for msg in processed_response["messages"]:
                email_fetch_data.append(
                    {
                        "from": msg.get("from", ""),
                        "subject": msg.get("subject", ""),
                        "time": msg.get("time", ""),
                        "thread_id": msg.get("threadId", ""),
                        "id": msg.get("id", ""),
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

        if writer is not None and processed_response.get("messages"):
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
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
        if not writer:  # type: ignore[truthy-function]
            return params

        payload = {"progress": "Fetching draft details..."}
        writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_get_draft_before_hook: {e}")

    return params


@register_before_hook(tools=["GMAIL_GET_CONTACTS"])
def gmail_get_contacts_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle contacts fetching with default page size."""
    try:
        arguments = params.get("arguments", {})

        # Set default page size to 50 if not specified
        if "page_size" not in arguments or not arguments["page_size"]:
            arguments["page_size"] = 50

        params["arguments"] = arguments

        writer = get_stream_writer()
        if writer is not None:
            payload = {"progress": "Fetching contacts..."}
            writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_get_contacts_before_hook: {e}")

    return params


@register_before_hook(tools=["GMAIL_SEARCH_PEOPLE"])
def gmail_search_people_before_hook(tool: str, toolkit: str, params: Any) -> Any:
    """Handle people search progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            arguments = params.get("arguments", {})
            query = arguments.get("query", "")
            payload = {"progress": f"Searching for people matching '{query}'..."}
            writer(payload)

    except Exception as e:
        logger.error(f"Error in gmail_search_people_before_hook: {e}")

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


@register_after_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process draft sending response."""
    try:
        writer = get_stream_writer()

        if writer is not None and response["data"].get("successful", True):
            # Send email sent data to frontend
            message_data = response["data"].get("message", {})

            payload = {
                "email_sent_data": [
                    {
                        "message_id": response["data"].get("id", ""),
                        "message": "Draft sent successfully!",
                        "timestamp": response["data"].get("timestamp", ""),
                        "recipients": message_data.get("to", []),
                        "subject": message_data.get("subject", ""),
                    }
                ]
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


@register_after_hook(tools=["GMAIL_GET_CONTACTS"])
def gmail_get_contacts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process contacts list response to minimize raw data."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response["data"]:
            return response["data"]

        response_data = response["data"].get("response_data", {})
        connections = response_data.get("connections", [])

        # Process contacts for frontend display
        contact_list = []
        # Process contacts for LLM (minimal data)
        llm_contacts = []

        for contact in connections:
            names = contact.get("names", [])
            email_addresses = contact.get("emailAddresses", [])
            phone_numbers = contact.get("phoneNumbers", [])

            primary_name = next(
                (n for n in names if n.get("metadata", {}).get("primary")),
                names[0] if names else {},
            )
            display_name = primary_name.get("displayName", "Unknown")

            primary_email = next(
                (e for e in email_addresses if e.get("metadata", {}).get("primary")),
                email_addresses[0] if email_addresses else {},
            )
            email = primary_email.get("value", "")

            phone = ""
            if phone_numbers:
                primary_phone = next(
                    (p for p in phone_numbers if p.get("metadata", {}).get("primary")),
                    phone_numbers[0],
                )
                phone = primary_phone.get("value", "")

            contact_data = {
                "name": display_name,
                "email": email,
                "phone": phone,
                "resource_name": contact.get("resourceName", ""),
            }

            contact_list.append(contact_data)

            # Minimal data for LLM
            llm_contact = {"name": display_name}
            if email:
                llm_contact["email"] = email
            if phone:
                llm_contact["phone"] = phone
            llm_contacts.append(llm_contact)

        # Send to frontend
        if writer is not None and contact_list:
            payload = {
                "contacts_data": contact_list,
                "total_count": response_data.get("totalPeople", len(contact_list)),
                "next_page_token": response_data.get("nextPageToken"),
            }
            writer(payload)

        # Return minimal data for LLM
        return {
            "contacts": llm_contacts,
            "total_count": response_data.get("totalPeople", len(llm_contacts)),
            "has_more": bool(response_data.get("nextPageToken")),
        }

    except Exception as e:
        logger.error(f"Error in gmail_get_contacts_after_hook: {e}")
        return response["data"]


@register_after_hook(tools=["GMAIL_SEARCH_PEOPLE"])
def gmail_search_people_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> Any:
    """Process people search response to minimize raw data."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response["data"]:
            return response["data"]

        response_data = response["data"].get("response_data", {})
        results = response_data.get("results", [])

        # Process search results for frontend display
        people_list = []
        # Process for LLM (minimal data)
        llm_people = []

        for result in results:
            person = result.get("person", {})
            names = person.get("names", [])
            email_addresses = person.get("emailAddresses", [])
            phone_numbers = person.get("phoneNumbers", [])

            primary_name = next(
                (n for n in names if n.get("metadata", {}).get("primary")),
                names[0] if names else {},
            )
            display_name = primary_name.get("displayName", "Unknown")

            primary_email = next(
                (e for e in email_addresses if e.get("metadata", {}).get("primary")),
                email_addresses[0] if email_addresses else {},
            )
            email = primary_email.get("value", "")

            phone = ""
            if phone_numbers:
                primary_phone = next(
                    (p for p in phone_numbers if p.get("metadata", {}).get("primary")),
                    phone_numbers[0],
                )
                phone = primary_phone.get("value", "")

            person_data = {
                "name": display_name,
                "email": email,
                "phone": phone,
                "resource_name": person.get("resourceName", ""),
            }

            people_list.append(person_data)

            # Minimal data for LLM
            llm_person = {"name": display_name}
            if email:
                llm_person["email"] = email
            if phone:
                llm_person["phone"] = phone
            llm_people.append(llm_person)

        # Send to frontend
        if writer is not None and people_list:
            payload = {
                "people_search_data": people_list,
                "result_count": len(people_list),
            }
            writer(payload)

        # Return minimal data for LLM
        return {
            "people": llm_people,
            "result_count": len(llm_people),
        }

    except Exception as e:
        logger.error(f"Error in gmail_search_people_after_hook: {e}")
        return response["data"]
