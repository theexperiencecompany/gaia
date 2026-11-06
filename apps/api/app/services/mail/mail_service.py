import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import UploadFile
from langchain_core.tools import StructuredTool

from app.constants.email import GMAIL_MULTIPLE_ATTACHMENTS_ERROR
from app.constants.log_tags import LogTag
from app.models.mail_models import (
    ComposioAttachment,
    GmailFetchEmailsData,
    GmailMessagesResponse,
    GmailToolResult,
)
from app.services.composio.attachments import upload_bytes_sync
from app.services.composio.composio_service import (
    get_composio_service,
)
from app.utils.general_utils import transform_gmail_message
from shared.py.wide_events import MailContext, log


def get_gmail_tool(
    tool_name: str, user_id: str, *, use_schema_modifier: bool = True
) -> StructuredTool | None:
    """Get a specific Gmail tool by name via ComposioService, or None if not found.

    use_schema_modifier=False asks for the tool's own schema instead of the
    agent-facing one. Callers that speak Composio's native argument shape need
    it: the modifiers exist to hide that shape from the model, and LangChain
    silently drops any argument the bound schema does not declare.
    """
    log.set(user={"id": user_id}, mail=MailContext(provider="gmail"))
    composio_service = get_composio_service()

    try:
        return composio_service.get_tool(
            tool_name,
            use_before_hook=False,
            use_after_hook=False,
            use_schema_modifier=use_schema_modifier,
            user_id=user_id,
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
    user_id: str,
    tool_name: str,
    parameters: Mapping[str, object],
    *,
    use_schema_modifier: bool = True,
) -> GmailToolResult:
    """Invoke a specific Gmail tool with the given parameters.

    parameters stays a loose mapping on purpose: every Gmail tool accepts a
    different argument set, and Composio validates it against the tool's own schema.
    use_schema_modifier is passed through to get_gmail_tool.
    """
    try:
        tool = get_gmail_tool(tool_name, user_id, use_schema_modifier=use_schema_modifier)

        if not tool:
            return GmailToolResult(error=f"Tool {tool_name} not found", successful=False)

        result = await tool.ainvoke(dict(parameters))
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


def _process_attachments(attachments: list[UploadFile], tool_name: str) -> list[ComposioAttachment]:
    """Upload each multipart file to Composio, returning its {name, mimetype, s3key}.

    Composio's compose tools take files already uploaded to their store, not raw
    bytes; upload_bytes_sync does that upload. Runs sync (called via
    asyncio.to_thread) because the Composio upload client is synchronous.
    """
    processed: list[ComposioAttachment] = []
    for att in attachments:
        content = att.file.read()
        att.file.seek(0)  # reset so a later reader sees the whole file
        processed.append(
            upload_bytes_sync(
                content,
                att.filename or "attachment",
                att.content_type,
                tool=tool_name,
                toolkit="gmail",
            )
        )
    return processed


@dataclass
class EmailContent:
    """Subject/body plus the secondary recipients of one Gmail compose or draft."""

    subject: str
    body: str
    extra_recipients: list[str] | None = None
    cc_list: list[str] | None = None
    bcc_list: list[str] | None = None


@dataclass
class MessageFetchOptions:
    """Presentation knobs for fetched/searched Gmail messages."""

    output_format: str | None = None
    include_payload: bool | None = None
    verbose: bool | None = None


async def send_email(
    user_id: str,
    to: str,
    content: EmailContent,
    *,
    thread_id: str | None = None,
    attachments: list[UploadFile] | None = None,
) -> GmailToolResult:
    """Send an email via Composio Gmail tools.

    Uses GMAIL_REPLY_TO_THREAD when thread_id is given, else GMAIL_SEND_EMAIL.
    The body is handed to Gmail as given: this path runs no Composio hooks, so
    the Markdown-to-HTML normalisation the agent path gets does not apply here.
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

        parameters: dict[str, Any] = {
            "recipient_email": to,
            "extra_recipients": content.extra_recipients or [],
            body_param: content.body,
            "subject": content.subject,
        }

        # Add thread_id for replies
        if is_reply:
            parameters["thread_id"] = thread_id

        # Add optional parameters
        if content.cc_list:
            parameters["cc"] = content.cc_list
        if content.bcc_list:
            parameters["bcc"] = content.bcc_list
        if attachments:
            # Composio types Gmail's `attachment` as a single FileUploadable, not
            # an array, so reject extra files up front instead of uploading them
            # all and failing the send.
            if len(attachments) > 1:
                return GmailToolResult(error=GMAIL_MULTIPLE_ATTACHMENTS_ERROR, successful=False)
            processed = await asyncio.to_thread(_process_attachments, attachments, tool_name)
            parameters["attachment"] = processed[0]

        log.info(
            f"{LogTag.MAIL} Sending email via Gmail tool",
            tool_name=tool_name,
            is_reply=is_reply,
            thread_id=thread_id,
            to=to,
        )

        # ``attachment`` is Gmail's native param; the agent schema modifier swaps it
        # for ``attachments``, but its before-hook is off on this path, so that
        # schema would drop the key and send with no file — use the native schema.
        result = await invoke_gmail_tool(
            user_id, tool_name, parameters, use_schema_modifier=not attachments
        )
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


async def search_messages(
    user_id: str,
    query: str | None = None,
    max_results: int = 20,
    page_token: str | None = None,
    options: MessageFetchOptions | None = None,
) -> GmailMessagesResponse:
    """
    Search Gmail messages using Composio Gmail tool.

    Pass MessageFetchOptions(output_format="metadata", include_payload=False,
    verbose=False) to skip body decode and bypass GMAIL_FULL_FETCH_HARD_LIMIT.
    """
    log.set(user={"id": user_id}, mail=MailContext(operation="fetch", provider="gmail"))
    opts = options or MessageFetchOptions()
    try:
        parameters: dict[str, Any] = {
            "query": query or "",
            "max_results": max_results,
        }
        if page_token:
            parameters["page_token"] = page_token
        if opts.output_format is not None:
            parameters["format"] = opts.output_format
        if opts.include_payload is not None:
            parameters["include_payload"] = opts.include_payload
        if opts.verbose is not None:
            parameters["verbose"] = opts.verbose

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
        raise


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
