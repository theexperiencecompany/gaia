"""Workspace compaction middleware.

Replaces large tool outputs with a `/workspace/sessions/{conv}/tool_outputs/`
reference that the agent reads on demand with the `read` tool. Keeps message
history small while making the full output recoverable.

Two independent triggers (unchanged from the prior VFS-backed version):
- Per-tool: a single output exceeds `max_output_chars` → compact immediately
- Thread-level: estimated context usage exceeds `compaction_threshold` →
  compact any output bigger than `MIN_COMPACTION_SIZE`

The decide-and-spill logic lives in the module-level `compact_tool_output`
helper so the spawned-subagent loop (which runs outside the middleware stack)
compacts its tool outputs the exact same way. The middleware is a thin wrapper
around it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.constants.llm import DEFAULT_MAX_TOKENS
from app.constants.log_tags import LogTag
from app.constants.summarization import MIN_COMPACTION_SIZE
from app.services.storage import JuiceFSUnavailable, write_session_file
from shared.py.wide_events import log


def estimate_context_usage(messages: Sequence[Any], context_window: int) -> float:
    """Estimate the fraction of the context window consumed by ``messages``.

    Uses the same 4-chars-per-token heuristic as the rest of the agent stack.
    """
    if not messages:
        return 0.0
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    estimated_tokens = total_chars // 4
    return min(estimated_tokens / context_window, 1.0)


def should_compact_output(
    content_str: str,
    tool_name: str,
    context_usage: float,
    *,
    max_output_chars: int,
    compaction_threshold: float,
    always_persist: bool,
    excluded: bool,
) -> tuple[bool, str]:
    """Decide whether a tool output should be spilled to the workspace.

    Returns ``(should_compact, reason)``. ``reason`` is empty when not compacting.
    """
    if excluded:
        return False, ""
    size = len(content_str)
    if always_persist:
        return True, "always_persist_tool"
    if size < MIN_COMPACTION_SIZE:
        return False, ""
    if size > max_output_chars:
        return True, f"large_output ({size} chars)"
    if context_usage >= compaction_threshold:
        return True, f"context_threshold ({context_usage:.1%} used)"
    return False, ""


def _summarize_output(content: str, tool_name: str) -> str:
    try:
        data = json.loads(content)
        if isinstance(data, list):
            preview = data[:3] if len(data) > 3 else data
            return (
                f"[{tool_name}] Returned {len(data)} items. "
                f"Preview: {json.dumps(preview, default=str)[:200]}..."
            )
        if isinstance(data, dict):
            keys = list(data.keys())[:5]
            return f"[{tool_name}] Returned object with keys: {keys}..."
    except (json.JSONDecodeError, TypeError):
        pass
    if len(content) > 500:
        return f"[{tool_name}] {content[:500]}..."
    return f"[{tool_name}] {content}"


async def _spill_to_workspace(
    *,
    content: Any,
    content_str: str,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
    user_id: str,
    conversation_id: str,
    reason: str,
    existing_additional_kwargs: dict[str, Any],
) -> ToolMessage:
    """Write the full output to the workspace and return a compacted ToolMessage."""
    content_hash = hashlib.md5(content_str.encode(), usedforsecurity=False).hexdigest()[:8]  # nosec B324
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    relative_path = f"tool_outputs/{tool_name}_{timestamp}_{content_hash}.json"

    output_data: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "args": tool_args,
        "content": content,
        "stored_at": datetime.now(UTC).isoformat(),
        "compaction_reason": reason,
    }
    _, sandbox_path = await write_session_file(
        user_id=user_id,
        conversation_id=conversation_id,
        relative_path=relative_path,
        content=json.dumps(output_data, indent=2, default=str),
    )

    summary = _summarize_output(content_str, tool_name)
    size_kb = len(content_str) / 1024
    body = (
        f"{summary}\n\n"
        f"[Full output ({size_kb:.1f} KB / {len(content_str)} chars) "
        f"stored at: {sandbox_path}]\n"
        f"[Use the `read` tool to load it, or `bash` to grep/process it]"
    )

    log.info(
        f"{LogTag.AGENT} Compacted {tool_name} output ({len(content_str)} chars) to {sandbox_path} ({reason})"
    )
    return ToolMessage(
        content=body,
        tool_call_id=tool_call_id,
        name=tool_name,
        additional_kwargs={
            **existing_additional_kwargs,
            "workspace_path": sandbox_path,
            "original_length": len(content_str),
            "compacted": True,
            "compaction_reason": reason,
        },
    )


async def compact_tool_output(
    *,
    content: Any,
    tool_name: str,
    tool_call_id: str,
    tool_args: dict[str, Any],
    user_id: str | None,
    conversation_id: str | None,
    context_usage: float,
    max_output_chars: int,
    compaction_threshold: float,
    always_persist: bool = False,
    excluded: bool = False,
    existing_additional_kwargs: dict[str, Any] | None = None,
) -> ToolMessage | None:
    """Decide-and-spill a tool output. The one canonical compaction path.

    Returns a compacted ``ToolMessage`` when the output was spilled to the
    workspace, or ``None`` when it should be kept as-is — below threshold,
    excluded, or the workspace was unavailable (degrades gracefully, matching
    the middleware's prior behavior).
    """
    content_str = str(content)
    should, reason = should_compact_output(
        content_str,
        tool_name,
        context_usage,
        max_output_chars=max_output_chars,
        compaction_threshold=compaction_threshold,
        always_persist=always_persist,
        excluded=excluded,
    )
    if not should:
        return None

    try:
        if not user_id:
            raise ValueError("compaction requires 'user_id' in configurable")
        if not conversation_id:
            raise ValueError("compaction requires 'vfs_session_id' or 'thread_id' in configurable")
        return await _spill_to_workspace(
            content=content,
            content_str=content_str,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            user_id=user_id,
            conversation_id=conversation_id,
            reason=reason,
            existing_additional_kwargs=existing_additional_kwargs or {},
        )
    except JuiceFSUnavailable as e:
        log.warning(f"{LogTag.AGENT} Compaction skipped (workspace unavailable): {e}")
        return None
    except Exception as e:
        log.error(f"{LogTag.AGENT} Compaction failed for {tool_name}: {e}")
        return None


class WorkspaceCompactionMiddleware(AgentMiddleware):
    """Compacts large tool outputs to the user's persistent workspace.

    Usage::

        middleware = WorkspaceCompactionMiddleware(
            max_output_chars=20000,
            compaction_threshold=0.65,
        )
    """

    def __init__(
        self,
        compaction_threshold: float = 0.65,
        max_output_chars: int = 20000,
        always_persist_tools: list[str] | None = None,
        context_window: int = DEFAULT_MAX_TOKENS,
        excluded_tools: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.compaction_threshold = compaction_threshold
        self.max_output_chars = max_output_chars
        self.always_persist_tools = always_persist_tools or []
        self.context_window = context_window
        self.excluded_tools = excluded_tools or set()

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result

        tool_call = request.tool_call
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name", "")
            tool_call_id = tool_call.get("id", "")
            tool_args = tool_call.get("args", {})
        else:
            tool_name = tool_call.name
            tool_call_id = tool_call.id
            tool_args = tool_call.args

        config = getattr(request.runtime, "config", {}) or {}
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")

        compacted = await compact_tool_output(
            content=result.content if hasattr(result, "content") else str(result),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_args=tool_args,
            user_id=configurable.get("user_id"),
            conversation_id=configurable.get("vfs_session_id") or thread_id,
            context_usage=self._get_context_usage(request),
            max_output_chars=self.max_output_chars,
            compaction_threshold=self.compaction_threshold,
            always_persist=tool_name in self.always_persist_tools,
            excluded=tool_name in self.excluded_tools,
            existing_additional_kwargs=getattr(result, "additional_kwargs", {}),
        )
        return compacted if compacted is not None else result

    def _get_context_usage(self, request: ToolCallRequest) -> float:
        try:
            state = getattr(request, "state", None)
            if state is None:
                return 0.0
            return estimate_context_usage(state.get("messages", []), self.context_window)
        except Exception:
            return 0.0
