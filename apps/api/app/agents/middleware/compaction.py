"""Tool-output compaction middleware.

Bounds how much a single tool observation can contribute to the context. Once
the decision to compact is made, the output goes through two independent
best-effort steps whose outcomes compose:

1. Workspace spill (optional, lossless). When the workspace exists the RAW
   output is written to `/workspace/sessions/{conv}/tool_outputs/`; the compacted
   message then carries a pointer the model can still mine with
   `query_json`/`grep`. A JuiceFS-less deployment (every native, non-Docker run —
   see the JuiceFS trade-off in `apps/api/CLAUDE.md`) skips this and compacts on
   alone; the spill is an add-on, never a requirement (issue #916).
2. Summary payload. With a ``summary_llm`` available the output is digested by
   one bounded model call into a dense factual digest placed directly in
   context — counts, IDs, errors verbatim, totals, representative samples — so
   the agent rarely needs to re-mine the spilled file at all. The call is
   single-attempt, timeout-bounded, and fires only for outputs already judged
   oversized; any failure degrades cleanly. Without a summarizer the payload is
   the deterministic heuristic preview (`_summarize_output`) or, when there was
   nowhere to spill either, a head+tail truncation whose marker says plainly
   that the middle is gone and cannot be recovered.

The truncation fallback exists because returning the output unchanged is not a
safe degradation: it silently removes the only bound on context growth, which is
how a native run reached 131k median input tokens per case and hit the step
limit.

Two independent triggers (unchanged from the prior VFS-backed version):
- Per-tool: a single output exceeds `max_output_chars` → compact immediately
- Thread-level: estimated context usage exceeds `compaction_threshold` →
  compact any output bigger than `MIN_COMPACTION_SIZE`

The decide-and-compact logic lives in the module-level `compact_tool_output`
helper and the middleware is a thin wrapper around it, so the tiering is
testable without a middleware stack. Subagents reach it through that same
middleware (`create_subagent_middleware` passes `enable_compaction=True`);
comms deliberately does not compact, having no tools to mine a spilled file.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from app.agents.workspace.offload import (
    OffloadInfo,
    mark_offload,
    read_offload,
    sniff_offload_fmt,
    tools_for_offload,
)
from app.constants.llm import DEFAULT_MAX_TOKENS
from app.constants.log_tags import LogTag
from app.constants.summarization import (
    COMPACTION_FALLBACK_HEAD_CHARS,
    COMPACTION_FALLBACK_TAIL_CHARS,
    COMPACTION_SUMMARY_INPUT_HEAD_CHARS,
    COMPACTION_SUMMARY_INPUT_TAIL_CHARS,
    COMPACTION_SUMMARY_MAX_CHARS,
    COMPACTION_SUMMARY_TIMEOUT_SECONDS,
    MIN_COMPACTION_SIZE,
)
from app.models.agent_models import runtime_configurable
from app.services.storage import JuiceFSUnavailable, write_session_file
from app.utils.multimodal import (
    MessageContent,
    approx_content_chars,
    extract_text_content,
    has_media_blocks,
)
from shared.py.wide_events import log

# The file-format discriminator carried by every offload marker.
OffloadFmt = Literal["json", "jsonl", "text"]

COMPACTION_TRUNCATED_MARKER = "[Compacted in context]"


def estimate_context_usage(messages: Sequence[AnyMessage], context_window: int) -> float:
    """Estimate the fraction of the context window consumed by ``messages``.

    Uses the same 4-chars-per-token heuristic as the rest of the agent stack.
    """
    if not messages:
        return 0.0
    total_chars = sum(approx_content_chars(getattr(m, "content", "")) for m in messages)
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

    ``tool_name`` is intentionally unused here — callers already resolve it into
    ``always_persist``/``excluded`` before calling in; kept as a parameter for
    call-site readability (and mirrored by the test suite).

    Returns ``(should_compact, reason)``. ``reason`` is empty when not compacting.
    """
    del tool_name
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


_COMPACTION_SUMMARIZER_SYSTEM_PROMPT = """You compress tool outputs for an AI agent's context. Write a dense, factual digest of the tool output below.

Rules:
- Preserve exactly: record/result counts, IDs, names, dates, statuses, totals, and any errors or warnings (keep errors near-verbatim).
- For long repetitive collections: state the count and item shape, then quote 2-3 representative items.
- Keep anything that directly answers what the tool was apparently asked; drop boilerplate, pagination filler, and repetition.
- Plain text only. No preamble (never start with "Here is" or similar), no commentary about yourself. At most {max_chars} characters."""


