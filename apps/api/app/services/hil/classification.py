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

A CLI-backed call is the one exception, and it takes a ``command_shape`` (see
:mod:`app.services.hil.command_shape`). One CLI integration is one tool, so its name
covers every command that CLI can run and step 3 has nothing to say about any of them:
the verdict resolves on steps 4-5 alone, keyed by ``(tool name, command shape)``, and is
never written back to the registry's name-keyed flag.

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
from app.services.hil.prompts import CLI_COMMAND_CLASSIFY_PROMPT, TOOL_CLASSIFY_PROMPT
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
    command_shape: str | None = None,
) -> bool:
    """Return whether this call must be gated by HIL. Fails closed.

    ``destructive_hint`` is the caller-read MCP ``destructiveHint`` (see
    :func:`mcp_destructive_hint`); it escalates an otherwise-unclassified tool
    to destructive without an LLM call.

    ``command_shape`` is set only for a CLI-backed call (see
    :func:`app.services.hil.command_shape.cli_command_shape`). It moves the verdict from
    the tool to the command the call would run — including ``""``, which means the
    command could not be shaped at all and therefore gates.
    """
    if tool_name in HIL_EXEMPT_TOOLS:
        return False
    # Escalation-only (see module docstring): a true hint gates even over a
    # reviewed-safe registry flag.
    if destructive_hint is True:
        return True
    try:
        if command_shape is not None:
            return await _classify_command(tool_name, description, command_shape)
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
    subject_hash = _subject_hash(description)
    cached = await _cached_classification(tool_name, subject_hash)
    if cached is not None:
        registry.mark_tool_destructive(tool_name, cached)
        return cached

    result = await _classify_with_llm(tool_name, description)
    await _persist_classification(tool_name, subject_hash, result)
    registry.mark_tool_destructive(tool_name, result.is_destructive)
    return result.is_destructive


async def _classify_command(tool_name: str, description: str, command_shape: str) -> bool:
    """Resolve ONE CLI command's risk from the Mongo cache, else the LLM.

    The registry's ``destructive`` flag is deliberately neither read nor written here.
    It is keyed by tool name, and one CLI tool name covers every command that CLI can
    run: a verdict earned by ``gh repo delete`` must never become the verdict for
    ``gh pr list``, in either direction.
    """
    if not command_shape:
        # The command could not be reduced to anything stable enough to classify or
        # cache (see command_shape). An unreadable command is not a safe one.
        log.warning(f"{LogTag.HIL} Unshapeable CLI command, failing closed", tool_name=tool_name)
        return True

    subject_hash = _subject_hash(description, command_shape)
    cached = await _cached_classification(tool_name, subject_hash)
    if cached is not None:
        return cached

    result = await _classify_with_llm(tool_name, description, command_shape)
    await _persist_classification(tool_name, subject_hash, result, command_shape)
    return result.is_destructive


async def _cached_classification(tool_name: str, subject_hash: str) -> bool | None:
    """A prior classification of this exact subject for this tool, or ``None``."""
    record = await hil_tool_risk_repository.find_classification(tool_name, subject_hash)
    return record.is_destructive if record else None


async def _classify_with_llm(
    tool_name: str, description: str, command_shape: str = ""
) -> _ClassifyResult:
    """Classify a TOOL — or, for a CLI-backed call, the COMMAND it would run — and never
    a request, so this call deliberately carries no user attribution. The verdict is
    cached per subject (DB + registry) and shared by every user, so billing its COGS to
    whichever user happened to trigger the first classification would be arbitrary. The
    unattributed-spend warning from ``ainvoke_structured`` is expected here, and rare:
    this runs once per subject, not per call."""
    described = description or "(none provided)"
    prompt = (
        CLI_COMMAND_CLASSIFY_PROMPT.format(
            name=tool_name, description=described, command=command_shape
        )
        if command_shape
        else TOOL_CLASSIFY_PROMPT.format(name=tool_name, description=described)
    )
    return await ainvoke_structured(
        _ClassifyResult,
        prompt,
        label="hil_tool_classification",
        config=SILENT_LLM_CONFIG,
        options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
    )


async def _persist_classification(
    tool_name: str, subject_hash: str, result: _ClassifyResult, command_shape: str = ""
) -> None:
    """Cache the classification in Mongo so restarts/refreshes don't re-run the
    LLM (the hashed subject means only a changed description — or a different CLI
    command shape — re-classifies)."""
    record = HILToolRiskRecord(
        tool_name=tool_name,
        description_hash=subject_hash,
        is_destructive=result.is_destructive,
        command_shape=command_shape,
        rationale=result.rationale,
    )
    await hil_tool_risk_repository.upsert_classification(record)


def _subject_hash(description: str, command_shape: str = "") -> str:
    """The cache key's body: what was classified, not merely which tool asked.

    A CLI command's shape is folded in, so one tool name holds one verdict per command
    it can run. Everything else hashes the description alone, byte for byte as before,
    so verdicts cached before CLI tools existed still hit.
    """
    subject = f"{description}\n{command_shape}" if command_shape else description
    return hashlib.md5(subject.encode(), usedforsecurity=False).hexdigest()  # nosec B324
