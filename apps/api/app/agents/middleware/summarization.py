"""Workspace-archiving summarization middleware.

Summarizes only the conversation (never GAIA's prompt slots), and archives the
full message history to the persistent workspace first. The agent can recover
any detail by reading /workspace/sessions/{conv}/archives/... with the read tool.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any, cast

from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.summarization import ContextSize, TriggerClause
from langchain.agents.middleware.types import AgentState
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
    get_buffer_string,
)
from langgraph.config import get_config
from langgraph.runtime import Runtime

from app.agents.context.slots import (
    SUMMARY_SOURCE,
    PromptSlot,
    is_conversation_summary,
    slot_of,
)
from app.agents.llm.client import SILENT_LLM_CONFIG
from app.agents.middleware.completion import running_turn_start
from app.constants.log_tags import LogTag
from app.models.agent_models import agent_configurable
from app.services.storage import JuiceFSUnavailable, write_session_file
from app.utils.multimodal import extract_text_content
from shared.py.wide_events import log

# The {messages} placeholder is filled with the summarized turns (XML). The work
# still in progress is NOT in them: it stays in context verbatim after the
# summary, so this prompt asks for a record of the past and nothing else.
CONVERSATION_SUMMARY_PROMPT = """You are condensing the OLDER part of a conversation between a user and GAIA, their personal assistant, so it fits in memory.

The messages below are history. The most recent turns, including whatever is being worked on right now, are NOT included here: they stay in the conversation word for word, right after your summary. Do not summarize, restate or continue that current work.

Write a factual record of what already happened in these messages:
- What the user told GAIA about themselves, their plans and preferences: names, people, dates, places, numbers, decisions.
- What GAIA did: actions taken, tools used and their results, anything created or changed, with exact ids, titles, links and file paths.
- Requests that were finished, and anything explicitly left unresolved, stated as a fact ("not done yet: ..."), never as an instruction.

Rules:
- Past tense, plain statements. No goals, plans, next steps, advice or instructions to anyone.
- Never treat an old request as the current task. If the newest messages here still show something in progress, record only what was asked and what was done so far.
- Leave out GAIA's own operating rules, formatting conventions and persona. Only what happened in the conversation.
- Keep specifics exact. Drop small talk and repetition.
- Write it the way a sharp person takes notes: short, direct sentences or a flat list, plain words, no headings, no filler.

Reply with the summary only.