def _summary_input_sample(content_str: str) -> str:
    """Head+tail sample of the output sized for the summarizer prompt.

    Mirrors the truncation fallback's rationale: schema/first records live at the
    front, totals/errors at the end, and the middle of a huge listing carries the
    least information per char.
    """
    if (
        len(content_str)
        <= COMPACTION_SUMMARY_INPUT_HEAD_CHARS + COMPACTION_SUMMARY_INPUT_TAIL_CHARS
    ):
        return content_str
    dropped = (
        len(content_str) - COMPACTION_SUMMARY_INPUT_HEAD_CHARS - COMPACTION_SUMMARY_INPUT_TAIL_CHARS
    )
    return (
        f"{content_str[:COMPACTION_SUMMARY_INPUT_HEAD_CHARS]}\n"
        f"[... {dropped} middle chars omitted from this sample ...]\n"
        f"{content_str[-COMPACTION_SUMMARY_INPUT_TAIL_CHARS:]}"
    )


async def _llm_summarize_output(
    summary_llm: LanguageModelLike, content_str: str, tool_name: str
) -> str | None:
    """Digest an oversized tool output into a bounded in-context summary.

    Single attempt under a hard timeout — the compaction path runs inside the
    tool loop, so a slow endpoint must never stall it. Returns ``None`` on any
    failure (or an empty/unusable response); callers degrade to the deterministic
    tiers, and the failure is logged loudly rather than swallowed.
    """
    prompt = f"Tool: {tool_name}\n\nOutput to digest:\n{_summary_input_sample(content_str)}"
    try:
        response = await asyncio.wait_for(
            summary_llm.ainvoke(
                [
                    SystemMessage(
                        content=_COMPACTION_SUMMARIZER_SYSTEM_PROMPT.format(
                            max_chars=COMPACTION_SUMMARY_MAX_CHARS
                        )
                    ),
                    HumanMessage(content=prompt),
                ]
            ),
            timeout=COMPACTION_SUMMARY_TIMEOUT_SECONDS,
        )
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} LLM compaction summary failed; falling back to deterministic tiers",
            tool_name=tool_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        return None
    response_message = getattr(response, "content", "")
    if not isinstance(response_message, (str, list)):
        log.warning(
            f"{LogTag.AGENT} LLM compaction summary returned an unusable payload",
            tool_name=tool_name,
            payload_type=type(response_message).__name__,
        )
        return None
    text = extract_text_content(response_message).strip()
    if not text:
        log.warning(
            f"{LogTag.AGENT} LLM compaction summary was empty; falling back to deterministic tiers",
            tool_name=tool_name,
        )
        return None
    # Hard cap regardless of what the model returned — the whole point of the
    # tier is a bounded payload, and a rambling digest would undo the offload.
    if len(text) > COMPACTION_SUMMARY_MAX_CHARS:
        text = text[:COMPACTION_SUMMARY_MAX_CHARS].rstrip() + "…[digest truncated]"
    return text


async def _write_raw_output(
    *, content_str: str, tool_name: str, user_id: str, conversation_id: str
) -> tuple[OffloadFmt, str]:
    """Write the RAW output to the workspace; return ``(fmt, sandbox_path)``.

    The raw content (not a metadata wrapper) is written so query_json/grep can
    mine it directly. Raises on any storage failure — callers own the fallback.
    """
    fmt = sniff_offload_fmt(content_str)
    ext = {"json": "json", "jsonl": "jsonl", "text": "txt"}[fmt]
    content_hash = hashlib.md5(content_str.encode(), usedforsecurity=False).hexdigest()[:8]  # nosec B324
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    relative_path = f"tool_outputs/{tool_name}_{timestamp}_{content_hash}.{ext}"

    _, sandbox_path = await write_session_file(
        user_id=user_id,
        conversation_id=conversation_id,
        relative_path=relative_path,
        content=content_str,
    )
    return fmt, sandbox_path


def _offload_kwargs(
    *, sandbox_path: str, fmt: OffloadFmt, content_str: str, tool_name: str
) -> OffloadInfo:
    return {
        "path": sandbox_path,
        "bytes": len(content_str.encode("utf-8")),
        "fmt": fmt,
        "producer": tool_name,
        "records": None,
    }


