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
from langchain.agents.middleware.summarization import ContextSize, TriggerClause
from langchain.agents.middleware.types import AgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.services.storage import JuiceFSUnavailable, write_session_file
from app.utils.multimodal import extract_text_content
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
        trigger: ContextSize | TriggerClause | list[ContextSize | TriggerClause] | None = (
            "fraction",
            0.85,
        ),
        keep: ContextSize = ("messages", 15),
        enable_archive: bool = True,
        excluded_tools: set[str] | None = None,
        **kwargs: Any,  # noqa: ANN401 -- framework contract
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
                archive_path = await self._archive(state)
            except JuiceFSUnavailable as e:
                log.warning(
                    f"{LogTag.AGENT} Archive skipped (workspace unavailable)",
                    error_type=type(e).__name__,
                )
            except Exception as e:
                log.error(f"{LogTag.AGENT} Archive failed", error_type=type(e).__name__)

        result = await super().abefore_model(state, runtime)
        if result is not None and archive_path:
            self._inject_archive_path(result, archive_path)
        return result

    def _should_trigger_summarization(self, state: AgentState[Any]) -> bool:
        """Whether the archive should be written before ``super().abefore_model`` runs.

        Delegates the threshold decision to the parent's ``_should_summarize`` so
        the archive gate fires in exact lockstep with summarization. Re-deriving
        the thresholds here drifted from the parent in four ways (strict ``>``
        instead of ``>=`` at the boundary, and no support for list, mapping, or
        provider-reported-token triggers), each of which summarized history away
        with no archive to recover it from.
        """
        filtered = [
            m
            for m in state.get("messages", [])
            if not (isinstance(m, ToolMessage) and getattr(m, "name", None) in self.excluded_tools)
        ]
        return self._should_summarize(filtered, self.token_counter(filtered))

    async def _archive(self, state: AgentState[Any]) -> str:
        messages = state.get("messages", [])
        # The `runtime` handed to a middleware hook carries no config — LangGraph's
        # `Runtime` deliberately omits it (see its class docstring). Reading it from
        # there yielded an empty configurable on every real run, so the archive
        # raised "requires 'user_id'" and was swallowed by the caller's handler:
        # no history was ever archived. `get_config()` is the supported accessor,
        # and is what LLMAccountingMiddleware already uses for the same reason.
        configurable = agent_configurable(get_config())
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
        log.info(
            f"{LogTag.AGENT} Archived messages before summarization",
            message_count=len(messages),
            sandbox_path=sandbox_path,
        )
        return sandbox_path

    def _serialize_messages(self, messages: list[AnyMessage]) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for msg in messages:
            # Text-extract so inline media never lands base64 in the archive —
            # the archive is a text record of the conversation, and a single
            # image block would add ~1.4 MB of base64 to the JSON.
            entry: dict[str, Any] = {
                "type": type(msg).__name__,
                "content": extract_text_content(msg.content)
                if hasattr(msg, "content")
                else str(msg),
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
                if additional_kwargs.get("lc_source") == "summarization":
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        msg.content += (
                            f"\n\n[Full history archived at: {archive_path}. "
                            f"Use the `read` tool to recover detail.]"
                        )
                    additional_kwargs["archive_path"] = archive_path
                    break
