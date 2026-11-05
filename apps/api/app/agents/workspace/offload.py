"""Structured marker + helpers for tool outputs offloaded to a workspace file.

The compaction middleware stamps an OffloadInfo under
additional_kwargs[OFFLOAD_KEY]. The compaction middleware reads it through
read_offload to decide which file-mining tools to surface. One marker, one
read path — no content parsing.
"""

from __future__ import annotations

import json
from typing import Literal, NamedTuple, TypedDict

from langchain_core.messages import ToolMessage

from app.constants.offload import (
    GREP_TOOL_NAME,
    OFFLOAD_JSON_FORMATS,
    OFFLOAD_KEY,
    QUERY_JSON_TOOL_NAME,
)


class OffloadInfo(TypedDict):
    path: str  # /workspace sandbox path of the offloaded file
    bytes: int  # file size in bytes
    fmt: Literal["jsonl", "json", "text"]  # how the file should be mined
    producer: str  # tool name that produced the offload
    records: int | None  # line/message count when known, else None


def mark_offload(additional_kwargs: dict[str, object], info: OffloadInfo) -> dict[str, object]:
    """Return a copy of additional_kwargs with the offload marker attached."""
    return {**additional_kwargs, OFFLOAD_KEY: info}


def read_offload(message: ToolMessage) -> OffloadInfo | None:
    """Extract the offload marker from a tool message, or None if absent."""
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    # Read off the wire, so the declared shape is only trusted once path checks out.
    info: OffloadInfo | None = kwargs.get(OFFLOAD_KEY)
    if isinstance(info, dict) and isinstance(info.get("path"), str):
        return info
    return None


def _is_json_object(line: str) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except (json.JSONDecodeError, ValueError):
        return False


def sniff_offload_fmt(text: str) -> Literal["json", "jsonl", "text"]:
    """Classify an offloaded payload so the right miner (query_json/grep) is bound.

    Cheap heuristic (samples a few lines, never full-parses a big blob): a leading
    [ is treated as a JSON array; a file whose first non-empty lines are all
    JSON objects is JSONL; anything else is free text.
    """
    if text.lstrip()[:1] == "[":
        return "json"
    sample = [ln for ln in text.splitlines() if ln.strip()][:5]
    if sample and all(_is_json_object(ln) for ln in sample):
        return "jsonl"
    return "text"


JSONScalar = str | int | float | bool | None


class OffloadRecords(NamedTuple):
    """A payload's one record list, plus the scalar fields around it that a JSONL file drops."""

    records: list[dict[str, object]]
    metadata: dict[str, JSONScalar]


def _records_in(value: object, path: str) -> OffloadRecords | None:
    """Descend a JSON object to its single list of objects, when every other field is a scalar."""
    if isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            return OffloadRecords(records=value, metadata={})
        return None
    if not isinstance(value, dict):
        return None
    scalars: dict[str, JSONScalar] = {}
    nested: list[tuple[str, object]] = []
    for key, item in value.items():
        if item is None or isinstance(item, (str, int, float, bool)):
            scalars[f"{path}{key}"] = item
        else:
            nested.append((key, item))
    if len(nested) != 1:
        return None
    key, item = nested[0]
    found = _records_in(item, f"{path}{key}.")
    if found is None:
        return None
    return OffloadRecords(records=found.records, metadata={**scalars, **found.metadata})


def extract_offload_records(text: str) -> OffloadRecords | None:
    """Split out the record list an enveloped object carries, e.g. {"data": {"messages": [...]}}.

    None for anything else: a top-level array is already queryable as-is, and an
    object holding two collections (or none) has no single record set to split out.
    """
    if text.lstrip()[:1] != "{":
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, RecursionError, ValueError):
        return None
    return _records_in(payload, "")


def tools_for_offload(info: OffloadInfo) -> list[str]:
    """Mining tools to surface for an offload: query_json for records, grep for text.

    Tolerant of a missing/unknown fmt (defaults to grep) so it never raises on
    a marker that only satisfied read_offload's path check.
    """
    if info.get("fmt") in OFFLOAD_JSON_FORMATS:
        return [QUERY_JSON_TOOL_NAME, GREP_TOOL_NAME]
    return [GREP_TOOL_NAME]
