"""Route handlers must call ``log.set`` (the 3-step contract's mechanical core).

Every FastAPI handler in ``app/api/v1/endpoints/`` follows a 3-step contract
(see ``apps/api/CLAUDE.md`` -> "FastAPI — Route Handlers"): ``log.set()`` with
what is known at entry, delegate to a service, ``log.set()`` the result. The
mechanically-checkable core is step 1: a handler with no ``log.set`` call emits a
request with no canonical wide-event context, which is invisible in Loki/Grafana.

This rule flags any ``@router.<method>`` handler whose body never calls
``log.set(...)``. The ``ALLOWLIST`` grandfathers the handlers that predate the
lint; it is a ratchet — entries may be removed as they are fixed, never added.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from _common import Violation

RULE = "route-contract"
WHY = "handlers with no log.set emit a request with no wide-event context (blind in Loki/Grafana)"
DOC = "tools/lints/README.md#route-contract"

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "websocket"}

# Ratchet allowlist of (endpoint-file basename, handler function name) pairs that
# predate the lint. Grouped by why they legitimately (or provisionally) skip
# log.set. Remove an entry once its handler adopts the contract — never add one.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        # Infra endpoints with no user/operation context to record.
        ("health.py", "health_check"),
        ("health.py", "favicon"),
    }
)


def _route_methods(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """HTTP methods this function is registered under via ``@<router>.<method>``."""
    methods: set[str] = set()
    for deco in func.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute) and target.attr in _HTTP_METHODS:
            methods.add(target.attr)
    return methods


def _iter_own_scope(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """Yield the handler's own nodes, stopping at nested scopes.

    A `log.set()` inside a nested function/class/lambda must not satisfy the
    handler's contract — only calls the handler itself makes count.
    """
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.append(child)


def _calls_log_set(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in _iter_own_scope(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "log"
        ):
            return True
    return False


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        if "/api/v1/endpoints/" not in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods = _route_methods(node)
            if not methods:
                continue
            if (path.name, node.name) in ALLOWLIST:
                continue
            if _calls_log_set(node):
                continue
            verb = "/".join(sorted(methods)).upper()
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    detail=f"{verb} handler '{node.name}' never calls log.set(...)",
                    fix=(
                        f"add `log.set(...)` at the top of '{node.name}' with the user/"
                        "operation/IDs known at entry (step 1 of the 3-step contract)"
                    ),
                )
            )
    return violations
