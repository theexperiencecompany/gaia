"""
VFS Compaction Middleware.

Uses LangChain's wrap_tool_call hook to compact large tool outputs
to VFS storage, replacing them with references.

This middleware:
1. Intercepts tool results via wrap_tool_call
2. Stores large outputs in VFS
3. Returns file reference instead of raw content

Two independent compaction triggers:
- Per-tool: Single tool output > max_output_chars (always, regardless of context)
- Thread-level: Context usage exceeds compaction_threshold (compacts any output > MIN_COMPACTION_SIZE)
- Always: Tool is in always_persist_tools list
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.config.loggers import app_logger as logger
from app.constants.summarization import MIN_COMPACTION_SIZE
from app.services.vfs.path_resolver import get_session_path
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage


class VFSCompactionMiddleware(AgentMiddleware):
    """
    Compacts large tool outputs to VFS using wrap_tool_call.

    Two independent triggers:
    1. Per-tool: Any single output > max_output_chars → compact immediately
    2. Thread-level: Context usage > compaction_threshold → compact outputs > MIN_COMPACTION_SIZE

    Usage:
        middleware = VFSCompactionMiddleware(
            max_output_chars=20000,     # Single output > 20k chars → compact
            compaction_threshold=0.65,  # Thread at 65% context → compact all
        )
    """

    def __init__(
        self,
        compaction_threshold: float = 0.65,
        max_output_chars: int = 20000,
        always_persist_tools: list[str] | None = None,
        context_window: int = 128000,
        excluded_tools: set[str] | None = None,
    ):
        """
        Initialize the VFS compaction middleware.

        Args:
            compaction_threshold: Thread context usage fraction (0-1) above which
                                  all tool outputs (> MIN_COMPACTION_SIZE) are compacted
            max_output_chars: Character count threshold for a single tool output —
                              outputs exceeding this are always compacted regardless
                              of thread context usage
            always_persist_tools: Tools whose output should always be persisted
            context_window: Total context window size in tokens (for threshold calc)
            excluded_tools: Tools whose output should NEVER be compacted
        """
        super().__init__()
        self.compaction_threshold = compaction_threshold
        self.max_output_chars = max_output_chars
        self.always_persist_tools = always_persist_tools or []
        self.context_window = context_window
        self.excluded_tools = excluded_tools or set()
        self._vfs = None  # Lazy loaded

    async def _get_vfs(self):
        """Lazy load VFS."""
        if self._vfs is None:
            from app.services.vfs import get_vfs

            self._vfs = await get_vfs()
        return self._vfs

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]],
    ) -> ToolMessage:
        """
        Wrap tool execution to compact large outputs.

        Args:
            request: The tool call request
            handler: The next handler in the chain (or actual tool execution)

        Returns:
            ToolMessage with potentially compacted content
        """
        # Execute the tool
        result = await handler(request)

        # Get tool info
        tool_call = request.tool_call
        tool_name = (
            tool_call.get("name", "") if isinstance(tool_call, dict) else tool_call.name
        )

        # Get context usage from state if available
        context_usage = self._get_context_usage(request)

        # Check if compaction is needed
        should_compact, reason = self._should_compact(result, tool_name, context_usage)

        if should_compact:
            try:
                result = await self._compact_to_vfs(result, request, reason)
            except Exception as e:
                logger.error(f"VFS compaction failed for {tool_name}: {e}")

        return result

    def _get_context_usage(self, request: ToolCallRequest) -> float:
        """
        Get current context usage ratio from state.

        Returns a value between 0.0 and 1.0 representing how much of the
        context window is currently used.
        """
        try:
            # Try to get state from request
            state = getattr(request, "state", None)
            if state is None:
                return 0.0

            messages = state.get("messages", [])
            if not messages:
                return 0.0

            # Estimate token count (4 chars per token)
            total_chars = sum(len(str(getattr(msg, "content", ""))) for msg in messages)
            estimated_tokens = total_chars // 4

            return min(estimated_tokens / self.context_window, 1.0)
        except Exception:
            return 0.0

    def _should_compact(
        self,
        result: ToolMessage,
        tool_name: str,
        context_usage: float,
    ) -> tuple[bool, str]:
        """
        Determine if the tool output should be compacted.

        Returns:
            (should_compact, reason) tuple
        """
        # Skip excluded tools entirely
        if tool_name in self.excluded_tools:
            return False, ""

        content = result.content if hasattr(result, "content") else str(result)
        content_str = str(content)
        content_size = len(content_str)

        # Skip very small outputs
        if content_size < MIN_COMPACTION_SIZE:
            return False, ""

        # 1. Always persist certain tools
        if tool_name in self.always_persist_tools:
            return True, "always_persist_tool"

        # 2. Per-tool trigger: single output > max_output_chars → always compact
        if content_size > self.max_output_chars:
            return True, f"large_output ({content_size} chars)"

        # 3. Thread-level trigger: context at threshold → compact anything above MIN_COMPACTION_SIZE
        if context_usage >= self.compaction_threshold:
            return True, f"context_threshold ({context_usage:.1%} used)"

        return False, ""

    async def _compact_to_vfs(
        self,
        result: ToolMessage,
        request: ToolCallRequest,
        reason: str,
    ) -> ToolMessage:
        """Store the tool output in VFS and return a compacted reference."""
        content = result.content if hasattr(result, "content") else str(result)
        content_str = str(content)

        tool_call = request.tool_call
        tool_name = (
            tool_call.get("name", "unknown")
            if isinstance(tool_call, dict)
            else tool_call.name
        )
        tool_call_id = (
            tool_call.get("id", "") if isinstance(tool_call, dict) else tool_call.id
        )

        # Extract user context from runtime
        runtime = request.runtime
        config = getattr(runtime, "config", {}) or {}
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id", "unknown")
        conversation_id = configurable.get("thread_id", "unknown")

        # Generate storage path
        content_hash = hashlib.md5(
            content_str.encode(), usedforsecurity=False
        ).hexdigest()[:8]  # noqa: S324
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_path = get_session_path(user_id, conversation_id)
        vfs_path = (
            f"{session_path}/tool_outputs/{tool_name}_{timestamp}_{content_hash}.json"
        )

        # Store in VFS
        vfs = await self._get_vfs()

        output_data: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "args": tool_call.get("args", {})
            if isinstance(tool_call, dict)
            else tool_call.args,
            "content": content,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "compaction_reason": reason,
        }

        await vfs.write(
            path=vfs_path,
            content=json.dumps(output_data, indent=2, default=str),
            user_id=user_id,
            metadata={
                "type": "tool_output",
                "tool_name": tool_name,
                "conversation_id": conversation_id,
                "compacted": True,
                "reason": reason,
            },
        )

        # Create compacted content with size info and spawn_subagent hint
        summary = self._create_summary(content_str, tool_name)
        size_kb = len(content_str) / 1024
        compacted_content = (
            f"{summary}\n\n"
            f"[Full output ({size_kb:.1f} KB / {len(content_str)} chars) stored at: {vfs_path}]\n"
            f"[Use spawn_subagent to read and process this file to keep your context clean]"
        )

        logger.info(
            f"Compacted {tool_name} output ({len(content_str)} chars) to {vfs_path} ({reason})"
        )

        # Return new ToolMessage with compacted content
        return ToolMessage(
            content=compacted_content,
            tool_call_id=tool_call_id,
            name=tool_name,
            additional_kwargs={
                **getattr(result, "additional_kwargs", {}),
                "vfs_path": vfs_path,
                "original_length": len(content_str),
                "compacted": True,
                "compaction_reason": reason,
            },
        )

    def _create_summary(self, content: str, tool_name: str) -> str:
        """Create a summary of the tool output."""
        # Try to parse as JSON and summarize
        try:
            data = json.loads(content)
            if isinstance(data, list):
                # Show first few items for context
                preview = data[:3] if len(data) > 3 else data
                return f"[{tool_name}] Returned {len(data)} items. Preview: {json.dumps(preview, default=str)[:200]}..."
            elif isinstance(data, dict):
                keys = list(data.keys())[:5]
                return f"[{tool_name}] Returned object with keys: {keys}..."
        except (json.JSONDecodeError, TypeError):
            pass

        # Fallback: truncate
        max_preview = 500
        if len(content) > max_preview:
            return f"[{tool_name}] {content[:max_preview]}..."

        return f"[{tool_name}] {content}"
