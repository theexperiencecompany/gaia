"""
Gmail-specific hooks using the enhanced decorator system.

These hooks implement writer functionality for frontend streaming,
response processing for raw Gmail API data, and schema modifiers
for customizing tool descriptions and defaults.
"""

from collections.abc import Sequence
from typing import Any, TypedDict, TypeVar

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer
from pydantic import BaseModel, ValidationError

from app.agents.templates.mail_templates import (
    detailed_message_template,
    draft_template,
    process_get_thread_response,
    process_list_drafts_response,
)
from app.constants.log_tags import LogTag
from app.models.composio_schemas.google_people import (
    ContactCard,
    ContactSummary,
    GoogleContactsResponseData,
    GooglePeopleSearchResponseData,
    GooglePerson,
    GooglePersonName,
    GooglePersonValue,
)
from app.services.composio.attachments import (
    AttachmentReference,
    ComposioAttachment,
    resolve_attachments_sync,
)
from app.utils.errors import AppError
from app.utils.markdown_utils import normalize_email_body_to_html
from shared.py.wide_events import log

from .registry import (
    HookAbortError,
    register_after_hook,
    register_before_hook,
    register_schema_modifier,
)

_GMAIL_COMPOSE_TOOLS = (
    "GMAIL_SEND_EMAIL",
    "GMAIL_CREATE_EMAIL_DRAFT",
    "GMAIL_REPLY_TO_THREAD",
    "GMAIL_FORWARD_MESSAGE",
)
# Gmail's ``body`` field is named differently across compose tools.
_GMAIL_BODY_KEYS = ("body", "message_body", "message")

_PersonField = TypeVar("_PersonField", GooglePersonName, GooglePersonValue)


def _primary(entries: Sequence[_PersonField]) -> _PersonField | None:
    """The entry People flagged as primary, else the first one, else None."""
    if not entries:
        return None
    return next(
        (entry for entry in entries if entry.metadata is not None and entry.metadata.primary),
        entries[0],
    )


def _display_name(name: GooglePersonName | None) -> str | None:
    """``displayName`` off the primary name, or "Unknown" when People omitted it."""
    if name is None or "display_name" not in name.model_fields_set:
        return "Unknown"
    return name.display_name


def _entry_value(entry: GooglePersonValue | None) -> str | None:
    """``value`` off an email/phone entry, or "" when People omitted it."""
    if entry is None or "value" not in entry.model_fields_set:
        return ""
    return entry.value


def _contact_card(person: GooglePerson) -> ContactCard:
    """Flatten a People API person to the primary name/email/phone the UI shows.

    Every fallback keys off ``model_fields_set``, not on the value being None,
    because that is what the original ``.get(key, default)`` did: the default
    fires only when People omitted the key, while a key sent as an explicit
    ``null`` stays ``None``. The web client and the LLM have always received that
    ``None``, so normalizing it here would change a live payload.
    """
    return {
        "name": _display_name(_primary(person.names)),
        "email": _entry_value(_primary(person.email_addresses)),
        "phone": _entry_value(_primary(person.phone_numbers)),
        "resource_name": (
            person.resource_name if "resource_name" in person.model_fields_set else ""
        ),
    }


def _contact_summary(card: ContactCard) -> ContactSummary:
    """Trim a contact card for the LLM: name always, email/phone only when known."""
    summary: ContactSummary = {"name": card["name"]}
    if card["email"]:
        summary["email"] = card["email"]
    if card["phone"]:
        summary["phone"] = card["phone"]
    return summary


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
        "\n\nIMPORTANT WORKFLOW: Unless the user explicitly requests "
        "immediate sending, prefer creating a draft first using "
        "GMAIL_CREATE_EMAIL_DRAFT for user review. "
        "If a draft was already created in the current conversation, "
        "use GMAIL_SEND_DRAFT with the draft_id instead of this tool."
    )
    schema.description += draft_guidance
    return schema


