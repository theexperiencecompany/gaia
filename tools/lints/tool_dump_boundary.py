"""Every ``model_dump()`` under ``app/agents/tools/`` must pass ``mode="json"``.

Issue #917: ``search_reminders_tool`` fed a python-mode dump to stdlib
``json.dumps`` and returned "Object of type datetime is not JSON serializable"
on every call, while ``workflow_tool`` shipped the same crash in its
stream-writer payloads. Pydantic's two dump modes have opposite contracts —
python mode keeps native ``datetime`` objects (the Mongo write path needs them),
JSON mode produces ISO strings — and the modes differ by three invisible
characters at the call site. Inside the agent tools tree every dump crosses into
model/SSE text, so there is exactly one correct mode and the lint demands it
explicitly instead of trusting review to notice its absence.

Scope is deliberately the tools tree: service-layer dumps legitimately stay in
python mode because repositories persist them as BSON dates (the scheduler's
``$lte`` recovery scans match on them). A tool that ever truly needs python
objects can compute them without crossing the serialization boundary.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from _common import Violation

RULE = "tool-dump-boundary"
WHY = (
    "a python-mode model_dump() keeps native datetime objects, which crash stdlib "
    "json.dumps and degrade to Python reprs in agent/stream text — issue #917"
)
DOC = "tools/lints/README.md#tool-dump-boundary"

_SCOPE_SEGMENT = "/app/agents/tools/"


def _missing_json_mode(call: ast.Call) -> bool:
    """True when the dump call does not pin ``mode="json"`` literally."""
    for kw in call.keywords:
        if kw.arg == "mode":
            return not (isinstance(kw.value, ast.Constant) and kw.value.value == "json")
    return True


#: Bare ``model_dump()`` sites that predate this rule, as
#: ``<path>::<enclosing function>`` mapped to the audited count of exempt calls
#: in that function. Every model dumped at these sites was verified string-only
#: by the #917 audit (``ImageData``, ``SearchResultItem``/``WebSearchResult``,
#: the calendar wire models, ``TodoLabelCount``), so both dump modes produce
#: identical output — flipping them is unobservable, which is also why the
#: mutation gate rejects the flip as untestable.
#:
#: The COUNT is the ratchet, not just the entry: a new bare dump added to an
#: allowlisted function pushes its count past the audited number and is
#: reported, so a historical exemption can never absorb new code. Remove or
#: lower an entry when its site takes ``mode="json"``; never raise one.
ALLOWLIST: dict[str, int] = {
    "app/agents/tools/image_tool.py::generate_image": 1,
    "app/agents/tools/webpage_tool.py::web_search_tool": 2,
    "app/agents/tools/integrations/calendar_tool.py::CUSTOM_LIST_CALENDARS": 2,
    "app/agents/tools/integrations/calendar_tool.py::CUSTOM_GET_DAY_SUMMARY": 3,
    "app/agents/tools/integrations/calendar_tool.py::CUSTOM_FETCH_EVENTS": 2,
    "app/agents/tools/integrations/calendar_tool.py::CUSTOM_FIND_EVENT": 2,
    "app/agents/tools/todo_tool.py::get_all_labels": 1,
}


def _calls_by_function(tree: ast.AST) -> list[tuple[ast.Call, str]]:
    """Every ``.model_dump(...)`` call paired with its enclosing function name."""

    def walk(node: ast.AST, enclosing: str) -> list[tuple[ast.Call, str]]:
        found: list[tuple[ast.Call, str]] = []
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                found.extend(walk(child, child.name))
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "model_dump"
            ):
                found.append((child, enclosing))
            found.extend(walk(child, enclosing))
        return found

    return walk(tree, "<module>")


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        posix = path.as_posix()
        if _SCOPE_SEGMENT not in posix:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = posix[posix.index("app/") :]

        bare_by_function: dict[str, list[ast.Call]] = defaultdict(list)
        for node, enclosing in _calls_by_function(tree):
            if _missing_json_mode(node):
                bare_by_function[f"{rel}::{enclosing}"].append(node)

        for key, calls in bare_by_function.items():
            allowed = ALLOWLIST.get(key, 0)
            excess = calls[allowed:]
            if not excess:
                continue
            detail = (
                'model_dump() without mode="json" — a python-mode dump keeps native '
                "datetimes that are not JSON-safe at the tool boundary"
            )
            if allowed:
                detail = (
                    f"{len(excess)} bare model_dump() call(s) beyond the {allowed} "
                    f"grandfathered for this function"
                )
            violations.append(
                Violation(
                    path=path,
                    line=excess[0].lineno,
                    detail=detail,
                    fix=(
                        'pass mode="json" so datetime fields cross into model/stream '
                        "text as ISO strings. (Mongo-bound dumps belong in the "
                        "service/repository layer, not under app/agents/tools/.)"
                    ),
                )
            )
    return violations
