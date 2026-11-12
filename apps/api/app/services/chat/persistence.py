"""Conversation initialization and persistence.

Two concerns kept together because they share the user/conversation shape:
:func:initialize_new_conversation writes the conversation row;
:func:save_user_message writes the user message as the turn begins,
:func:open_bot_reply takes the reply's place in the order when the user first
sees it, and :func:save_bot_reply writes the reply when it ends. Spend is NOT billed here — every model call is metered once, at
the point of the call, by LLMAccountingMiddleware (see
app.services.llm_metering); a second pass over the stream's aggregate
usage_metadata used to re-count the turn against chat_messages as well.

:func:absolutize_artifact_urls rewrites relative ./artifacts/<name>
references inside the bot response to absolute backend URLs so the saved
message renders correctly even when the user's browser is holding a stale
frontend chunk.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re

from app.constants.chat import ARTIFACT_REF_RE, USER_MESSAGE_TYPE, WORKSPACE_ARTIFACT_RE
from app.db.repositories.conversations import conversation_repository
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import MessageDict, MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import update_messages
from app.utils.artifact_utils import artifact_url_base
from app.utils.chat_utils import create_conversation
from app.utils.errors import ConversationNotFoundError


def user_message_content_from(body: MessageRequestWithHistory) -> str:
    """Return the turn's user message text; the single derivation for init + persist.

    Clients omit empty-text turns (file-only sends) from messages, so the
    last history entry is the current turn only when its role is user —
    otherwise it is the previous assistant reply and must not be used.
    """
    last: MessageDict | None = body.messages[-1] if body.messages else None
    if last and last.get("role") == "user":
        return last.get("content") or body.message
    return body.message


async def initialize_new_conversation(
    body: MessageRequestWithHistory, user: AuthenticatedUser, conversation_id: str
) -> str:
    """Create the conversation row and return its description."""
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
    return conversation.description


def absolutize_artifact_urls(message: str, conversation_id: str) -> str:
    """Rewrite relative artifact paths in a bot response to absolute backend URLs.

    ./artifacts/<name> is correct inside the sandbox but breaks when the
    frontend fetches it from the browser origin; substituting the full URL
    once at save time renders correctly even with a stale frontend bundle.
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


async def save_user_message(
    body: MessageRequestWithHistory,
    user: AuthenticatedUser,
    conversation_id: str,
    user_message_id: str,
) -> int:
    """Persist the turn's user message before any agent work runs, returning its seq.

    Written ahead of the reply because the work it asks for commits on its own:
    a turn that dies mid-run must still show the user what they asked.
    """
    user_message = MessageModel(
        type=USER_MESSAGE_TYPE,
        response=user_message_content_from(body),
        date=datetime.now(UTC).isoformat(),
        fileIds=body.fileIds,
        fileData=body.fileData,
        selectedTool=body.selectedTool,
        toolCategory=body.toolCategory,
        selectedWorkflow=body.selectedWorkflow,
        replyToMessage=body.replyToMessage,
        platform_message_id=body.platform_message_id,
    )
    user_message.message_id = user_message_id
    saved = await update_messages(
        UpdateMessagesRequest(conversation_id=conversation_id, messages=[user_message]),
        user=user,
    )
    return saved.message_seqs[0]


async def open_bot_reply(
    body: MessageRequestWithHistory,
    user: AuthenticatedUser,
    conversation_id: str,
    bot_message_id: str,
) -> int:
    """Append the reply's entry, empty and in progress, as the user first sees it; return its seq."""
    reply = MessageModel(
        type="bot",
        response="",
        date=datetime.now(UTC).isoformat(),
        fileIds=body.fileIds,
        message_id=bot_message_id,
        in_progress=True,
    )
    saved = await update_messages(
        UpdateMessagesRequest(conversation_id=conversation_id, messages=[reply]), user=user
    )
    return saved.message_seqs[0]


@dataclass(frozen=True)
class BotReply:
    """What one turn's reply saves: its text, cards and the stamps a reload needs."""

    complete_message: str
    bot_message_id: str
    tool_data: Mapping[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    follow_up_actions: list[str] | None = None
    #: The user cut this turn off with Stop.
    stopped: bool = False
    #: Its entry was opened (open_bot_reply), so it is filled in place rather than appended.
    opened: bool = False


async def save_bot_reply(
    body: MessageRequestWithHistory,
    user: AuthenticatedUser,
    conversation_id: str,
    reply: BotReply,
) -> int | None:
    """Persist the turn's reply, returning its seq when appended; an opened entry keeps its own.

    Artifact URLs are baked absolute so a stale frontend chunk still renders.
    """
    rendered_message = absolutize_artifact_urls(reply.complete_message, conversation_id)

    bot_message = MessageModel(
        type="bot",
        response=rendered_message,
        date=datetime.now(UTC).isoformat(),
        fileIds=body.fileIds,
        metadata=reply.metadata,
        error=reply.error,
        # Persisted here rather than patched in afterwards: the chips are part
        # of the turn the user saw, so a reload, a sync, or a second device must
        # rebuild them from the saved message alone.
        follow_up_actions=reply.follow_up_actions,
        stopped=reply.stopped or None,
    )
    bot_message.message_id = reply.bot_message_id

    for key, value in reply.tool_data.items():
        setattr(bot_message, key, value)

    if reply.opened:
        if not await conversation_repository.fill_message(
            conversation_id, user_id=user.user_id, message=bot_message
        ):
            raise ConversationNotFoundError(
                message=f"the opened reply {reply.bot_message_id} is gone from its conversation",
                meta={"conversation_id": conversation_id},
            )
        return None
    saved = await update_messages(
        UpdateMessagesRequest(conversation_id=conversation_id, messages=[bot_message]), user=user
    )
    return saved.message_seqs[0]
