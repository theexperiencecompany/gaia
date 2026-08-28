"""Classify whether a tool is destructive for the HIL approval gate.

Resolution order (first match wins):

1. Exempt orchestration/plumbing tools → safe.
2. A server-declared MCP ``destructiveHint`` → destructive. Escalation-only: an
   untrusted MCP server may flag danger but never clear it, so ``readOnlyHint``
   and ``destructiveHint=False`` are ignored; a true hint gates even over a
   reviewed-safe registry flag.
3. The tool registry's flag — authoritative for internal tools and curated
   integration slugs.
4. A cached Mongo classification for a previously-seen custom tool.
5. A one-shot LLM classification, persisted to Mongo + the live registry.

Any failure — registry unavailable, LLM error, or a tool absent from every
source — resolves to destructive (fail closed).
"""

import hashlib

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agents.llm.client import SILENT_LLM_CONFIG, StructuredCallOptions, ainvoke_structured
from app.agents.tools.core.registry import ToolRegistry, get_tool_registry
from app.constants.hil import HIL_EXEMPT_TOOLS, HIL_LLM_TIMEOUT_SECONDS
from app.constants.log_tags import LogTag
from app.db.repositories.hil import hil_tool_risk_repository
from app.models.hil_models import HILToolRiskRecord
from app.services.hil.prompts import TOOL_CLASSIFY_PROMPT
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY
from shared.py.wide_events import log


class _ClassifyResult(BaseModel):
    is_destructive: bool = Field(description="True if the tool is destructive.")
    rationale: str = Field(default="", description="One short sentence of reasoning.")


async def is_tool_destructive(
    tool_name: str,
    description: str = "",
    *,
    destructive_hint: bool | None = None,
) -> bool:
    """Return whether ``tool_name`` must be gated by HIL. Fails closed.

    ``destructive_hint`` is the caller-read MCP ``destructiveHint`` (see
    :func:`mcp_destructive_hint`); it escalates an otherwise-unclassified tool
    to destructive without an LLM call.
    """
    if tool_name in HIL_EXEMPT_TOOLS:
        return False
    # Escalation-only (see module docstring): a true hint gates even over a
    # reviewed-safe registry flag.
    if destructive_hint is True:
        return True
    try:
        registry = await get_tool_registry()
        flag = registry.is_tool_destructive(tool_name)
        if flag is not None:
            return flag
        return await _classify_unknown_tool(registry, tool_name, description)
    except Exception as e:
        # Fail closed: every failure mode (registry/LLM/Mongo down, unknown tool)
        # must gate rather than let a possibly-destructive call run unattended.
        log.warning(
            f"{LogTag.HIL} Failed to classify, failing closed",
            tool_name=tool_name,
            error=str(e),
            error_type=type(e).__name__,
        )
        return True


def mcp_destructive_hint(tool: BaseTool | None) -> bool | None:
    """Return ``True`` only when an MCP tool declares itself destructive.

    Honors the ``destructiveHint`` annotation ``SanitizingLangChainAdapter``
    stashes on tool metadata. Escalation-only (see module docstring): a falsey
    or missing hint yields ``None`` (defer), never ``False``.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    annotations = metadata.get(MCP_ANNOTATIONS_METADATA_KEY)
    if isinstance(annotations, dict) and annotations.get("destructiveHint") is True:
        return True
    return None


async def _classify_unknown_tool(registry: ToolRegistry, tool_name: str, description: str) -> bool:
    """Resolve an unclassified custom tool from the Mongo cache, else the LLM."""
    description_hash = _description_hash(description)
    cached = await _cached_classification(tool_name, description_hash)
    if cached is not None:
        registry.mark_tool_destructive(tool_name, cached)
        return cached

    result = await _classify_with_llm(tool_name, description)
    await _persist_classification(tool_name, description_hash, result)
    registry.mark_tool_destructive(tool_name, result.is_destructive)
    return result.is_destructive


async def _cached_classification(tool_name: str, description_hash: str) -> bool | None:
    """A prior classification for this exact tool+description, or ``None``."""
    record = await hil_tool_risk_repository.find_classification(tool_name, description_hash)
    return record.is_destructive if record else None


async def _classify_with_llm(tool_name: str, description: str) -> _ClassifyResult:
    """Classify a TOOL, not a request — so this call deliberately carries no
    user attribution. The verdict is cached per tool+description (DB + registry)
    and shared by every user, so billing its COGS to whichever user happened to
    trigger the first classification would be arbitrary. The unattributed-spend
    warning from ``ainvoke_structured`` is expected here, and rare: this runs
    once per tool, not per call."""
    return await ainvoke_structured(
        _ClassifyResult,
        TOOL_CLASSIFY_PROMPT.format(name=tool_name, description=description or "(none provided)"),
        label="hil_tool_classification",
        config=SILENT_LLM_CONFIG,
        options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
    )


async def _persist_classification(
    tool_name: str, description_hash: str, result: _ClassifyResult
) -> None:
    """Cache the classification in Mongo so restarts/refreshes don't re-run the
    LLM (the description_hash key means only a changed description re-classifies)."""
    record = HILToolRiskRecord(
        tool_name=tool_name,
        description_hash=description_hash,
        is_destructive=result.is_destructive,
        rationale=result.rationale,
    )
    await hil_tool_risk_repository.upsert_classification(record)


def _description_hash(description: str) -> str:
    return hashlib.md5(description.encode(), usedforsecurity=False).hexdigest()  # nosec B324
