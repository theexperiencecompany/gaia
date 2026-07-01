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

from app.agents.tools.coding._context import canonical_path, get_session_id, get_user_id
from app.agents.workspace.paths import WORKSPACE_ROOT
from app.constants.log_tags import LogTag
from app.constants.offload import (
    MAX_FILTER_OUTPUT_CHARS,
    MAX_QUERY_INPUT_BYTES,
    MAX_QUERY_RECORDS,
)
from app.decorators import with_doc, with_rate_limiting
from app.services.storage import FsOps, fs_timer, resolve_user_file
from app.templates.docstrings.coding_tools_docs import QUERY_JSON_TOOL
from shared.py.wide_events import log

# Condition operators. All are pure comparisons over already-parsed JSON values —
# note there is deliberately no regex op (ReDoS can't be killed in-process); use
# `grep` for regex/free-text.
_OPS = frozenset(
    {"contains", "equals", "not_equals", "is_true", "is_false", "exists", "gt", "lt", "in"}
)


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
        session_id = get_session_id(config)
        abs_path, _, _ = canonical_path(path, session_id=session_id)
    except ValueError as e:
        return f"Error: {e}"

    rel = abs_path[len(WORKSPACE_ROOT) + 1 :] if abs_path != WORKSPACE_ROOT else ""
    if not rel:
        return "Error: path must be a file inside the workspace, not the workspace root"

    if match not in ("all", "any"):
        return "Error: match must be 'all' or 'any'"
    bad_ops = [c.get("op") for c in (where or []) if c.get("op") not in _OPS]
    if bad_ops:
        return f"Error: unknown filter op(s) {bad_ops}; allowed: {sorted(_OPS)}"

    try:
        async with fs_timer(FsOps.TOOL_QUERY_JSON):
            target = await resolve_user_file(user_id, rel)
            records, dropped, truncated = await asyncio.to_thread(_load_records, target)
    except FileNotFoundError:
        return f"Error: file not found at {abs_path}"
    except Exception as e:
        log.error(f"{LogTag.SANDBOX} query_json failed: {e}", exc_info=True)
        return f"Error running query_json: {e}"

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
    return _format_result(result, dropped=dropped, truncated=truncated)


def _load_records(target: Path) -> tuple[list[dict], int, bool]:
    """Read a JSON-array or JSONL file into a list of dict records (bounded)."""
    raw = target.read_bytes()[: MAX_QUERY_INPUT_BYTES + 1]
    truncated = len(raw) > MAX_QUERY_INPUT_BYTES
    text = raw[:MAX_QUERY_INPUT_BYTES].decode("utf-8", "replace")

    if text.lstrip()[:1] == "[":
        try:
            data = json.loads(text)
            return [r for r in data if isinstance(r, dict)], 0, truncated
        except json.JSONDecodeError:
            pass  # truncated/invalid array — fall through to line parsing

    records: list[dict] = []
    dropped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
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
    actual = record.get(field) if isinstance(field, str) else None

    if op == "exists":
        return actual is not None
    if op == "is_true":
        return bool(actual) is True
    if op == "is_false":
        return not bool(actual)
    if op == "equals":
        return actual == value
    if op == "not_equals":
        return actual != value
    if op == "contains":
        return isinstance(actual, str) and str(value).lower() in actual.lower()
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
        for r in matched:
            counts[r.get(group_count_by)] = counts.get(r.get(group_count_by), 0) + 1
        grouped = [{"value": v, "count": n} for v, n in counts.items()]
        grouped.sort(key=lambda g: g["count"], reverse=True)
        return grouped

    if unique_by:
        seen: set[Any] = set()
        deduped = []
        for r in matched:
            key = r.get(unique_by)
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        matched = deduped

    if sort_by:
        matched.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by)), reverse=(order == "desc"))

    matched = matched[: max(1, limit)]

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