def _stub_spill_message(
    *,
    content_str: str,
    fmt: OffloadFmt,
    sandbox_path: str,
    tool_name: str,
    tool_call_id: str,
    reason: str,
    status: str,
    existing_additional_kwargs: dict[str, Any],
) -> ToolMessage:
    """Build the deterministic-preview spill message for an already-written file.

    The degraded payload shape used when no LLM summarizer produced a digest:
    heuristic preview plus the file pointer. ``_write_raw_output`` wrote the
    file; this only renders the in-context replacement.
    """
    summary = _summarize_output(content_str, tool_name)
    size_kb = len(content_str) / 1024
    mine = (
        "prefer `query_json` (structured records) or `grep` (text)"
        if fmt in ("json", "jsonl")
        else "use `grep` to pull matching lines"
    )
    body = (
        f"{summary}\n\n"
        f"[Full output ({size_kb:.1f} KB / {len(content_str)} chars) "
        f"stored at: {sandbox_path}]\n"
        f"[Do NOT `read` the whole file back into context, that undoes the offload. "
        f"To pull just what you need, {mine}; `bash` and spawn_subagent also work "
        f"for {sandbox_path}.]"
    )

    offload: OffloadInfo = _offload_kwargs(
        sandbox_path=sandbox_path, fmt=fmt, content_str=content_str, tool_name=tool_name
    )

    log.info(
        f"{LogTag.AGENT} Compacted tool output",
        tool_name=tool_name,
        content_chars=len(content_str),
        sandbox_path=sandbox_path,
        reason=reason,
    )
    return ToolMessage(
        content=body,
        tool_call_id=tool_call_id,
        name=tool_name,
        # Preserve the source status so an error result stays an error after
        # compaction — otherwise downstream `status == "error"` checks (loop
        # guard, error handling) would treat the spilled output as a success.
        status=status,
        additional_kwargs=mark_offload(
            {
                **existing_additional_kwargs,
                "workspace_path": sandbox_path,
                "original_length": len(content_str),
                "compacted": True,
                "compaction_reason": reason,
                "compaction_strategy": "workspace_spill",
            },
            offload,
        ),
    )


def _summarized_compact_message(
    *,
    summary: str,
    tool_name: str,
    tool_call_id: str,
    reason: str,
    status: str,
    content_str: str,
    spilled: tuple[OffloadFmt, str] | None,
    existing_additional_kwargs: dict[str, Any],
) -> ToolMessage:
    """Build the LLM-summary compaction message, with an optional spill pointer.

    The digest IS the payload — the agent can reason over it directly instead of
    exploring a file. When the raw output was also spilled, a one-line pointer
    and the offload marker ride along so lossless recovery stays available;
    when it wasn't (no workspace), the summary stands alone.

    ``spilled`` is ``(fmt, sandbox_path)`` from ``_write_raw_output``.
    """
    body = f"[{tool_name} compacted — {reason}] {summary}"
    additional: dict[str, Any] = {
        **existing_additional_kwargs,
        "original_length": len(content_str),
        "compacted": True,
        "compaction_reason": reason,
        "compaction_strategy": "llm_summary",
    }
    if spilled:
        fmt, sandbox_path = spilled
        mine = "query_json/grep" if fmt in ("json", "jsonl") else "grep"
        size_kb = len(content_str) / 1024
        body += (
            f"\n\n[Full raw output ({size_kb:.1f} KB) saved at {sandbox_path} — if the "
            f"digest missed something you need, mine just that with {mine}; do NOT "
            f"read the whole file back into context.]"
        )
        additional["workspace_path"] = sandbox_path
        additional["compaction_strategy"] = "llm_summary_workspace_spill"

    log.info(
        f"{LogTag.AGENT} Compacted tool output into an LLM summary",
        tool_name=tool_name,
        content_chars=len(content_str),
        summary_chars=len(summary),
        workspace_spill=bool(spilled),
        reason=reason,
    )
    return ToolMessage(
        content=body,
        tool_call_id=tool_call_id,
        name=tool_name,
        # Preserve the source status so an error result stays an error after
        # compaction — same contract as the other tiers.
        status=status,
        additional_kwargs=(
            mark_offload(
                additional,
                _offload_kwargs(
                    sandbox_path=spilled[1],
                    fmt=spilled[0],
                    content_str=content_str,
                    tool_name=tool_name,
                ),
            )
            if spilled
            else additional
        ),
    )


