"""Structured marker + helpers for tool outputs offloaded to a workspace file.

Both offload producers (the compaction middleware and a self-offloading tool
like the gmail fetch) stamp an ``OffloadInfo`` under
``additional_kwargs[OFFLOAD_KEY]``. The compaction middleware reads it through
``read_offload`` to decide which file-mining tools to surface. One marker, one
read path — no content parsing.
"""

from __future__ import annotations

import json
from typing import Literal, TypedDict

from langchain_core.messages import ToolMessage

from app.constants.offload import (
    GREP_TOOL_NAME,
    OFFLOAD_JSON_FORMATS,
    OFFLOAD_KEY,
    OFFLOAD_RESULT_KEY,
    QUERY_JSON_TOOL_NAME,
)


class OffloadInfo(TypedDict):
    path: str  # /workspace sandbox path of the offloaded file
    bytes: int  # file size in bytes
    fmt: Literal["jsonl", "json", "text"]  # how the file should be mined
    producer: str  # tool name that produced the offload
    records: int | None  # line/message count when known, else None


def mark_offload(additional_kwargs: dict, info: OffloadInfo) -> dict:
    """Return a copy of ``additional_kwargs`` with the offload marker attached."""
    return {**additional_kwargs, OFFLOAD_KEY: info}


def read_offload(message: ToolMessage) -> OffloadInfo | None:
    """Extract the offload marker from a tool message, or None if absent."""
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    info = kwargs.get(OFFLOAD_KEY)
    if isinstance(info, dict) and isinstance(info.get("path"), str):
        return info  # type: ignore[return-value]
    return None


def pop_offload_descriptor(result: object) -> OffloadInfo | None:
    """Pop a self-offloading tool's descriptor from its dict result, or None.

    Mutates ``result`` (removes ``OFFLOAD_RESULT_KEY``) so the descriptor never
    leaks into the model-facing tool content — it carries only the structured
    marker. The tool's own human-facing fields (preview, hint, …) are untouched.
    """
    if not isinstance(result, dict):
        return None
    info = result.pop(OFFLOAD_RESULT_KEY, None)
    if isinstance(info, dict) and isinstance(info.get("path"), str):
        return info  # type: ignore[return-value]
    return None


def _is_json_object(line: str) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except (json.JSONDecodeError, ValueError):
        return False


def sniff_offload_fmt(text: str) -> Literal["json", "jsonl", "text"]:
    """Classify an offloaded payload so the right miner (query_json/grep) is bound.

    Cheap heuristic (samples a few lines, never full-parses a big blob): a leading
    ``[`` is treated as a JSON array; a file whose first non-empty lines are all
    JSON objects is JSONL; anything else is free text.
    """
    if text.lstrip()[:1] == "[":
        return "json"
    sample = [ln for ln in text.splitlines() if ln.strip()][:5]
    if sample and all(_is_json_object(ln) for ln in sample):
        return "jsonl"
    return "text"


def tools_for_offload(info: OffloadInfo) -> list[str]:
    """Mining tools to surface for an offload: query_json for records, grep for text.

    Tolerant of a missing/unknown ``fmt`` (defaults to grep) so it never raises on
    a marker that only satisfied ``read_offload``'s ``path`` check.
    """
    if info.get("fmt") in OFFLOAD_JSON_FORMATS:
        return [QUERY_JSON_TOOL_NAME, GREP_TOOL_NAME]
    return [GREP_TOOL_NAME]
