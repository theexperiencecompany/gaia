"""
Gmail-specific hooks using the enhanced decorator system.

These hooks implement writer functionality for frontend streaming,
response processing for raw Gmail API data, and schema modifiers
for customizing tool descriptions and defaults.
"""

from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypedDict, TypeVar

from composio.types import Tool, ToolExecuteParams, ToolExecutionResponse
from langgraph.config import get_stream_writer

from app.agents.templates.mail_templates import (
    detailed_message_template,
    draft_template,
    process_get_thread_response,
    process_list_drafts_response,
)
from app.constants.email import (
    GMAIL_DRAFT_ID_MISSING_LOG,
    GMAIL_SKIP_STREAM_LOG,
    GMAIL_TO_MAPPED_LOG,
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
from app.models.integrations.composio_hooks import (
    ComposioToolCall,
    ComposioToolResponse,
    JsonSchemaNode,
)
from app.models.integrations.gmail import (
    GmailAttachmentData,
    GmailComposeArguments,
    GmailContactsData,
    GmailDraftCreatedData,
    GmailGetContactsArguments,
    GmailLabelArguments,
    GmailListDraftsArguments,
    GmailModifyLabelsArguments,
    GmailSearchPeopleArguments,
    GmailSearchPeopleData,
    GmailSentDraftData,
    GmailSentDraftMessage,
    GmailThreadView,
)
from app.utils.markdown_utils import normalize_email_body_to_html
from shared.py.wide_events import log

from .file_upload_hooks import (
    AttachmentDisplay,
    resolve_tool_attachments,
    swapped_upload_param,
)
from .registry import (
    AfterHookResponse,
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
# Composio's names for the Gmail params the hooks read or rewrite.
_IS_HTML_PARAM = "is_html"
_SUBJECT_PARAM = "subject"
_FORMAT_PARAM = "format"
_USER_ID_PARAM = "user_id"
_RECIPIENT_EMAIL_PARAM = "recipient_email"
_TO_PARAM = "to"
_PAGE_SIZE_PARAM = "page_size"
_DEFAULT_CONTACTS_PAGE_SIZE = 50


@dataclass(slots=True)
class ComposeCard:
    """The compose/sent card for one Gmail compose call, as the chat UI renders it.

    draft_id is set only on a draft card that must be sent as the stored
    draft (see gmail_create_draft_after_hook); the payload omits it otherwise.
    """

    to: list[str]
    subject: str | None
    body: str | None
    thread_id: str | None
    bcc: list[str] | str | None
    cc: list[str] | str | None
    is_html: bool | None
    attachments: list[AttachmentDisplay]
    draft_id: str | None = None

    def payload(self) -> dict[str, object]:
        card: dict[str, object] = {
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "thread_id": self.thread_id,
            "bcc": self.bcc,
            "cc": self.cc,
            "is_html": self.is_html,
            "attachments": self.attachments,
        }
        if self.draft_id is not None:
            card["draft_id"] = self.draft_id
        return card


class SentDraftSummary(TypedDict):
    id: str | None
    successful: bool
    message: str


class ContactsSummary(TypedDict):
    contacts: list[ContactSummary]
    total_count: int
    has_more: bool


class PeopleSearchSummary(TypedDict):
    people: list[ContactSummary]
    result_count: int


class AttachmentSummary(TypedDict):
    attachmentId: str | None
    filename: str | None
    mimeType: str | None
    size: int | None
    message: str


# The draft compose card, built before the tool runs but streamed after it, once
# Gmail has returned the draft id the card's Send button needs. Set and read
# within one tool execution, so a ContextVar is the whole lifetime.
_pending_draft_card: ContextVar[ComposeCard | None] = ContextVar(
    "gmail_pending_draft_card", default=None
)

_PersonField = TypeVar("_PersonField", GooglePersonName, GooglePersonValue)


def _primary(entries: Sequence[_PersonField]) -> _PersonField | None:
    """Return the entry People flagged as primary, else the first one, else None."""
    if not entries:
        return None
    return next(
        (entry for entry in entries if entry.metadata is not None and entry.metadata.primary),
        entries[0],
    )


def _display_name(name: GooglePersonName | None) -> str | None:
    """DisplayName off the primary name, or "Unknown" when People omitted it."""
    if name is None or "display_name" not in name.model_fields_set:
        return "Unknown"
    return name.display_name


def _entry_value(entry: GooglePersonValue | None) -> str | None:
    """Value off an email/phone entry, or "" when People omitted it."""
    if entry is None or "value" not in entry.model_fields_set:
        return ""
    return entry.value


@dataclass(frozen=True, slots=True)
class _Contact:
    """A People API person flattened to the primary name/email/phone the UI shows.

    Fallbacks key off model_fields_set, not None: matching the original .get(key, default) semantics (default only when the key is missing, an explicit null stays None) keeps the payload the web client and LLM already receive unchanged.
    """

    name: str | None
    email: str | None
    phone: str | None
    resource_name: str | None

    @classmethod
    def from_person(cls, person: GooglePerson) -> "_Contact":
        return cls(
            name=_display_name(_primary(person.names)),
            email=_entry_value(_primary(person.email_addresses)),
            phone=_entry_value(_primary(person.phone_numbers)),
            resource_name=(
                person.resource_name if "resource_name" in person.model_fields_set else ""
            ),
        )

    def card(self) -> ContactCard:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "resource_name": self.resource_name,
        }

    def summary(self) -> ContactSummary:
        """Trim the contact for the LLM: name always, email/phone only when known."""
        summary: ContactSummary = {"name": self.name}
        if self.email:
            summary["email"] = self.email
        if self.phone:
            summary["phone"] = self.phone
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
    """Hide the is_html parameter from the agent-facing schema.

    The before-hook always converts the body to HTML and sets the flag, so
    exposing it to the agent just invites bad choices (agent picks False,
    writes Markdown, Gmail renders **bold** as literal asterisks). The
    agent writes Markdown — everything else is our problem.
    """
    return _drop_param(schema, _IS_HTML_PARAM)


@register_schema_modifier(tools=["GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"])
def gmail_compose_require_subject_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Make subject a required, non-empty field for email composition.

    A blank subject reads as spam and gets buried, so require it with minLength — the function-calling / args-validation layer then rejects a call that omits or blanks it before the tool runs, which matters because before-hook exceptions are swallowed and schema enforcement is the only hard guarantee.
    """
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    if input_params is None:
        return schema
    if input_params.required is None:
        input_params.required = []
    if _SUBJECT_PARAM not in input_params.required:
        input_params.required.append(_SUBJECT_PARAM)

    subject = input_params.properties.get(_SUBJECT_PARAM) if input_params.properties else None
    if subject is not None:
        subject.minLength = 1
        subject.description = (
            "Email subject line. Required: write a clear, specific subject "
            "that summarizes the email. Never leave it blank."
        )
    schema.input_parameters = input_params.as_schema()
    return schema


@register_schema_modifier(tools=["GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_fetch_message_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Default GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID to format='full' for detailed content."""
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    if input_params is None:
        return schema

    fmt = input_params.properties.get(_FORMAT_PARAM) if input_params.properties else None
    if fmt is not None:
        fmt.default = "full"
        schema.input_parameters = input_params.as_schema()

    return schema


@register_schema_modifier(toolkits=["gmail"])
def gmail_hide_user_id_schema_modifier(tool: str, toolkit: str, schema: Tool) -> Tool:
    """Strip user_id from every Gmail tool's agent-facing schema.

    The mailbox is fixed by the connected account, so the Gmail userId must
    always be "me". Exposing it baits the agent into passing the literal
    address, which returns zero results; removing it forces Composio's default.
    """
    return _drop_param(schema, _USER_ID_PARAM)


def _drop_param(schema: Tool, param: str) -> Tool:
    """Remove param from a tool's agent-facing properties and its required list."""
    input_params = JsonSchemaNode.parse(schema.input_parameters)
    if input_params is None:
        return schema
    if input_params.properties is not None:
        input_params.properties.pop(param, None)
    if input_params.required and param in input_params.required:
        input_params.required.remove(param)
    schema.input_parameters = input_params.as_schema()
    return schema


# ====================== BEFORE EXECUTE HOOKS ======================
# These hooks send progress/streaming data to frontend before tool execution


def _normalize_compose_body(arguments: dict[str, object]) -> None:
    """Convert the Markdown body to HTML in place and flag it (idempotent).

    The agent writes Markdown; Gmail renders Markdown literally as plain text.
    """
    for body_key in _GMAIL_BODY_KEYS:
        raw_body = arguments.get(body_key)
        # Defensive guard; and->or is equivalent for realistic (str) bodies.
        if isinstance(raw_body, str) and raw_body:  # pragma: no mutate
            arguments[body_key] = normalize_email_body_to_html(raw_body)
    arguments[_IS_HTML_PARAM] = True


def _compose_recipient_ready(tool: str, arguments: dict[str, object]) -> bool:
    """Map to -> recipient_email and confirm a SEND/DRAFT call is streamable.

    Non-compose tools (reply/forward) are always ready. Returns False (and logs) when
    a SEND/DRAFT call is missing a recipient or any content, so streaming is skipped.
    """
    if tool not in ("GMAIL_SEND_EMAIL", "GMAIL_CREATE_EMAIL_DRAFT"):
        return True
    compose = GmailComposeArguments.model_validate(arguments)
    if _TO_PARAM in arguments and _RECIPIENT_EMAIL_PARAM not in arguments:
        arguments[_RECIPIENT_EMAIL_PARAM] = compose.to
        log.info(GMAIL_TO_MAPPED_LOG, tool=tool)  # pragma: no mutate
    has_recipient = bool(compose.recipient_email or compose.to or compose.cc or compose.bcc)
    has_content = bool(compose.subject or compose.body)
    if not has_recipient or not has_content:
        log.warning(GMAIL_SKIP_STREAM_LOG, tool=tool)  # pragma: no mutate
        return False
    return True


def _compose_recipients(tool: str, compose: GmailComposeArguments) -> list[str]:
    """Flatten the recipient set for the compose card, per tool."""
    if tool == "GMAIL_FORWARD_MESSAGE":
        recipients = compose.to_recipients
        return [recipients] if isinstance(recipients, str) else recipients
    extra_recipients = compose.extra_recipients
    if not isinstance(extra_recipients, list):
        extra_recipients = []
    return [compose.recipient_email, *extra_recipients]


def _compose_card(
    tool: str, compose: GmailComposeArguments, attachment_display: list[AttachmentDisplay]
) -> ComposeCard:
    """Build the compose/sent card for one Gmail compose call."""
    return ComposeCard(
        to=_compose_recipients(tool, compose),
        subject=compose.subject,
        body=compose.body,
        thread_id=compose.thread_id,
        bcc=compose.bcc,
        cc=compose.cc,
        is_html=compose.is_html,
        attachments=attachment_display,
    )


def _stream_compose_preview(
    tool: str, compose: GmailComposeArguments, attachment_display: list[AttachmentDisplay]
) -> None:
    """Stream the sent card now; hold the draft card until its id exists.

    A draft card's Send button sends the draft (attachments and all), which needs the id Gmail only returns once the tool has run; streaming it here would fall back to composing a fresh mail and silently drop every attachment, so the draft card is handed to gmail_create_draft_after_hook instead.
    """
    card = _compose_card(tool, compose, attachment_display)
    if tool == "GMAIL_CREATE_EMAIL_DRAFT":
        _pending_draft_card.set(card)
        return
    get_stream_writer()({"email_sent_data": [card.payload()]})


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
    """Resolve attachments, normalise the body, and stream the compose/sent card."""
    log.set(gmail_tool=tool, toolkit=toolkit)  # pragma: no mutate -- observability
    try:
        # Strict: raises HookAbortError if a file can't be attached, so we never
        # send mail missing a requested attachment. The native param name comes
        # from the swap record, not a constant: Composio names it per tool.
        native_param = swapped_upload_param(tool)
        attachment_display = (
            resolve_tool_attachments(tool, toolkit, params, native_param=native_param)
            if native_param
            else []
        )
        if attachment_display:
            log.set(gmail_attachment_count=len(attachment_display))  # pragma: no mutate
        # Read after attachment resolution, which rewrites the bag under the tool's
        # native upload param; the view is a copy, so the edits below reach the
        # tool only through the write-back.
        arguments = ComposioToolCall.model_validate(params).arguments
        _normalize_compose_body(arguments)
        params["arguments"] = arguments
        # Drop any card a previous draft call in this context left held, so an
        # aborted run can never have its card streamed by a later one.
        _pending_draft_card.set(None)
        if _compose_recipient_ready(tool, arguments):
            _stream_compose_preview(
                tool, GmailComposeArguments.model_validate(arguments), attachment_display
            )
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


@register_after_hook(tools=["GMAIL_CREATE_EMAIL_DRAFT"])
def gmail_create_draft_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> ToolExecutionResponse:
    """Stream the held compose card, now that the draft it describes exists; the response passes through untouched.

    A card with attachments gets the draft's id so its Send button sends this draft rather than recomposing from the card's visible fields — the only path that keeps the files. Without an id the card is dropped instead of shown with attachments it cannot deliver; a card with no attachments stays editable and is sent as a fresh compose.
    """
    card = _pending_draft_card.get()
    _pending_draft_card.set(None)
    if card is None:
        return response
    data = ComposioToolResponse.model_validate(response).data
    draft_id = GmailDraftCreatedData.model_validate(data).id if isinstance(data, dict) else None
    if card.attachments:
        if not draft_id:
            # Every send path open to this card recomposes the mail from its
            # visible fields, so it would go out without the files the card is
            # showing. No card at all beats a card that silently drops them.
            log.warning(GMAIL_DRAFT_ID_MISSING_LOG, tool=tool)  # pragma: no mutate
            return response
        # Only a card that MUST be sent as the stored draft carries the id: it is
        # what makes Send send this draft, and it is why the card renders
        # read-only (the draft's files cannot be re-attached to an edited copy).
        card.draft_id = draft_id
    writer = get_stream_writer()
    if writer is not None:
        writer({"email_compose_data": [card.payload()]})
    return response


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"])
def gmail_message_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process single message response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        if not isinstance(raw, dict) or "error" in raw:
            return raw

        # Transform raw message data to detailed but clean format
        return detailed_message_template(raw)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_message_detail_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_FETCH_MESSAGE_BY_THREAD_ID"])
def gmail_thread_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process thread response and send data to frontend."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if not isinstance(raw, dict) or "error" in raw:
            return raw

        processed_response = process_get_thread_response(raw)
        thread = GmailThreadView.model_validate(processed_response)

        if writer is not None and thread.messages:
            # Transform to EmailThreadData format for frontend
            thread_messages = [
                {
                    "id": msg.id,
                    "from": msg.sender,
                    "subject": msg.subject,
                    "time": msg.time,
                    "snippet": msg.snippet,
                    "body": msg.body,
                    "content": msg.content if msg.content is not None else "",
                }
                for msg in thread.messages
            ]

            # Send thread data to frontend
            payload = {
                "email_thread_data": {
                    "thread_id": thread.id,
                    "messages": thread_messages,
                    "messages_count": thread.message_count,
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
        return raw


@register_after_hook(tools=["GMAIL_LIST_DRAFTS"])
def gmail_drafts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process drafts list response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        if not isinstance(raw, dict) or "error" in raw:
            return raw

        return process_list_drafts_response(raw)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_drafts_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_GET_DRAFT"])
def gmail_draft_detail_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process single draft response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        if not isinstance(raw, dict) or "error" in raw:
            return raw

        # Transform raw draft data to clean format
        return draft_template(raw)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_draft_detail_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_FETCH_ATTACHMENT"])
def gmail_attachment_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process attachment response to extract metadata only."""
    result = ComposioToolResponse.model_validate(response)
    # Composio's envelope types `data` as a plain Dict, but this endpoint has been
    # observed returning a non-dict `data` (e.g. a bare string) on some error paths,
    # so both branches below pass the raw value through unprocessed.
    data = result.data
    try:
        if not result.successful:
            return data

        # Extract only metadata, not the base64 content
        if not isinstance(data, dict):
            return data

        attachment = GmailAttachmentData.model_validate(data)
        summary: AttachmentSummary = {
            "attachmentId": attachment.attachment_id,
            "filename": attachment.filename,
            "mimeType": attachment.mime_type,
            "size": attachment.size,
            "message": "Attachment content available but not displayed to preserve context",
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_attachment_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return data


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

        if tool == "GMAIL_CREATE_LABEL":
            arguments = GmailLabelArguments.model_validate(
                ComposioToolCall.model_validate(params).arguments
            )
            payload = {"progress": f"Creating label: {arguments.name}..."}
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

        arguments = GmailModifyLabelsArguments.model_validate(
            ComposioToolCall.model_validate(params).arguments
        )
        message_ids = arguments.message_ids
        label_ids = arguments.label_ids

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

        arguments = GmailListDraftsArguments.model_validate(
            ComposioToolCall.model_validate(params).arguments
        )

        payload = {"progress": f"Fetching drafts (max {arguments.max_results} results)..."}
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
        arguments = ComposioToolCall.model_validate(params).arguments

        # Set default page size to 50 if not specified
        if not GmailGetContactsArguments.model_validate(arguments).page_size:
            arguments[_PAGE_SIZE_PARAM] = _DEFAULT_CONTACTS_PAGE_SIZE

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
            arguments = GmailSearchPeopleArguments.model_validate(
                ComposioToolCall.model_validate(params).arguments
            )
            payload = {"progress": f"Searching for people matching '{arguments.query}'..."}
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
) -> AfterHookResponse:
    """Process single email fetch response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        if not isinstance(raw, dict) or "error" in raw:
            return raw

        # Transform raw message data to detailed but clean format
        return detailed_message_template(raw)

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_fetch_by_id_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_SEND_DRAFT"])
def gmail_send_draft_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process draft sending response."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        sent = GmailSentDraftData.model_validate(raw)
        # ``successful`` reads with two defaults: the card streams unless the key
        # says otherwise, the LLM summary only when the key is present and true.
        successful_present = "successful" in sent.model_fields_set

        if writer is not None and (sent.successful if successful_present else True):
            # Send email sent data to frontend
            message_data = sent.message or GmailSentDraftMessage()

            payload = {
                "email_sent_data": [
                    {
                        "message_id": sent.id,
                        "message": "Draft sent successfully!",
                        "timestamp": sent.timestamp,
                        "recipients": message_data.to,
                        "subject": message_data.subject,
                    }
                ]
            }
            writer(payload)

        # Keep the response minimal for LLM
        if successful_present and sent.successful:
            summary: SentDraftSummary = {
                "id": sent.id,
                "successful": True,
                "message": "Draft sent successfully",
            }
            return summary
        return raw

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_send_draft_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_GET_CONTACTS"])
def gmail_get_contacts_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process contacts list response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if not isinstance(raw, dict) or "error" in raw:
            return raw

        data = GmailContactsData.model_validate(raw)
        response_data = data.response_data or GoogleContactsResponseData()

        contacts = [_Contact.from_person(person) for person in response_data.connections]
        contact_list: list[ContactCard] = [contact.card() for contact in contacts]
        llm_contacts: list[ContactSummary] = [contact.summary() for contact in contacts]
        total_count = data.total_people if data.total_people is not None else len(contacts)

        # Send to frontend
        if writer is not None and contact_list:
            payload = {
                "contacts_data": contact_list,
                "total_count": total_count,
                "next_page_token": data.next_page_token,
            }
            writer(payload)

        # Return minimal data for LLM
        summary: ContactsSummary = {
            "contacts": llm_contacts,
            "total_count": total_count,
            "has_more": bool(data.next_page_token),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_get_contacts_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw


@register_after_hook(tools=["GMAIL_SEARCH_PEOPLE"])
def gmail_search_people_after_hook(
    tool: str, toolkit: str, response: ToolExecutionResponse
) -> AfterHookResponse:
    """Process people search response to minimize raw data."""
    raw = ComposioToolResponse.model_validate(response).data
    try:
        writer = get_stream_writer()

        if not isinstance(raw, dict) or "error" in raw:
            return raw

        data = GmailSearchPeopleData.model_validate(raw)
        response_data = data.response_data or GooglePeopleSearchResponseData()

        people = [_Contact.from_person(result.person) for result in response_data.results]
        people_list: list[ContactCard] = [person.card() for person in people]
        llm_people: list[ContactSummary] = [person.summary() for person in people]

        # Send to frontend
        if writer is not None and people_list:
            payload = {
                "people_search_data": people_list,
                "result_count": len(people_list),
            }
            writer(payload)

        # Return minimal data for LLM
        summary: PeopleSearchSummary = {
            "people": llm_people,
            "result_count": len(llm_people),
        }
        return summary

    except Exception as e:
        log.error(
            f"{LogTag.COMPOSIO} Error in gmail_search_people_after_hook",
            error=str(e),
            error_type=type(e).__name__,
        )
        return raw
