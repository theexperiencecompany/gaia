"""Workspace-archiving summarization middleware.

Wraps LangChain's `SummarizationMiddleware` so we archive the full message
history to the persistent workspace before summarization happens. The agent
can recover any detail by reading `/workspace/sessions/{conv}/archives/...`
with the `read` tool.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.types import AgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from app.services.storage import JuiceFSUnavailable, write_session_file
from shared.py.wide_events import log


class WorkspaceArchivingSummarizationMiddleware(SummarizationMiddleware):
    """Archives conversation history to the user's workspace before summarizing.

    Drop-in replacement for the previous VFS-backed middleware. The archive
    path is injected into the summary message so the agent can fetch detail
    on demand via the `read` tool.
    """

    def __init__(
        self,
        model: str | BaseChatModel,
        *,
        trigger=("fraction", 0.85),
        keep=("messages", 15),
        enable_archive: bool = True,
        excluded_tools: set[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(model=model, trigger=trigger, keep=keep, **kwargs)
        self.enable_archive = enable_archive
        self.excluded_tools = excluded_tools or set()

    async def abefore_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        archive_path: str | None = None
        if self.enable_archive and self._should_trigger_summarization(state):
            try:
                archive_path = await self._archive(state, runtime)
            except JuiceFSUnavailable as e:
                log.warning(f"Archive skipped (workspace unavailable): {e}")
            except Exception as e:
                log.error(f"Archive failed: {e}")

        result = await super().abefore_model(state, runtime)
        if result is not None and archive_path:
            self._inject_archive_path(result, archive_path)
        return result

    def _should_trigger_summarization(self, state: AgentState[Any]) -> bool:
        messages = state.get("messages", [])
        if not messages:
            return False
        filtered = [
            m
            for m in messages
            if not (isinstance(m, ToolMessage) and getattr(m, "name", None) in self.excluded_tools)
        ]
        if not filtered:
            return False
        try:
            token_count = self.token_counter(filtered)
            if isinstance(self.trigger, tuple):
                trigger_type, trigger_value = self.trigger
                if trigger_type == "fraction":
                    max_tokens = getattr(self, "_max_tokens", 128000)
                    return token_count > max_tokens * trigger_value
                if trigger_type == "tokens":
                    return token_count > trigger_value
                if trigger_type == "messages":
                    return len(filtered) > trigger_value
        except Exception:
            return False
        return False

    async def _archive(self, state: AgentState[Any], runtime: Runtime[Any]) -> str:
        messages = state.get("messages", [])
        config: dict[str, Any] = getattr(runtime, "config", {}) or {}
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")
        thread_id = configurable.get("thread_id")
        conversation_id = configurable.get("vfs_session_id") or thread_id
        if not user_id:
            raise ValueError("archive requires 'user_id' in configurable")
        if not conversation_id:
            raise ValueError("archive requires 'vfs_session_id' or 'thread_id' in configurable")

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        relative_path = f"archives/pre_summary_{timestamp}.json"
        history = self._serialize_messages(messages)

        _, sandbox_path = await write_session_file(
            user_id=user_id,
            conversation_id=conversation_id,
            relative_path=relative_path,
            content=json.dumps(history, indent=2, default=str),
        )
        log.info(f"Archived {len(messages)} messages to {sandbox_path} before summarization")
        return sandbox_path

    def _serialize_messages(self, messages: list[AnyMessage]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for msg in messages:
            entry: dict[str, Any] = {
                "type": type(msg).__name__,
                "content": msg.content if hasattr(msg, "content") else str(msg),
            }
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.get("id"), "name": tc.get("name"), "args": tc.get("args")}
                    for tc in tool_calls
                ]
            if isinstance(msg, ToolMessage):
                entry["tool_call_id"] = msg.tool_call_id
                entry["name"] = getattr(msg, "name", None)
            history.append(entry)
        return history

    def _inject_archive_path(self, result: dict[str, Any], archive_path: str) -> None:
        """Annotate the summary HumanMessage in ``result`` with the archive path.

        Mutates ``result``'s messages in place.
        """
        messages = result.get("messages", [])
        for msg in messages:
            if isinstance(msg, HumanMessage):
                additional_kwargs = getattr(msg, "additional_kwargs", {})
                if additional_kwargs.get("is_summary"):
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        msg.content += (
                            f"\n\n[Full history archived at: {archive_path}. "
                            f"Use the `read` tool to recover detail.]"
                        )
                    additional_kwargs["archive_path"] = archive_path
                    break
