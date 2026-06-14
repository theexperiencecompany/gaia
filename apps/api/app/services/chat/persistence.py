"""Conversation initialization, persistence, and post-stream billing.

Three concerns kept together because they share the user/conversation shape:
:func:`initialize_new_conversation` writes the conversation row and returns the
init SSE chunk; :func:`save_conversation_async` writes the user + bot messages
on stream end; :func:`process_token_usage_and_cost` debits tiered credits from
the LangChain ``usage_metadata`` once the stream is done.

:func:`absolutize_artifact_urls` rewrites relative ``./artifacts/<name>``
references inside the bot response to absolute backend URLs so the saved
message renders correctly even when the user's browser is holding a stale
frontend chunk.
"""

from datetime import UTC, datetime, timedelta
import json
import re
from typing import Any

from app.api.v1.middleware.tiered_rate_limiter import tiered_limiter
from app.config.model_pricing import calculate_token_cost
from app.config.settings import settings
from app.models.chat_models import MessageModel, UpdateMessagesRequest
from app.models.message_models import MessageRequestWithHistory
from app.models.payment_models import PlanType
from app.services.conversation_service import update_messages
from app.services.payments.payment_service import payment_service
from app.services.storage import JuiceFSUnavailable, ensure_session_dirs
from app.utils.chat_utils import create_conversation
from shared.py.wide_events import log

# Matches bot-emitted artifact references in three shapes — ``./artifacts/x``,
# ``/artifacts/x``, and plain ``artifacts/x`` — so we can rewrite each to an
# absolute backend URL. Allows quotes, parens or whitespace right before
# (markdown image links, OpenUI string args, plain prose) but requires no
# leading "word" character so we don't mangle ``myartifacts/``.
_ARTIFACT_REF_RE = re.compile(
    r"""(?P<lead>(?<![A-Za-z0-9_/])|(?<=['"`(\s]))(?P<prefix>\.\/|\/)?artifacts\/(?P<path>[A-Za-z0-9._\-/]+)""",
    re.VERBOSE,
)


async def initialize_new_conversation(
    body: MessageRequestWithHistory,
    user: dict,
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

    # Conversation creation owns the per-conversation session dirs (scratch/,
    # user-uploaded/, artifacts/) — this is the only event that creates a
    # conversation, so dir creation no longer runs on every chat turn. Soft-fail
    # when JuiceFS is unmounted (native dev); file/artifact tools surface the
    # missing mount clearly if used.
    user_id = user.get("user_id")
    if user_id:
        try:
            await ensure_session_dirs(user_id, conversation_id)
        except JuiceFSUnavailable:
            pass

    init_data = {
        "conversation_id": conversation_id,
        "conversation_description": conversation.get("description"),
        "user_message_id": user_message_id,
        "bot_message_id": bot_message_id,
        "stream_id": stream_id,
    }

    return f"data: {json.dumps(init_data)}\n\n"


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

    base = f"{settings.HOST}/api/v1/sessions/{conversation_id}/artifacts"

    def _sub(m: re.Match[str]) -> str:
        # Preserve leading whitespace/quote so we don't break adjacent syntax.
        lead = m.group("lead") or ""
        return f"{lead}{base}/{m.group('path')}"

    return _ARTIFACT_REF_RE.sub(_sub, message)


async def save_conversation_async(
    body: MessageRequestWithHistory,
    user: dict,
    conversation_id: str,
    complete_message: str,
    tool_data: dict[str, Any],
    metadata: dict[str, Any],
    user_message_id: str,
    bot_message_id: str,
) -> None:
    """Persist the finished turn to Mongo and bill token usage.

    Bakes absolute artifact URLs into the saved bot message so the chat renders
    correctly even when the user's browser holds a stale frontend chunk.
    """
    user_id = user.get("user_id")

    if metadata and user_id:
        try:
            await process_token_usage_and_cost(user_id, metadata)
        except Exception as e:  # noqa: BLE001 — billing failure must not block save
            log.error(f"Failed to process token usage: {e}")

    bot_timestamp = datetime.now(UTC)
    user_timestamp = bot_timestamp - timedelta(milliseconds=100)

    user_content = (
        body.messages[-1].get("content") if body.messages and len(body.messages) > 0 else None
    ) or body.message

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


async def process_token_usage_and_cost(user_id: str, metadata: dict[str, Any]) -> None:
    """Translate the LangChain ``usage_metadata`` into credit debits.

    Cache reads are billed at the discounted rate (not free) — we read them
    from ``input_token_details.cache_read`` per LangChain canonical shape, with
    a fallback to the older ``cached_content_token_count`` for older SDKs.
    """
    try:
        subscription = await payment_service.get_user_subscription_status(user_id)
        user_plan = subscription.plan_type or PlanType.FREE

        total_credits = 0.0

        for model_name, usage_data in metadata.items():
            if not isinstance(usage_data, dict):
                continue
            input_tokens = usage_data.get("input_tokens", 0)
            output_tokens = usage_data.get("output_tokens", 0)
            details = usage_data.get("input_token_details") or {}
            cached_tokens = int(
                details.get("cache_read") or usage_data.get("cached_content_token_count") or 0
            )

            if input_tokens > 0 or output_tokens > 0:
                cost_info = await calculate_token_cost(
                    model_name,
                    input_tokens,
                    output_tokens,
                    cached_tokens=cached_tokens,
                )
                total_credits += cost_info["total_cost"]

        if total_credits > 0:
            await tiered_limiter.check_and_increment(
                user_id=user_id,
                feature_key="chat_messages",
                user_plan=user_plan,
                credits_used=total_credits,
            )

        existing_model = log.get().get("model", {})
        log.set(
            model={**existing_model, "cost_usd": round(total_credits, 6)},
            user_plan=str(user_plan),
        )

    except Exception as e:  # noqa: BLE001 — billing failure must not block save
        log.debug(f"Token usage processing failed: {e}")