@register_schema_modifier(tools=list(_GMAIL_COMPOSE_TOOLS))
def gmail_compose_hide_is_html_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Hide the ``is_html`` parameter from the agent-facing schema.

    The before-hook always converts the body to HTML and sets the flag, so
    exposing it to the agent just invites bad choices (agent picks False,
    writes Markdown, Gmail renders ``**bold**`` as literal asterisks). The
    agent writes Markdown — everything else is our problem.
    """
    # `input_parameters` is typed as a Dict by Composio's SDK, but callers in practice
    # (including this codebase's own test doubles) don't always hand us a real,
    # validated `Tool`, so this stays defensive against a non-dict value.
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return schema
    props = input_params.get("properties")
    if isinstance(props, dict):
        props.pop("is_html", None)
    required = input_params.get("required")
    if isinstance(required, list) and "is_html" in required:
        required.remove("is_html")
    return schema


@register_schema_modifier(tools=["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"])
def gmail_compose_require_subject_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Make ``subject`` a required, non-empty field for email composition.

    A blank subject line reads as spam and gets buried — the agent must always
    write a clear, specific subject. Marking it required with ``minLength`` means
    the function-calling / args-validation layer rejects a call that omits or
    blanks it, before the tool ever runs (before-hook exceptions are swallowed,
    so schema-level enforcement is the only hard guarantee).
    """
    input_params = schema.input_parameters
    if isinstance(input_params, dict):
        required = input_params.setdefault("required", [])
        if isinstance(required, list) and "subject" not in required:
            required.append("subject")

        props = input_params.get("properties")
        if isinstance(props, dict) and isinstance(props.get("subject"), dict):
            props["subject"]["minLength"] = 1
            props["subject"]["description"] = (
                "Email subject line. Required — write a clear, specific subject "
                "that summarizes the email. Never leave it blank."
            )
    return schema


_ATTACHMENTS_PARAM_SCHEMA: dict[str, Any] = {
    "type": "array",
    "description": (
        "Files to attach to the email. Each item references ONE file by EITHER "
        "'workspace_path' (a file in the current session workspace, e.g. one the user "
        "uploaded or an agent saved there) OR 'url' (a fetchable link). To attach a "
        "Google Drive file, first call GOOGLEDRIVE_DOWNLOAD_FILE and pass the download "
        "URL it returns as 'url'. Total message size must stay under 25 MB."
    ),
    "items": {
        "type": "object",
        "properties": {
            "workspace_path": {
                "type": "string",
                "description": "Path to a file in the current session workspace (relative to /workspace).",
            },
            "url": {
                "type": "string",
                "description": "A fetchable URL to the file, e.g. a GOOGLEDRIVE_DOWNLOAD_FILE download URL.",
            },
            "name": {
                "type": "string",
                "description": "Optional filename to use for the attachment.",
            },
        },
    },
}


@register_schema_modifier(tools=["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"])
def gmail_compose_attachments_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Expose a friendly ``attachments`` param instead of Composio's raw ``attachment``.

    Composio's native ``attachment`` takes a pre-uploaded ``{name, mimetype, s3key}``,
    which an agent cannot produce. We swap it for ``attachments`` — a list of file
    references (workspace path or URL) — that ``gmail_compose_before_hook`` resolves to
    real Composio uploads before the tool runs.
    """
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return schema
    props = input_params.get("properties")
    if isinstance(props, dict):
        props.pop("attachment", None)
        props["attachments"] = _ATTACHMENTS_PARAM_SCHEMA
    required = input_params.get("required")
    if isinstance(required, list) and "attachment" in required:
        required.remove("attachment")
    return schema


@register_schema_modifier(tools=["GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_fetch_message_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Default GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID to format='full' for detailed content."""
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return schema

    props = input_params.get("properties", {})
    if isinstance(props, dict) and "format" in props and isinstance(props["format"], dict):
        props["format"]["default"] = "full"

    return schema


