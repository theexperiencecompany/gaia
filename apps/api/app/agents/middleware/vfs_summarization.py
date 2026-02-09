"""
VFS Archiving Summarization Middleware.

Extends LangChain's SummarizationMiddleware to archive conversation history
to VFS before summarization occurs.

This middleware:
1. Uses LangChain's built-in fraction-based triggering (auto-detects context window)
2. Archives full message history to VFS before summarization
3. Adds archive path reference to the summary message
"""

import json
from datetime import datetime, timezone
from typing import Any

from app.config.loggers import app_logger as logger
from app.services.vfs.path_resolver import get_session_path
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig


class VFSArchivingSummarizationMiddleware(SummarizationMiddleware):
    """
    Extends SummarizationMiddleware to archive to VFS before summarizing.

    This middleware monitors token usage and automatically:
    1. Archives full conversation history to VFS when threshold is reached
    2. Calls parent's summarization logic
    3. Injects archive path into the summary for context recovery

    Usage:
        middleware = VFSArchivingSummarizationMiddleware(
            model="gpt-4o-mini",
            trigger=("fraction", 0.85),  # 85% of context window
            keep=("messages", 15),
            vfs_enabled=True,
        )
    """

    def __init__(
        self,
        model: str | BaseChatModel,
        *,
        trigger=("fraction", 0.85),
        keep=("messages", 15),
        vfs_enabled: bool = True,
        **kwargs,
    ):
        """
        Initialize the VFS archiving summarization middleware.

        Args:
            model: Model to use for summarization (string name or BaseChatModel)
            trigger: When to trigger summarization. Defaults to 85% of context.
                     Can be ("fraction", 0.85), ("tokens", 8000), or ("messages", 50)
            keep: How many messages to keep after summarization.
                  Defaults to 15 messages.
            vfs_enabled: Whether to archive to VFS before summarization
            **kwargs: Additional arguments passed to SummarizationMiddleware
        """
        super().__init__(
            model=model,
            trigger=trigger,
            keep=keep,
            **kwargs,
        )
        self.vfs_enabled = vfs_enabled
        self._vfs = None  # Lazy loaded
        self._last_archive_path: str | None = None

    async def _get_vfs(self):
        """Lazy load VFS."""
        if self._vfs is None:
            from app.services.vfs import get_vfs

            self._vfs = await get_vfs()
        return self._vfs

    async def abefore_model(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """
        Called before each model invocation.

        Archives to VFS if summarization will occur, then delegates to parent.
        """
        # Check if we should archive (if parent will summarize)
        if self.vfs_enabled and self._should_trigger_summarization(state):
            try:
                await self._archive_to_vfs(state, runtime)
            except Exception as e:
                logger.error(f"VFS archiving failed: {e}")

        # Call parent's summarization logic
        result = await super().abefore_model(state, runtime)

        # If summarization occurred and we have an archive path, inject it
        if result is not None and self._last_archive_path:
            result = self._inject_archive_path(result)
            self._last_archive_path = None

        return result

    def _should_trigger_summarization(self, state: dict[str, Any]) -> bool:
        """Check if summarization will be triggered based on current state."""
        # Access parent's internal check if available
        # For now, we rely on token counting
        messages = state.get("messages", [])
        if not messages:
            return False

        try:
            token_count = self._token_counter(messages)
            # Get trigger threshold
            if isinstance(self._trigger, tuple):
                trigger_type, trigger_value = self._trigger
                if trigger_type == "fraction":
                    # Estimate max tokens (this is approximate)
                    max_tokens = getattr(self, "_max_tokens", 128000)
                    return token_count > max_tokens * trigger_value
                elif trigger_type == "tokens":
                    return token_count > trigger_value
                elif trigger_type == "messages":
                    return len(messages) > trigger_value
        except Exception:
            pass  # Intentional: fallback if token counter unavailable  # nosec B110

        return False

    async def _archive_to_vfs(self, state: dict[str, Any], runtime: Any) -> str:
        """Archive full conversation to VFS before summarization."""
        messages = state.get("messages", [])

        # Extract user_id and conversation_id from runtime config
        config: RunnableConfig = getattr(runtime, "config", {}) or {}
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")
        conversation_id = configurable.get("thread_id")

        if not user_id or not conversation_id:
            logger.warning("Cannot archive: missing user_id or conversation_id")
            return ""

        vfs = await self._get_vfs()

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_path = get_session_path(user_id, conversation_id)
        archive_path = f"{session_path}/archives/pre_summary_{timestamp}.json"

        # Serialize messages
        history = self._serialize_messages(messages)

        await vfs.write(
            path=archive_path,
            content=json.dumps(history, indent=2, default=str),
            user_id=user_id,
            metadata={
                "type": "pre_summarization_archive",
                "conversation_id": conversation_id,
                "message_count": len(messages),
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "trigger_reason": "summarization_middleware",
            },
        )

        logger.info(
            f"Archived {len(messages)} messages to {archive_path} before summarization"
        )
        self._last_archive_path = archive_path
        return archive_path

    def _serialize_messages(self, messages: list[AnyMessage]) -> list[dict[str, Any]]:
        """Serialize messages for VFS storage."""
        history = []
        for msg in messages:
            entry: dict[str, Any] = {
                "type": type(msg).__name__,
                "content": msg.content if hasattr(msg, "content") else str(msg),
            }

            # Handle tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "args": tc.get("args"),
                    }
                    for tc in msg.tool_calls
                ]

            # Handle tool messages
            if isinstance(msg, ToolMessage):
                entry["tool_call_id"] = msg.tool_call_id
                entry["name"] = getattr(msg, "name", None)

            history.append(entry)

        return history

    def _inject_archive_path(self, result: dict[str, Any]) -> dict[str, Any]:
        """Inject archive path reference into the summarized messages."""
        if not self._last_archive_path:
            return result

        messages = result.get("messages", [])
        if not messages:
            return result

        # Find the summary message (usually a HumanMessage with is_summary=True)
        for i, msg in enumerate(messages):
            if isinstance(msg, HumanMessage):
                additional_kwargs = getattr(msg, "additional_kwargs", {})
                if additional_kwargs.get("is_summary"):
                    # Add archive path to content
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        msg.content += (
                            f"\n\n[Full history archived at: {self._last_archive_path}]"
                        )
                    additional_kwargs["archive_path"] = self._last_archive_path
                    break

        return result