<messages>
{messages}
</messages>"""


class WorkspaceArchivingSummarizationMiddleware(SummarizationMiddleware):
    """Archives conversation history to the user's workspace before summarizing.

    Drop-in replacement for the previous VFS-backed middleware. The archive
    path is injected into the summary message so the agent can fetch detail
    on demand via the read tool.
    """

    def __init__(
        self,
        model: BaseChatModel,
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
        # The summary call runs inside the graph, so without the silent flag
        # LangGraph's messages stream hands its tokens to the chat as the reply.
        # The binding forwards .profile/._llm_type/._get_ls_params to the model.
        silent_model = cast("BaseChatModel", model.with_config(SILENT_LLM_CONFIG))
        kwargs.setdefault("summary_prompt", CONVERSATION_SUMMARY_PROMPT)
        super().__init__(model=silent_model, trigger=trigger, keep=keep, **kwargs)
        self.enable_archive = enable_archive
        self.excluded_tools = excluded_tools or set()

    async def abefore_model(
        self, state: AgentState[Any], runtime: Runtime[Any]
    ) -> dict[str, Any] | None:
        """Fold the oldest conversation into one summary, leaving every prompt slot intact.

        Prompt slots are rebuilt each turn and must reach the model verbatim. The
        update is an in-place delta (summary takes the first summarized id, the rest
        are removed) so the checkpoint keeps it ahead of the preserved tail.
        """
        del runtime  # framework contract; the archive reads config via get_config()
        if not self._should_trigger_summarization(state):
            return None

        conversation = [m for m in state["messages"] if slot_of(m) is PromptSlot.CONVERSATION]
        cutoff_index = self._determine_cutoff_index(conversation)
        if cutoff_index <= 0:
            return None
        summarized = _removable(_foldable(conversation, cutoff_index))
        if not summarized:
            return None

        summary_text = await self._asummarize(summarized)
        if summary_text is None:
            return None
        archive_path = await self._archive_or_none(state) if self.enable_archive else None
        summary_message = self._build_new_messages(summary_text)[0]
        summary_message.id = summarized[0].id
        result: dict[str, Any] = {
            "messages": [
                summary_message,
                *(RemoveMessage(id=cast("str", m.id)) for m in summarized[1:]),
            ]
        }
        if archive_path:
            self._inject_archive_path(result, archive_path)
        return result

    async def _asummarize(self, messages: list[AnyMessage]) -> str | None:
        """Return the summary of the whole prefix, or None when history must stay.

        Never trimmed: LangChain's 4000-token trim dropped the previous summary
        and emptied behind one large tool result. Its _acreate_summary also turns
        a failure into "Error generating summary" text that would replace the prefix.
        """
        prompt = self.summary_prompt.format(messages=get_buffer_string(messages, format="xml"))
        try:
            response = await self.model.ainvoke(
                prompt, config={"metadata": {"lc_source": SUMMARY_SOURCE}}
            )
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Summary generation failed",
                error_type=type(e).__name__,
                message_count=len(messages),
            )
            return None
        text = response.text.strip()
        if not text:
            log.error(f"{LogTag.AGENT} Summary generation failed", error_type="EmptySummary")
            return None
        return text

    async def _archive_or_none(self, state: AgentState[Any]) -> str | None:
        """Archive the full history; a failed archive is reported and never blocks the summary."""
        try:
            return await self._archive(state)
        except JuiceFSUnavailable as e:
            log.warning(
                f"{LogTag.AGENT} Archive skipped (workspace unavailable)",
                error_type=type(e).__name__,
            )
        except Exception as e:
            log.error(f"{LogTag.AGENT} Archive failed", error_type=type(e).__name__)
        return None

    def _should_trigger_summarization(self, state: AgentState[Any]) -> bool:
        """Return whether the context is large enough to summarize.

        Measured over the whole request (prompt slots included), since that is
        what fills the window; delegates to the parent's _should_summarize so
        the thresholds are never re-derived here.
        """
        filtered = [
            m
            for m in state.get("messages", [])
            if not (isinstance(m, ToolMessage) and getattr(m, "name", None) in self.excluded_tools)
        ]
        return self._should_summarize(filtered, self.token_counter(filtered))

    async def _archive(self, state: AgentState[Any]) -> str:
        messages = state.get("messages", [])
        # `runtime` carries no config (LangGraph's `Runtime` deliberately omits
        # it) — reading it from there once raised "requires 'user_id'" silently.
        # `get_config()` is the supported accessor, as LLMAccountingMiddleware uses.
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
        """Annotate the summary HumanMessage in result with the archive path.

        Mutates result's messages in place.
        """
        messages = result.get("messages", [])
        for msg in messages:
            if isinstance(msg, HumanMessage):
                additional_kwargs = getattr(msg, "additional_kwargs", {})
                if is_conversation_summary(msg):
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        msg.content += (
                            f"\n\n[Full history archived at: {archive_path}. "
                            f"Use the `read` tool to recover detail.]"
                        )
                    additional_kwargs["archive_path"] = archive_path
                    break


def _foldable(conversation: list[AnyMessage], cutoff: int) -> list[AnyMessage]:
    """Return what to fold: history before the running turn, else that turn's finished steps.

    The running turn's request is never folded. Only when nothing but an old
    summary precedes it (a long executor run) are its completed tool steps
    folded, so the run stays bounded; cutoff is already a safe tool-pair boundary.
    """
    start = running_turn_start(conversation)
    if start is None:
        return conversation[:cutoff]
    before = conversation[: min(start, cutoff)]
    if any(not is_conversation_summary(m) for m in before):
        return before
    steps = conversation[start + 1 : cutoff]
    # Nothing new to fold: re-summarizing the old summary alone frees no context.
    if not steps:
        return []
    return [*before, *steps]


def _removable(prefix: list[AnyMessage]) -> list[AnyMessage]:
    """Return the prefix messages a RemoveMessage can target, keeping tool pairs whole.

    Threads written before out-of-band writes carried ids hold id-less messages;
    those stay verbatim, and so does any AI message whose tool call one answers,
    or the provider would get a tool result with no call.
    """
    pinned_calls = {m.tool_call_id for m in prefix if isinstance(m, ToolMessage) and m.id is None}
    return [
        m
        for m in prefix
        if m.id is not None
        and not (isinstance(m, AIMessage) and {tc["id"] for tc in m.tool_calls} & pinned_calls)
    ]
