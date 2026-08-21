"""Every ``model_dump()`` under ``app/agents/tools/`` must pass ``mode="json"``.

Issue #917: ``search_reminders_tool`` fed a python-mode dump to stdlib
``json.dumps`` and returned "Object of type datetime is not JSON serializable"
on every call; ``workflow_tool`` shipped the same crash in its stream-writer
payloads. Pydantic's two dump modes have opposite contracts — python mode keeps
native ``datetime`` objects (what Mongo writes need), JSON mode produces ISO
strings — and the modes differ by three invisible characters. Inside the agent
tools tree every dump crosses into model/SSE text, so there is exactly one
correct mode and the lint demands it explicitly instead of trusting review to
notice its absence.

Scope is deliberately the tools tree: service-layer dumps legitimately stay in
python mode because repositories persist them as BSON dates (the scheduler's
``$lte`` scans match on them). A tool that ever truly needs python objects can
compute them without crossing the serialization boundary.
"""

from __future__ import annotations

import ast
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


#: Sites that predate this rule, as ``<path>::<enclosing function>``. Empty on
#: purpose: the thirteen bare dumps that existed when the rule landed were all
#: fixed in the same PR (#917) — every one was a string-only payload where the
#: explicit mode changes nothing. This is a ratchet like the other lints': an
#: entry may be removed when its site is fixed, never added.
ALLOWLIST: frozenset[str] = frozenset()


def _calls_by_function(tree: ast.AST) -> list[tuple[ast.Call, str]]:
    """Every ``.model_dump(...)`` call paired with its enclosing function name."""
    found: list[tuple[ast.Call, str]] = []

    def walk(node: ast.AST, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, child.name)
            else:
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "model_dump"
                ):
                    found.append((child, enclosing))
                walk(child, enclosing)

    walk(tree, "<module>")
    return found


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        posix = path.as_posix()
        if _SCOPE_SEGMENT not in posix:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = posix[posix.index("app/") :]
        for node, enclosing in _calls_by_function(tree):
            if not _missing_json_mode(node):
                continue
            if f"{rel}::{enclosing}" in ALLOWLIST:
                continue
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    detail=(
                        'model_dump() without mode="json" — a python-mode dump keeps '
                        "native datetimes that are not JSON-safe at the tool boundary"
                    ),
                    fix=(
                        'pass mode="json" so datetime fields cross into model/stream '
                        "text as ISO strings. (Mongo-bound dumps belong in the "
                        "service/repository layer, not under app/agents/tools/.)"
                    ),
                )
            )
    return violations
