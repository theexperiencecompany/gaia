"""A broad ``except`` may not swallow the failure and substitute an empty value.

``CLAUDE.md`` -> "Fail loud — never swallow errors or add silent fallbacks": a
masked error is a bug that resurfaces somewhere worse, later. The shape this
catches is the one that has actually shipped here more than once:

    except Exception:
        return []          # caller cannot tell "none found" from "search died"

Notification search returned an empty list for a total backend failure and
rendered as an empty inbox; a swallowed ``AttributeError`` did the same thing
one layer down. Both looked exactly like "no results" to every caller.

Scope is deliberately narrower than ruff's BLE001 (1001 findings, mostly benign
top-level safety nets). A handler is only reported when *all* of these hold:

1. it catches ``Exception``/``BaseException``/bare — a targeted ``except
   KeyError`` is a decision, not a blanket;
2. nothing in it logs, re-raises, or otherwise reports — that is what makes it
   *silent*;
3. it returns a falsy stand-in (``None``/``False``/``0``/``""``/``[]``/``{}``)
   or falls out of the handler, so the caller receives "nothing" and cannot
   distinguish it from a real empty result.

A handler that logs is fine. A handler that re-raises is fine. A handler that
returns a real value is fine. Only silence plus a fake answer is banned.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "no-silent-fallback"
WHY = (
    "a broad except that logs nothing and returns an empty value makes a total failure "
    "indistinguishable from 'no results' at every call site"
)
DOC = "tools/lints/README.md#no-silent-fallback"

#: Names that mean "the failure was reported". Includes the stdlib/loguru levels
#: and the wide-events methods, plus reporting wrappers this codebase defines
#: (``self._fail`` on the model catalog is a real one — matching only on level
#: names produced a false positive there).
_REPORTING_NAMES = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "log",
        "set",
        "set_ns",
        "print",
        "capture_exception",
        "capture_message",
    }
)

#: Substring test for project-defined reporting helpers (``_fail``, ``_report_error``).
_REPORTING_SUBSTRINGS = ("fail", "report", "notify", "alert", "track", "record")


def _is_broad(handler: ast.ExceptHandler) -> bool:
    node = handler.type
    if node is None:
        return True
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Tuple):
        return any(
            isinstance(e, ast.Name) and e.id in {"Exception", "BaseException"} for e in node.elts
        )
    return False


def _reports_or_reraises(handler: ast.ExceptHandler) -> bool:
    """True when the handler makes the failure observable to someone."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Raise):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if not name:
                continue
            lowered = name.lower()
            if name in _REPORTING_NAMES or any(s in lowered for s in _REPORTING_SUBSTRINGS):
                return True
    return False


def _empty_substitute(handler: ast.ExceptHandler) -> str | None:
    """Describe the falsy stand-in this handler hands back, if any."""
    for node in ast.walk(handler):
        if isinstance(node, ast.Return):
            value = node.value
            if value is None:
                return "returns None implicitly"
            if isinstance(value, ast.Constant) and (
                value.value is None or value.value is False or value.value in ("", 0)
            ):
                return f"returns {value.value!r}"
            if isinstance(value, ast.List | ast.Tuple) and not value.elts:
                return "returns an empty sequence"
            if isinstance(value, ast.Dict) and not value.keys:
                return "returns an empty dict"
            if isinstance(value, ast.Call):
                func = value.func
                if isinstance(func, ast.Name) and func.id in {"list", "dict", "set", "tuple"}:
                    if not value.args:
                        return f"returns an empty {func.id}()"
    return None


#: Handlers that predate this rule, as ``<path>::<enclosing function>``. Keyed by
#: function rather than line number so an unrelated edit above the handler does
#: not invalidate the entry and fire a false alarm. Each is a
#: probe or parse whose falsy result is arguably the honest answer for *some*
#: failures, but which currently swallows every failure to say it. This is a
#: ratchet like the one in ``no_service_classes``: remove an entry when the site
#: is fixed (log the cause, or catch the specific exception that means "no"),
#: never add one. The four with user-visible consequences — Dodo payment and
#: subscription payloads, the context-usage estimate that gates compaction, and
#: the workflow-generating flag — were fixed rather than listed here.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Connectivity/health probes: False genuinely means "not usable", but an
        # auth or permission error is currently indistinguishable from "down".
        "app/db/rabbitmq.py::is_connected",
        "app/services/sandbox/lifecycle.py::_health_probe",
        "app/services/storage/juicefs.py::_check",
        "app/services/storage/system_workspace.py::system_subtree_available",
        # Parse/lookup helpers where the falsy result means "not valid / not
        # found", but the except is broader than the failure it describes.
        "app/utils/timezone.py::try_parse",
        "app/utils/mcp_oauth_utils.py::is_localhost_url",
        "app/services/sandbox/lifecycle.py::_read_canary",
        "app/services/integrations/custom_crud.py::_fetch_icon_safely",
        # Best-effort side paths (stream writer outside a stream, sandbox artifact
        # enumeration) that bail without recording why.
        "app/agents/tools/coding/_context.py::safe_emit",
        "app/agents/tools/coding/bash_tool.py::_publish_artifacts",
    }
)


def _handlers_by_function(tree: ast.AST) -> list[tuple[ast.ExceptHandler, str]]:
    """Every except handler paired with the name of the function containing it."""
    found: list[tuple[ast.ExceptHandler, str]] = []

    def walk(node: ast.AST, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                walk(child, child.name)
            else:
                if isinstance(child, ast.ExceptHandler):
                    found.append((child, enclosing))
                walk(child, enclosing)

    walk(tree, "<module>")
    return found


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        posix = path.as_posix()
        rel = posix[posix.index("app/") :] if "app/" in posix else posix
        for node, enclosing in _handlers_by_function(tree):
            if not _is_broad(node) or _reports_or_reraises(node):
                continue
            substitute = _empty_substitute(node)
            if substitute is None:
                continue
            if f"{rel}::{enclosing}" in ALLOWLIST:
                continue
            violations.append(
                Violation(
                    path=path,
                    line=node.lineno,
                    detail=f"broad except logs nothing and {substitute}",
                    fix=(
                        "log why it failed before returning the fallback, or let the "
                        "exception propagate. If the empty value is genuinely the right "
                        "answer, catch the specific exception that means that instead of "
                        "Exception."
                    ),
                )
            )
    return violations
