"""Decide whether a tool only reads, for a read-only run (a brief scout) and its call-time guard.

A tool's own metadata is final: MCP readOnlyHint/destructiveHint or Composio's tags. When the
metadata is silent, a write-intent token in its name or description is a hard no, and
otherwise a cheap model judging the name, description and full input schema decides. That verdict is cached per tool shape (name, description,
input schema), so a tool is classified once and again only when its shape changes.
"""

import hashlib
import json
import re

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agents.llm.client import SILENT_LLM_CONFIG, StructuredCallOptions, ainvoke_structured
from app.constants.hil import (
    COMPOSIO_TAGS_METADATA_KEY,
    COMPOSIO_WRITE_TAGS,
    HIL_LLM_TIMEOUT_SECONDS,
    MCP_DESTRUCTIVE_HINT,
    MCP_READ_ONLY_HINT,
    WRITE_INTENT_TOKENS,
)
from app.db.repositories.hil import tool_read_only_verdict_repository
from app.models.hil_models import ToolReadOnlyVerdict
from app.services.hil.prompts import TOOL_READ_ONLY_PROMPT
from app.services.hil.utils import tool_schema, untrusted_fence
from app.services.mcp.langchain_adapter import MCP_ANNOTATIONS_METADATA_KEY
from shared.py.wide_events import log

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_NON_LETTERS = re.compile(r"[^a-z]+")


class _ReadOnlyJudgement(BaseModel):
    has_side_effects: bool = Field(
        description="True if calling the tool could change any state, anywhere, or contact anyone."
    )
    certain: bool = Field(description="False if the name, description or schema leave any doubt.")
    rationale: str = Field(default="", description="One short sentence of reasoning.")


def read_only_declaration(tool: BaseTool | None) -> bool | None:
    """Return what the tool's own metadata says about reading only; None when it says nothing.

    MCP: readOnlyHint true and destructiveHint not true; a false readOnlyHint or a true
    destructiveHint is a no. Composio: tagged readOnlyHint and with none of its write tags.
    """
    metadata = getattr(tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    annotations = metadata.get(MCP_ANNOTATIONS_METADATA_KEY)
    if isinstance(annotations, dict):
        if annotations.get(MCP_DESTRUCTIVE_HINT) is True:
            return False
        if MCP_READ_ONLY_HINT in annotations:
            return annotations[MCP_READ_ONLY_HINT] is True
    tags = metadata.get(COMPOSIO_TAGS_METADATA_KEY)
    if isinstance(tags, list | tuple | frozenset | set):
        return MCP_READ_ONLY_HINT in tags and not COMPOSIO_WRITE_TAGS.intersection(tags)
    return None


def _words(text: str) -> list[str]:
    """Split snake, kebab, dotted and camel case text into lowercase words."""
    return [
        word for word in _NON_LETTERS.split(_CAMEL_BOUNDARY.sub(r"\1 \2", text).lower()) if word
    ]


def _base_forms(word: str, *, past_tense: bool) -> set[str]:
    """Return the word and the base verbs it may inflect; past tense only when asked."""
    forms = {word}
    if word.endswith("s"):
        forms |= {word[:-1], word[:-2]}
    if word.endswith("ing"):
        stem = word[:-3]
        forms |= {stem, stem + "e", stem[:-1]}
    if past_tense and word.endswith("ed"):
        forms |= {word[:-1], word[:-2], word[:-3]}
    return forms


def _has_write_intent(words: list[str], *, past_tense: bool) -> bool:
    return any(WRITE_INTENT_TOKENS & _base_forms(word, past_tense=past_tense) for word in words)


def voices_write_intent(name: str, description: str) -> bool:
    """Whether the name or description carries a write-intent token.

    A description's past participles describe data ("issues created this week"), so only
    its present forms count as intent; the name counts every inflection.
    """
    return _has_write_intent(_words(name), past_tense=True) or _has_write_intent(
        _words(description), past_tense=False
    )


def tool_shape_hash(tool: BaseTool) -> str:
    """Hash the tool's name, description and input schema; any change means a new verdict."""
    shape = {"name": tool.name, "description": tool.description, "schema": tool_schema(tool)}
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()


async def is_read_only(tool: BaseTool | None) -> bool:
    """Return whether a read-only run may call the tool; any doubt is a no.

    Metadata decides when it speaks. Otherwise the write-intent check gates a cached
    cheap-model verdict, classified on first sight of this tool shape. Raises when that fails.
    """
    if tool is None:
        return False
    declared = read_only_declaration(tool)
    if declared is not None:
        return declared
    if voices_write_intent(tool.name, tool.description):
        return False
    shape_hash = tool_shape_hash(tool)
    cached = await tool_read_only_verdict_repository.find_verdict(shape_hash)
    if cached is not None:
        return cached.read_only
    verdict = await _classify(tool, shape_hash)
    await tool_read_only_verdict_repository.upsert_verdict(verdict)
    log.info(
        "hil.tool_read_only_classified",
        tool_name=tool.name,
        tool_hash=shape_hash,
        read_only=verdict.read_only,
        rationale=verdict.rationale,
    )
    return verdict.read_only


async def _classify(tool: BaseTool, shape_hash: str) -> ToolReadOnlyVerdict:
    """Ask the helper model about a TOOL, not a request: unattributed, as it runs once per shape."""
    judgement = await ainvoke_structured(
        _ReadOnlyJudgement,
        TOOL_READ_ONLY_PROMPT.format(
            nonce=untrusted_fence(),
            name=tool.name,
            description=tool.description or "(none provided)",
            schema=json.dumps(tool_schema(tool), sort_keys=True, default=str),
        ),
        label="hil_tool_read_only_classification",
        config=SILENT_LLM_CONFIG,
        options=StructuredCallOptions(timeout=HIL_LLM_TIMEOUT_SECONDS),
    )
    return ToolReadOnlyVerdict(
        tool_hash=shape_hash,
        tool_name=tool.name,
        read_only=judgement.certain and not judgement.has_side_effects,
        rationale=judgement.rationale,
    )
