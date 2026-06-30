"""Workspace compaction middleware.

Replaces large tool outputs with a `/workspace/sessions/{conv}/tool_outputs/`
reference that the agent reads on demand with the `read` tool. Keeps message
history small while making the full output recoverable.

Two independent triggers (unchanged from the prior VFS-backed version):
- Per-tool: a single output exceeds `max_output_chars` → compact immediately
- Thread-level: estimated context usage exceeds `compaction_threshold` →
  compact any output bigger than `MIN_COMPACTION_SIZE`
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from app.agents.workspace.offload import (
    OffloadInfo,
    mark_offload,
    read_offload,
    tools_for_offload,
)
from app.constants.log_tags import LogTag
from app.constants.summarization import MIN_COMPACTION_SIZE
from app.services.storage import JuiceFSUnavailable, write_session_file
from shared.py.wide_events import log


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
        context_window: int = 128000,
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
        tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else tool_call.name
        context_usage = self._get_context_usage(request)
        should_compact, reason = self._should_compact(result, tool_name, context_usage)
        if should_compact:
            try:
                result = await self._persist(result, request, reason)
            except JuiceFSUnavailable as e:
                log.warning(f"{LogTag.AGENT} Compaction skipped (workspace unavailable): {e}")
            except Exception as e:
                log.error(f"{LogTag.AGENT} Compaction failed for {tool_name}: {e}")

        # Whether we just offloaded the output or the tool self-offloaded (gmail),
        # surface the file-mining tools the moment a marker is present. Keyed on
        # the offload itself, so it covers every producer uniformly.
        return self._bind_offload_tools(result, request)

    def _bind_offload_tools(
        self, result: ToolMessage, request: ToolCallRequest
    ) -> ToolMessage | Command[Any]:
        """Append jq/grep to ``selected_tool_ids`` if ``result`` carries an offload marker.

        Binds only the mining tools not already selected — selected_tool_ids is an
        append-only reducer, so this avoids re-binding the same tool every offload
        and never touches/overrides any other tool.
        """
        info = read_offload(result)
        if info is None:
            return result
        state = getattr(request, "state", None) or {}
        already = set(state.get("selected_tool_ids", []) or [])
        to_bind = [name for name in tools_for_offload(info) if name not in already]
        if not to_bind:
            return result
        return Command(update={"messages": [result], "selected_tool_ids": to_bind})

    def _get_context_usage(self, request: ToolCallRequest) -> float:
        try:
            state = getattr(request, "state", None)
            if state is None:
                return 0.0
            messages = state.get("messages", [])
            if not messages:
                return 0.0
            total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
            estimated_tokens = total_chars // 4
            return min(estimated_tokens / self.context_window, 1.0)
        except Exception:
            return 0.0

    def _should_compact(
        self, result: ToolMessage, tool_name: str, context_usage: float
    ) -> tuple[bool, str]:
        if tool_name in self.excluded_tools:
            return False, ""
        content_str = str(result.content if hasattr(result, "content") else result)
        size = len(content_str)
        if tool_name in self.always_persist_tools:
            return True, "always_persist_tool"
        if size < MIN_COMPACTION_SIZE:
            return False, ""
        if size > self.max_output_chars:
            return True, f"large_output ({size} chars)"
        if context_usage >= self.compaction_threshold:
            return True, f"context_threshold ({context_usage:.1%} used)"
        return False, ""

    async def _persist(
        self, result: ToolMessage, request: ToolCallRequest, reason: str
    ) -> ToolMessage:
        content = result.content if hasattr(result, "content") else str(result)
        content_str = str(content)

        tool_call = request.tool_call
        tool_name = (
            tool_call.get("name", "unknown") if isinstance(tool_call, dict) else tool_call.name
        )
        tool_call_id = tool_call.get("id", "") if isinstance(tool_call, dict) else tool_call.id

        runtime = request.runtime
        config = getattr(runtime, "config", {}) or {}
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")
        thread_id = configurable.get("thread_id")
        conversation_id = configurable.get("vfs_session_id") or thread_id
        if not user_id:
            raise ValueError("compaction requires 'user_id' in configurable")
        if not conversation_id:
            raise ValueError("compaction requires 'vfs_session_id' or 'thread_id' in configurable")

        content_hash = hashlib.md5(content_str.encode(), usedforsecurity=False).hexdigest()[:8]  # nosec B324
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        relative_path = f"tool_outputs/{tool_name}_{timestamp}_{content_hash}.json"

        output_data: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "args": (tool_call.get("args", {}) if isinstance(tool_call, dict) else tool_call.args),
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

        summary = self._summary(content_str, tool_name)
        size_kb = len(content_str) / 1024
        body = (
            f"{summary}\n\n"
            f"[Full output ({size_kb:.1f} KB / {len(content_str)} chars) "
            f"stored at: {sandbox_path}]\n"
            f"[Do NOT `read` the whole file back into context, that undoes the offload. "
            f"To pull just what you need, prefer the `jq`/`grep` tools; `bash` and "
            f"spawn_subagent also work for {sandbox_path}.]"
        )

        offload: OffloadInfo = {
            "path": sandbox_path,
            "bytes": len(content_str.encode("utf-8")),
            "fmt": "json",
            "producer": tool_name,
            "records": None,
        }

        log.info(
            f"{LogTag.AGENT} Compacted {tool_name} output ({len(content_str)} chars) to {sandbox_path} ({reason})"
        )
        return ToolMessage(
            content=body,
            tool_call_id=tool_call_id,
            name=tool_name,
            additional_kwargs=mark_offload(
                {
                    **getattr(result, "additional_kwargs", {}),
                    "workspace_path": sandbox_path,
                    "original_length": len(content_str),
                    "compacted": True,
                    "compaction_reason": reason,
                },
                offload,
            ),
        )

    def _summary(self, content: str, tool_name: str) -> str:
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