@register_schema_modifier(toolkits=["gmail"])
def gmail_hide_user_id_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Strip ``user_id`` from every Gmail tool's agent-facing schema.

    The mailbox is fixed by the connected account, so the Gmail ``userId`` must
    always be ``"me"``. Exposing it baits the agent into passing the literal
    address, which returns zero results; removing it forces Composio's default.
    """
    input_params: object = schema.input_parameters
    if not isinstance(input_params, dict):
        return schema
    props = input_params.get("properties")
    if isinstance(props, dict):
        props.pop("user_id", None)
    required = input_params.get("required")
    if isinstance(required, list) and "user_id" in required:
        required.remove("user_id")
    return schema


# ====================== BEFORE EXECUTE HOOKS ======================
# These hooks send progress/streaming data to frontend before tool execution


class _AttachmentDisplay(TypedDict):
    """The per-attachment metadata streamed to the compose card (never the s3key)."""

    name: str
    mimetype: str


def _resolve_compose_attachments(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> list[_AttachmentDisplay]:
    """Turn the agent's ``attachments`` references into Composio's ``attachment`` arg.

    Uploads each referenced file to Composio and rewrites ``arguments`` in place.
    Raises ``HookAbortError`` on any failure so the compose tool does NOT run with a
    missing file (a silently attachment-less draft would be a data-loss bug).
    """
    arguments = params.get("arguments", {})
    raw = arguments.get("attachments")
    if not raw:
        return []
    if not isinstance(raw, list):
        raise HookAbortError("`attachments` must be a list of file references.")

    user_id = params.get("user_id")
    if not user_id:
        raise HookAbortError("Cannot resolve email attachments without a user context.")

    try:
        # Items arrive as dicts (REST) or as Composio's schema-generated Pydantic
        # models (agent path, where langchain coerces the tool args) — normalise
        # both to a plain mapping before validating into our reference model.
        references = [
            AttachmentReference.model_validate(
                item.model_dump() if isinstance(item, BaseModel) else item
            )
            for item in raw
        ]
    except ValidationError as exc:
        raise HookAbortError(f"Invalid attachment reference: {exc}") from exc

    try:
        resolved: list[ComposioAttachment] = resolve_attachments_sync(
            user_id, references, tool=tool, toolkit=toolkit
        )
    except AppError as exc:
        raise HookAbortError(exc.message) from exc

    # Composio's Gmail ``attachment`` is a single FileUploadable OR a list. The
    # pinned toolkit version only accepts the single-object form for one file, so
    # send a bare object when there is exactly one and reserve the list for many.
    arguments["attachment"] = resolved[0] if len(resolved) == 1 else resolved
    del arguments["attachments"]
    params["arguments"] = arguments
    log.set(gmail_attachment_count=len(resolved))
    return [{"name": a["name"], "mimetype": a["mimetype"]} for a in resolved]


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

    log.set(gmail_tool=tool, toolkit=toolkit)
    try:
        arguments = params.get("arguments", {})

        # Resolve any file references the agent supplied into real Composio uploads
        # BEFORE the tool runs. Raises HookAbortError (propagated below) if a file
        # can't be attached, so we never send mail missing a requested attachment.
        attachment_display = _resolve_compose_attachments(tool, toolkit, params)

        # Always normalise the body to HTML before it reaches Gmail. The agent
        # writes Markdown; Gmail renders Markdown literally as plain text. The
        # normaliser is idempotent on already-HTML bodies so callers that hand
        # us HTML are unaffected.
        for body_key in _GMAIL_BODY_KEYS:
            raw_body = arguments.get(body_key)
            if isinstance(raw_body, str) and raw_body:
                arguments[body_key] = normalize_email_body_to_html(raw_body)
        arguments["is_html"] = True
        params["arguments"] = arguments

        if tool in ["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"]:
            # Auto-convert 'to' to 'recipient_email' if needed
            if "to" in arguments and "recipient_email" not in arguments:
                arguments["recipient_email"] = arguments["to"]
                params["arguments"] = arguments
                log.info(
                    f"{LogTag.COMPOSIO} Mapped 'to' argument to 'recipient_email' for", tool=tool
                )

            # Check if at least one recipient type is provided
            recipient = arguments.get("recipient_email") or arguments.get("to")
            cc = arguments.get("cc", [])
            bcc = arguments.get("bcc", [])

            has_recipient = bool(recipient) or bool(cc) or bool(bcc)

            # Check if at least one of subject or body is provided
            subject = arguments.get("subject")
            body = arguments.get("body")

            has_content = bool(subject) or bool(body)

            # If validation fails, return params immediately to skip streaming
            if not has_recipient or not has_content:
                log.warning(
                    f"{LogTag.COMPOSIO} Skipping streaming: missing required fields",
                    tool_name=tool,
                    has_recipient=has_recipient,
                    has_content=has_content,
                )
                return params

        writer = get_stream_writer()

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
                "attachments": attachment_display,
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

    except HookAbortError:
        # Attachment resolution failed: propagate so the compose tool aborts
        # instead of sending mail without the file the user asked to attach.
        raise
    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_compose_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return params


# ====================== AFTER EXECUTE HOOKS ======================
# These hooks process responses and send data to frontend after tool execution


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_message_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process single message response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw message data to detailed but clean format
        processed_response = detailed_message_template(response["data"])
        return processed_response

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_message_detail_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_THREAD_ID"])
def gmail_thread_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
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
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_thread_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_LIST_DRAFTS"])
def gmail_drafts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process drafts list response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Process the raw drafts response
        processed_response = process_list_drafts_response(response["data"])
        return processed_response

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_drafts_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_GET_DRAFT"])
def gmail_draft_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process single draft response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw draft data to clean format
        processed_response = draft_template(response["data"])
        return processed_response

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_draft_detail_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_FETCH_ATTACHMENT"])
def gmail_attachment_after_hook(tool: str, toolkit: str, response: ToolExecutionResponse) -> object:
    """Process attachment response to extract metadata only."""
    try:
        # Composio's envelope types `data` as a plain Dict, but this endpoint has been
        # observed returning a non-dict `data` (e.g. a bare string) on some error paths,
        # so both branches below pass the raw value through unprocessed.
        data: object = response["data"]

        if not response["successful"]:
            return data

        # Extract only metadata, not the base64 content
        if not isinstance(data, dict):
            return data

        processed_response = {
            "attachmentId": data.get("attachmentId", ""),
            "filename": data.get("filename", ""),
            "mimeType": data.get("mimeType", ""),
            "size": data.get("size", 0),
            "message": "Attachment content available but not displayed to preserve context",
        }

        return processed_response

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_attachment_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


# ====================== PROGRESS HOOKS FOR OTHER OPERATIONS ======================


@register_before_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle draft sending progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            payload = {"progress": "Sending draft..."}
            writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_send_draft_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_TRASH_MESSAGE", "GMAIL_UNTRASH_MESSAGE"])
def gmail_trash_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle message trash/untrash progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            action = "Moving to trash" if tool == "GMAIL_TRASH_MESSAGE" else "Restoring from trash"

            payload = {"progress": f"{action}..."}
            writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_trash_before_hook for",
            tool=tool,
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_CREATE_LABEL", "GMAIL_UPDATE_LABEL", "GMAIL_DELETE_LABEL"])
def gmail_label_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle label management progress."""
    try:
        writer = get_stream_writer()
        if writer is None:
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
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_label_before_hook for",
            tool=tool,
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_ADD_LABEL_TO_EMAIL", "GMAIL_REMOVE_LABEL"])
def gmail_modify_labels_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle message label modification progress."""
    try:
        writer = get_stream_writer()
        if writer is None:
            return params

        arguments = params.get("arguments", {})
        message_ids = arguments.get("message_ids", [])
        label_ids = arguments.get("label_ids", [])

        action = (
            "Adding labels to" if tool == "GMAIL_ADD_LABEL_TO_EMAIL" else "Removing labels from"
        )
        message_count = len(message_ids) if isinstance(message_ids, list) else 1

        payload = {
            "progress": f"{action} {message_count} message(s) with {len(label_ids) if isinstance(label_ids, list) else 1} label(s)..."
        }
        writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_modify_labels_before_hook for",
            tool=tool,
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_UPDATE_DRAFT", "GMAIL_DELETE_DRAFT"])
def gmail_draft_management_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle draft management progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            action = "Updating" if tool == "GMAIL_UPDATE_DRAFT" else "Deleting"
            payload = {"progress": f"{action} draft..."}
            writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_draft_management_before_hook for",
            tool=tool,
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_LIST_DRAFTS"])
def gmail_list_drafts_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle drafts listing progress."""
    try:
        writer = get_stream_writer()
        if writer is None:
            return params

        arguments = params.get("arguments", {})
        max_results = arguments.get("max_results", 20)

        payload = {"progress": f"Fetching drafts (max {max_results} results)..."}
        writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_list_drafts_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_GET_DRAFT"])
