"""`query_json` tool — filter/project/aggregate an offloaded JSON/JSONL file.

Runs entirely in the API process over the parsed records: filter by field
conditions, project fields, sort, limit, count, dedupe, group-count. It is safe
by construction — pure dict/list operations with no code execution, no file or
network access beyond the one workspace file, and bounded input/output. This is
the in-process, sandbox-free replacement for running `jq` on the host.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool

from app.agents.tools.coding._context import canonical_rel, get_session_id, get_user_id
from app.constants.log_tags import LogTag
from app.constants.offload import (
    MAX_FILTER_OUTPUT_CHARS,
    MAX_QUERY_CONCURRENCY,
    MAX_QUERY_INPUT_BYTES,
    MAX_QUERY_RECORDS,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import FsOps, fs_timer, resolve_user_file
from app.templates.docstrings.coding_tools_docs import QUERY_JSON_TOOL
from app.utils.concurrency import loop_bound_semaphore
from shared.py.wide_events import log

# Condition operators. All are pure comparisons over already-parsed JSON values —
# note there is deliberately no regex op (ReDoS can't be killed in-process); use
# `grep` for regex/free-text.
_OPS = frozenset(
    {"contains", "equals", "not_equals", "is_true", "is_false", "exists", "gt", "lt", "in"}
)


def _hashable(value: Any) -> Any:
    """A stable hashable key for grouping/dedup — list/dict fields become a JSON string."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _sort_key(value: Any) -> tuple[int, Any]:
    """Type-ranked key so heterogeneous field values never compare across types."""
    if value is None:
        return (0, 0)
    if isinstance(value, bool):  # bool before int (bool is an int subclass)
        return (1, value)
    if isinstance(value, (int, float)):
        return (2, value)
    if isinstance(value, str):
        return (3, value)
    return (4, json.dumps(value, sort_keys=True, default=str))


@tool
@with_rate_limiting("workspace_query_json")
@with_doc(QUERY_JSON_TOOL)
async def query_json(
    config: RunnableConfig,
    path: Annotated[str, "JSON/JSONL file inside the workspace (relative = session scratch)"],
    where: Annotated[
        list[dict] | None,
        "Filters: [{field, op, value}]; op in contains|equals|not_equals|is_true|is_false|exists|gt|lt|in",
    ] = None,
    match: Annotated[str, "Combine filters with 'all' (AND) or 'any' (OR)"] = "all",
    fields: Annotated[list[str] | None, "Only return these fields (None = all)"] = None,
    sort_by: Annotated[str | None, "Field to sort by"] = None,
    order: Annotated[str, "'asc' or 'desc'"] = "desc",
    limit: Annotated[int, "Max records to return"] = 50,
    count_only: Annotated[bool, "Return just the match count"] = False,
    unique_by: Annotated[str | None, "Dedupe by this field"] = None,
    group_count_by: Annotated[str | None, "Return counts per distinct value of this field"] = None,
) -> str:
    """Query a workspace JSON/JSONL file: filter, project, sort, count, dedupe, group."""
    log.set(tool={"name": "query_json", "action": "query"})
    try:
        user_id = get_user_id(config)
        abs_path, rel = canonical_rel(path, session_id=get_session_id(config))
    except ValueError as e:
        return f"Error: {e}"

    if match not in ("all", "any"):
        return "Error: match must be 'all' or 'any'"
    bad_ops = [c.get("op") for c in (where or []) if c.get("op") not in _OPS]
    if bad_ops:
        return f"Error: unknown filter op(s) {bad_ops}; allowed: {sorted(_OPS)}"

    try:
        # Hold a concurrency slot across the read + query so only a bounded number
        # of large record sets are alive at once (cap total memory).
        async with (
            loop_bound_semaphore("query_json", MAX_QUERY_CONCURRENCY),
            fs_timer(FsOps.TOOL_QUERY_JSON),
        ):
            target = await resolve_user_file(user_id, rel)
            records, dropped, truncated = await asyncio.to_thread(_load_records, target)
            result = _apply_query(
                records,
                where=where or [],
                match=match,
                fields=fields,
                sort_by=sort_by,
                order=order,
                limit=limit,
                count_only=count_only,
                unique_by=unique_by,
                group_count_by=group_count_by,
            )
    except FileNotFoundError:
        return f"Error: file not found at {abs_path}"
    except Exception as e:
        log.error(f"{LogTag.SANDBOX} query_json failed: {e}", exc_info=True)
        return f"Error running query_json: {e}"

    return _format_result(result, dropped=dropped, truncated=truncated)


