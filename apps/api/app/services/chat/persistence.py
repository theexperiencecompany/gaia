"""Conversation initialization and persistence.

Two concerns kept together because they share the user/conversation shape:
:func:`initialize_new_conversation` writes the conversation row and returns the
init SSE chunk; :func:`save_conversation_async` writes the user + bot messages
on stream end. Spend is NOT billed here — every model call is metered once, at
the point of the call, by ``LLMAccountingMiddleware`` (see
``app.services.llm_metering``); a second pass over the stream's aggregate
``usage_metadata`` used to re-count the turn against ``chat_messages`` as well.

:func:`absolutize_artifact_urls` rewrites relative ``./artifacts/<name>``
references inside the bot response to absolute backend URLs so the saved
message renders correctly even when the user's browser is holding a stale
frontend chunk.
"""

from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any

from app.constants.chat import ARTIFACT_REF_RE, WORKSPACE_ARTIFACT_RE
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import MessageRequestWithHistory
from app.models.stream_events import ConversationInitializedFrame
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.utils.artifact_utils import artifact_url_base
from app.utils.chat_utils import create_conversation


def user_message_content_from(body: MessageRequestWithHistory) -> str:
    """The turn's user message text — single derivation for init + persist.

    Clients omit empty-text turns (file-only sends) from ``messages``, so the
    last history entry is the current turn only when its role is ``user`` —
    otherwise it is the previous assistant reply and must not be used.
    """
    last = body.messages[-1] if body.messages else None
    if last and last.get("role") == "user":
        return last.get("content") or body.message
    return body.message


async def initialize_new_conversation(
    body: MessageRequestWithHistory,
    user: AuthenticatedUser,
    conversation_id: str,
    user_message_id: str,
    bot_message_id: str,
    stream_id: str,
) -> str:
    """Create the conversation row and return the init SSE chunk."""
    last_message = body.messages[-1] if body.messages else None

    conversation = await create_conversation(
        last_message,
        user=user,
        selectedTool=body.selectedTool,
        selectedWorkflow=body.selectedWorkflow,
        generate_description=False,
        conversation_id=conversation_id,
    )

    # Per-conversation session dirs (scratch/, user-uploaded/, artifacts/) are
    # created on demand by the write/bash paths and `.meta.json` by the post-init
    # last-active touch — so we keep JuiceFS off the first-message critical path.

    init_frame = ConversationInitializedFrame(
        conversation_id=conversation_id,
        conversation_description=conversation.description,
        user_message_id=user_message_id,
        user_message_content=user_message_content_from(body),
        bot_message_id=bot_message_id,
        stream_id=stream_id,
    )

    return f"data: {json.dumps(init_frame.model_dump())}\n\n"


def absolutize_artifact_urls(message: str, conversation_id: str) -> str:
    """Rewrite relative artifact paths in a bot response to absolute backend URLs.

    The agent's prompt teaches it to reference files at ``./artifacts/<name>``,
    which is correct INSIDE the sandbox but breaks when the frontend tries to
    fetch the same path from the browser origin. Substituting the full
    ``<HOST>/api/v1/sessions/<conv>/artifacts/<name>`` URL once at save time
    means the saved message renders the right image regardless of whether the
    user's browser still holds a stale frontend bundle.
    """
    if not message or not conversation_id:
        return message

    base = artifact_url_base(conversation_id)

    def _sub(m: re.Match[str]) -> str:
        # Preserve leading whitespace/quote so we don't break adjacent syntax.
        lead = m.group("lead") or ""
        return f"{lead}{base}/{m.group('path')}"

    message = WORKSPACE_ARTIFACT_RE.sub(lambda m: f"{base}/{m.group('path')}", message)
    return ARTIFACT_REF_RE.sub(_sub, message)


async def save_conversation_async(
    body: MessageRequestWithHistory,
    user: AuthenticatedUser,
    conversation_id: str,
    complete_message: str,
    tool_data: dict[str, Any],
    metadata: dict[str, Any],
    user_message_id: str,
    bot_message_id: str,
    bot_timestamp: datetime | None = None,
    error: str | None = None,
    follow_up_actions: list[str] | None = None,
) -> None:
    """Persist the finished turn to Mongo and bill token usage.

    Bakes absolute artifact URLs into the saved bot message so the chat renders
    correctly even when the user's browser holds a stale frontend chunk.

    ``bot_timestamp`` lets the caller stamp the turn at comms-completion time
    rather than now() — needed in voice mode, where finalize is deferred until a
    delegated executor finishes, so the user/comms messages must still sort ahead
    of the executor's answer (saved mid-wait).
    """
    bot_timestamp = bot_timestamp or datetime.now(UTC)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

    user_content = user_message_content_from(body)

    user_message = MessageModel(
        type="user",
        response=user_content,
        date=user_timestamp.isoformat(),
        fileIds=body.fileIds,
        fileData=body.fileData,
        selectedTool=body.selectedTool,
        toolCategory=body.toolCategory,
        selectedWorkflow=body.selectedWorkflow,
        replyToMessage=body.replyToMessage,
    )
    user_message.message_id = user_message_id

    rendered_message = absolutize_artifact_urls(complete_message, conversation_id)

    bot_message = MessageModel(
        type="bot",
        response=rendered_message,
        date=bot_timestamp.isoformat(),
        fileIds=body.fileIds,
        metadata=metadata,
        error=error,
        # Persisted here rather than patched in afterwards: the chips are part
        # of the turn the user saw, so a reload, a sync, or a second device must
        # rebuild them from the saved message alone.
        follow_up_actions=follow_up_actions,
    )
    bot_message.message_id = bot_message_id

    for key, value in tool_data.items():
        setattr(bot_message, key, value)

    await update_messages(
        UpdateMessagesRequest(
            conversation_id=conversation_id,
            messages=[user_message, bot_message],
        ),
        user=user,
    )