def _truncate_in_context(
    *,
    content_str: str,
    tool_name: str,
    tool_call_id: str,
    reason: str,
    status: str,
    existing_additional_kwargs: dict[str, Any],
) -> ToolMessage | None:
    """Compact ``content_str`` in place, keeping its head and tail plus a loud marker.

    The fallback tier, used when no workspace file can be written. Unlike the
    spill this is LOSSY and unrecoverable, so the marker says so explicitly —
    the model must never mistake a truncated output for the whole thing.

    Returns ``None`` when the output already fits the budget: there is nothing
    to reclaim, and re-wrapping it would only add noise.
    """
    kept = COMPACTION_FALLBACK_HEAD_CHARS + COMPACTION_FALLBACK_TAIL_CHARS
    dropped = len(content_str) - kept
    if dropped <= 0:
        return None

    body = (
        f"{COMPACTION_TRUNCATED_MARKER} {tool_name} returned {len(content_str)} chars "
        f"({reason}). The full output could NOT be saved for later and the middle "
        f"{dropped} chars are gone for good. The first "
        f"{COMPACTION_FALLBACK_HEAD_CHARS} and last {COMPACTION_FALLBACK_TAIL_CHARS} "
        f"chars are below — if you need what was dropped, call the tool again with a "
        f"narrower query rather than assuming this is the complete result.\n\n"
        f"{content_str[:COMPACTION_FALLBACK_HEAD_CHARS]}\n\n"
        f"[... {dropped} chars dropped ...]\n\n"
        f"{content_str[-COMPACTION_FALLBACK_TAIL_CHARS:]}"
    )

    log.warning(
        f"{LogTag.AGENT} Compacted tool output in context because the workspace was unavailable",
        tool_name=tool_name,
        chars_before=len(content_str),
        chars_after=len(body),
        dropped=dropped,
        lossy=True,
        reason=reason,
    )
    return ToolMessage(
        content=body,
        tool_call_id=tool_call_id,
        name=tool_name,
        status=status,
        additional_kwargs={
            **existing_additional_kwargs,
            "original_length": len(content_str),
            "compacted": True,
            "compaction_reason": reason,
            "compaction_strategy": "in_context_truncation",
            "compaction_lossy": True,
        },
    )