def _load_records(target: Path) -> tuple[list[dict], int, bool]:
    """Read a JSON-array or JSONL file into a list of dict records (bounded).

    Reads AT MOST ``MAX_QUERY_INPUT_BYTES`` (never the whole file — a multi-GB file
    would OOM the process) and parses AT MOST ``MAX_QUERY_RECORDS`` records.
    """
    with target.open("rb") as fh:
        raw = fh.read(MAX_QUERY_INPUT_BYTES + 1)  # cap+1 to detect overflow, no more
    truncated = len(raw) > MAX_QUERY_INPUT_BYTES
    text = raw[:MAX_QUERY_INPUT_BYTES].decode("utf-8", "replace")

    if text.lstrip()[:1] == "[":
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, RecursionError, ValueError):
            # Array-shaped but unparseable — almost always the byte cap cut it off.
            # Signal truncation instead of re-parsing as JSONL (which would drop
            # every pretty-printed line and hide the real cause).
            return [], 0, True
        records = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        if len(records) > MAX_QUERY_RECORDS:
            records = records[:MAX_QUERY_RECORDS]
            truncated = True
        return records, 0, truncated

    records = []
    dropped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, RecursionError, ValueError):
            dropped += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            dropped += 1
        if len(records) >= MAX_QUERY_RECORDS:
            truncated = True
            break
    return records, dropped, truncated


def _match_condition(record: dict, cond: dict) -> bool:
    field = cond.get("field")
    op = cond.get("op")
    value = cond.get("value")
    present = isinstance(field, str) and field in record
    actual = record.get(field) if isinstance(field, str) else None

    if op == "exists":
        return present
    if op == "is_true":  # present AND truthy (a missing field is neither true nor false)
        return present and bool(actual)
    if op == "is_false":
        return present and not bool(actual)
    if op == "equals":
        return actual == value
    if op == "not_equals":
        return actual != value
    if op == "contains":  # value=None must not become the literal "none"
        return value is not None and isinstance(actual, str) and str(value).lower() in actual.lower()
    if op == "in":  # value is present in a list-valued field (e.g. labels)
        return isinstance(actual, list) and value in actual
    if op in ("gt", "lt"):
        try:
            return actual > value if op == "gt" else actual < value  # type: ignore[operator]
        except TypeError:
            return False
    return False


def _match_record(record: dict, where: list[dict], match: str) -> bool:
    if not where:
        return True
    results = (_match_condition(record, c) for c in where)
    return all(results) if match == "all" else any(results)


def _apply_query(
    records: list[dict],
    *,
    where: list[dict],
    match: str,
    fields: list[str] | None,
    sort_by: str | None,
    order: str,
    limit: int,
    count_only: bool,
    unique_by: str | None,
    group_count_by: str | None,
) -> Any:
    matched = [r for r in records if _match_record(r, where, match)]

    if count_only:
        return {"count": len(matched)}

    if group_count_by:
        counts: dict[Any, int] = {}
        originals: dict[Any, Any] = {}
        for r in matched:
            v = r.get(group_count_by)
            k = _hashable(v)  # list/dict values would be unhashable otherwise
            counts[k] = counts.get(k, 0) + 1
            originals.setdefault(k, v)
        grouped = [{"value": originals[k], "count": n} for k, n in counts.items()]
        grouped.sort(key=lambda g: g["count"], reverse=True)
        return grouped

    if unique_by:
        seen: set[Any] = set()
        deduped = []
        for r in matched:
            key = _hashable(r.get(unique_by))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        matched = deduped

    if sort_by:
        matched.sort(key=lambda r: _sort_key(r.get(sort_by)), reverse=(order == "desc"))

    matched = matched[: max(0, limit)]  # limit<=0 -> empty (count_only exists for counts)

    if fields:
        matched = [{k: r.get(k) for k in fields} for r in matched]
    return matched


def _format_result(result: Any, *, dropped: int, truncated: bool) -> str:
    if isinstance(result, dict):  # count_only
        body = json.dumps(result)
    elif not result:
        body = "(no matches)"
    else:
        body = "\n".join(json.dumps(r, default=str) for r in result)

    notes = []
    if truncated:
        notes.append("input truncated (file too large) — results may be incomplete")
    if dropped:
        notes.append(f"{dropped} unparseable line(s) skipped")
    if len(body) > MAX_FILTER_OUTPUT_CHARS:
        body = body[:MAX_FILTER_OUTPUT_CHARS]
        notes.append(f"output truncated at {MAX_FILTER_OUTPUT_CHARS} chars — narrow the filter or lower limit")

    return body + ("\n\n[" + "; ".join(notes) + "]" if notes else "")