def gmail_get_draft_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle single draft fetching progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            payload = {"progress": "Fetching draft details..."}
            writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_get_draft_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_GET_CONTACTS"])
def gmail_get_contacts_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
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
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_get_contacts_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


@register_before_hook(tools=["GMAIL_SEARCH_PEOPLE"])
def gmail_search_people_before_hook(
    tool: str, toolkit: str, params: ToolExecuteParams
) -> ToolExecuteParams:
    """Handle people search progress."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            arguments = params.get("arguments", {})
            query = arguments.get("query", "")
            payload = {"progress": f"Searching for people matching '{query}'..."}
            writer(payload)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_search_people_before_hook",
            error=str(e),
            error_type=type(e).__name__,
        )

    return params


# ====================== ADDITIONAL AFTER HOOKS FOR RESPONSE PROCESSING ======================


@register_after_hook(tools=["GMAIL_FETCH_EMAIL_BY_ID"])
def gmail_fetch_by_id_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process single email fetch response to minimize raw data."""
    try:
        if not response or "error" in response["data"]:
            return response["data"]

        # Transform raw message data to detailed but clean format
        processed_response = detailed_message_template(response["data"])
        return processed_response

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_fetch_by_id_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
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
        return response["data"]

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_send_draft_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_GET_CONTACTS"])
def gmail_get_contacts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process contacts list response to minimize raw data."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response["data"]:
            return response["data"]

        response_data = GoogleContactsResponseData.model_validate(
            response["data"].get("response_data") or {}
        )

        contact_list: list[ContactCard] = [
            _contact_card(person) for person in response_data.connections
        ]
        llm_contacts: list[ContactSummary] = [_contact_summary(card) for card in contact_list]

        # Send to frontend
        if writer is not None and contact_list:
            payload = {
                "contacts_data": contact_list,
                "total_count": response["data"].get("totalPeople", len(contact_list)),
                "next_page_token": response["data"].get("nextPageToken"),
            }
            writer(payload)

        # Return minimal data for LLM
        return {
            "contacts": llm_contacts,
            "total_count": response["data"].get("totalPeople", len(llm_contacts)),
            "has_more": bool(response["data"].get("nextPageToken")),
        }

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_get_contacts_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]


@register_after_hook(tools=["GMAIL_SEARCH_PEOPLE"])
def gmail_search_people_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> dict[str, Any]:
    """Process people search response to minimize raw data."""
    try:
        writer = get_stream_writer()

        if not response or "error" in response["data"]:
            return response["data"]

        response_data = GooglePeopleSearchResponseData.model_validate(
            response["data"].get("response_data") or {}
        )

        people_list: list[ContactCard] = [
            _contact_card(result.person) for result in response_data.results
        ]
        llm_people: list[ContactSummary] = [_contact_summary(card) for card in people_list]

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
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_search_people_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return response["data"]