async def compact_tool_output(
    *,
    content: MessageContent,
    tool_name: str,
    tool_call_id: str,
    user_id: str | None,
    conversation_id: str | None,
    context_usage: float,
    max_output_chars: int,
    compaction_threshold: float,
    status: str = "success",
    always_persist: bool = False,
    excluded: bool = False,
    existing_additional_kwargs: dict[str, Any] | None = None,
    summary_llm: LanguageModelLike | None = None,
) -> ToolMessage | None:
    """Decide-and-compact a tool output. The one canonical compaction path.

    The workspace spill runs first as an OPTIONAL lossless step (skipped without
    a workspace identity or when storage fails); an LLM digest of the output is
    the in-context payload whenever ``summary_llm`` is supplied; the legacy
    deterministic preview and head+tail truncation remain as degradation tiers.
    Returns a compacted ``ToolMessage``, or ``None`` when the output should be
    kept as-is (below threshold, excluded, or nothing to reclaim).
    """
    # Inline media can't be spilled to a text file and re-read — the block IS
    # the payload the model needs. Each block is bounded at its producer
    # (ImageCodec), and how many reach a request is bounded at the request
    # boundary (MediaAdapter), so there is nothing for compaction to do here.
    if has_media_blocks(content):
        return None
    # Text-extract rather than str(): a media-free block list would otherwise be
    # sized and previewed as its Python repr ("[{'type': 'text', ...}]").
    content_str = extract_text_content(content)
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

    # Optional lossless tier — raw bytes preserved whenever a spill target exists.
    # Missing here is never fatal: every later tier works without a spilled file
    # (issue #916: JuiceFS is an add-on to compaction, not its foundation).
    spilled: tuple[OffloadFmt, str] | None = None
    if not user_id or not conversation_id:
        log.warning(
            f"{LogTag.AGENT} Compaction has no workspace identity; compacting without a spill",
            tool_name=tool_name,
            user_id=("set" if user_id else "missing"),
            conversation_id=("set" if conversation_id else "missing"),
        )
    else:
        try:
            spilled = await _write_raw_output(
                content_str=content_str,
                tool_name=tool_name,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except JuiceFSUnavailable as e:
            log.warning(
                f"{LogTag.AGENT} Workspace unavailable, compacting without a spill",
                tool_name=tool_name,
                error_type=type(e).__name__,
            )
        except Exception as e:
            log.error(
                f"{LogTag.AGENT} Workspace spill failed, compacting without a spill",
                tool_name=tool_name,
                error=str(e),
                error_type=type(e).__name__,
            )

    # Primary payload — the LLM digest. On failure this degrades to the
    # deterministic tiers below rather than failing the tool call.
    if summary_llm is not None:
        summary = await _llm_summarize_output(summary_llm, content_str, tool_name)
        if summary is not None:
            return _summarized_compact_message(
                summary=summary,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                reason=reason,
                status=status,
                content_str=content_str,
                spilled=spilled,
                existing_additional_kwargs=existing_additional_kwargs or {},
            )

    if spilled is not None:
        return _stub_spill_message(
            content_str=content_str,
            fmt=spilled[0],
            sandbox_path=spilled[1],
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            reason=reason,
            status=status,
            existing_additional_kwargs=existing_additional_kwargs or {},
        )

    log.warning(
        f"{LogTag.AGENT} No spill and no LLM digest available; truncating in context",
        tool_name=tool_name,
    )
    return _truncate_in_context(
        content_str=content_str,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        reason=reason,
        status=status,
        existing_additional_kwargs=existing_additional_kwargs or {},
    )


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
        summary_llm: LanguageModelLike | None = None,
    ) -> None:
        super().__init__()
        self.compaction_threshold = compaction_threshold
        self.max_output_chars = max_output_chars
        self.always_persist_tools = always_persist_tools or []
        self.context_window = context_window
        self.excluded_tools = excluded_tools or set()
        # The graph's chat LLM. Invoked with the request's configurable bound
        # (same as the model node), so digests ride the conversation's model.
        self.summary_llm = summary_llm

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        result = await handler(request)
        if not isinstance(result, ToolMessage):
            return result

        # `ToolCall` is a TypedDict, but tool calls also reach middleware in
        # attribute form; Any keeps the else-branch from being narrowed away.
        tool_call: Any = request.tool_call
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name", "")
            tool_call_id = tool_call.get("id", "")
        else:
            tool_name = tool_call.name
            tool_call_id = tool_call.id

        configurable = runtime_configurable(request)
        thread_id = configurable.get("thread_id")

        # Same per-request routing the model node does: bind this request's
        # configurable so the digest rides the conversation's chosen model.
        summary_llm = self.summary_llm
        if summary_llm is not None and hasattr(summary_llm, "with_config"):
            summary_llm = summary_llm.with_config(configurable=configurable)

        compacted = await compact_tool_output(
            content=result.content if hasattr(result, "content") else str(result),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            user_id=configurable.get("user_id"),
            conversation_id=configurable.get("vfs_session_id") or thread_id,
            context_usage=self._get_context_usage(request),
            max_output_chars=self.max_output_chars,
            compaction_threshold=self.compaction_threshold,
            status=result.status,
            always_persist=tool_name in self.always_persist_tools,
            excluded=tool_name in self.excluded_tools,
            existing_additional_kwargs=getattr(result, "additional_kwargs", {}),
            summary_llm=summary_llm,
        )
        result = compacted if compacted is not None else result

        # Whether we just offloaded the output or the tool self-offloaded (gmail,
        # which is excluded from compaction), surface the file-mining tools the
        # moment a marker is present. Keyed on the offload itself, so it covers
        # every producer uniformly.
        return self._bind_offload_tools(result, request)

    def _bind_offload_tools(
        self, result: ToolMessage, request: ToolCallRequest
    ) -> ToolMessage | Command[Any]:
        """Append query_json/grep to ``selected_tool_ids`` if ``result`` carries an offload marker.

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
            return estimate_context_usage(state.get("messages", []), self.context_window)
        except Exception as exc:
            # 0.0 reads as "context is empty", which is the one value that stops
            # compaction from ever triggering — never let that happen quietly.
            log.warning(
                f"{LogTag.AGENT} Context-usage estimate failed, treating as 0%",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0.0
