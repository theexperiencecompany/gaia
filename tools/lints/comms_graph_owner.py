"""Freeze the set of modules that run or write the comms agent's conversation thread.

The comms graph checkpoints each conversation on a thread whose id is the
conversation id. Two writers on that thread at once fork it, and one side's
messages drop out of the model's memory. The conversation runtime's comms runner
(``OWNER``, which the step drives) is the one owner.

Outside the owner and the builder package (``GRAPH_BUILDERS``, which constructs and
registers the graph but runs no conversation on it), three checks:

1. R1: no reference to ``GraphName.COMMS``, and no ``"comms_agent"`` string passed
   to a graph lookup (``GraphManager.get_graph`` / ``providers.get`` / ``providers.aget``).
2. R2: no call to a comms graph constructor (``COMMS_ENTRY_FUNCTIONS``).
3. R3: in a module that trips R1 or R2, no ``astream`` / ``ainvoke`` / state read or
   write call (``GRAPH_THREAD_METHODS``). Syntactic, not data flow: a graph handed to
   a module that names neither the symbol nor a constructor is not seen.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "comms-graph-owner"
WHY = "two writers on one conversation's comms thread fork it and drop messages from the model's memory"
DOC = "tools/lints/README.md#comms-graph-owner"

COMMS_GRAPH_SYMBOL = "GraphName"
COMMS_GRAPH_MEMBER = "COMMS"
COMMS_GRAPH_NAME = "comms_agent"
_GRAPH_LOOKUPS = frozenset({"get_graph"})
_PROVIDER_LOOKUPS = frozenset({"get", "aget"})
_PROVIDER_REGISTRY = "providers"

# app/agents/core/graph_builder/build_graph.py: the graph constructors.
COMMS_ENTRY_FUNCTIONS = frozenset({"build_comms_graph", "build_comms_agent"})

GRAPH_THREAD_METHODS = frozenset(
    {
        "astream",
        "astream_events",
        "ainvoke",
        "aget_state",
        "aget_state_history",
        "aupdate_state",
        "abulk_update_state",
    }
)

# Paths relative to app/. The one module that runs and writes the comms thread.
OWNER = "services/conversation/comms_runner.py"
# The package that constructs and registers the comms graph; it runs no conversation.
GRAPH_BUILDERS = "agents/core/graph_builder/"
_FIX = f"run or write the conversation through app/{OWNER}, driven by the conversation step"


def _app_relative(path: Path) -> str | None:
    """Return the path relative to its ``app/`` package, or None outside one."""
    posix = path.as_posix()
    marker = "/app/"
    idx = posix.rfind(marker)
    return None if idx == -1 else posix[idx + len(marker) :]


def _is_owner(app_rel: str) -> bool:
    return app_rel == OWNER or app_rel.startswith(GRAPH_BUILDERS)


def _is_comms_member(node: ast.Attribute) -> bool:
    value = node.value
    named = value.id if isinstance(value, ast.Name) else getattr(value, "attr", None)
    return node.attr == COMMS_GRAPH_MEMBER and named == COMMS_GRAPH_SYMBOL


def _is_graph_lookup(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in _GRAPH_LOOKUPS
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in _GRAPH_LOOKUPS:
        return True
    target = func.value
    return (
        func.attr in _PROVIDER_LOOKUPS
        and isinstance(target, ast.Name)
        and target.id == _PROVIDER_REGISTRY
    )


def _names_comms_by_string(call: ast.Call) -> bool:
    args = [*call.args[:1], *(kw.value for kw in call.keywords if kw.arg == "graph_name")]
    return any(isinstance(a, ast.Constant) and a.value == COMMS_GRAPH_NAME for a in args)


def _wrapper_aliases(tree: ast.Module) -> dict[str, str]:
    """Map every local name bound to a comms entry function to that function's name."""
    aliases = {name: name for name in COMMS_ENTRY_FUNCTIONS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in COMMS_ENTRY_FUNCTIONS and alias.asname:
                    aliases[alias.asname] = alias.name
    return aliases


def _called_wrapper(func: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(func, ast.Name):
        return aliases.get(func.id)
    if isinstance(func, ast.Attribute) and func.attr in COMMS_ENTRY_FUNCTIONS:
        return func.attr
    return None


def _ownership_hits(tree: ast.Module) -> list[tuple[int, str]]:
    """R1 and R2: (line, detail) for each place the module names or enters the comms graph."""
    aliases = _wrapper_aliases(tree)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_comms_member(node):
            hits.append((node.lineno, f"names the comms graph ({COMMS_GRAPH_SYMBOL}.COMMS)"))
        elif isinstance(node, ast.Call):
            if _is_graph_lookup(node.func) and _names_comms_by_string(node):
                hits.append(
                    (node.lineno, f'looks up the comms graph by name ("{COMMS_GRAPH_NAME}")')
                )
            wrapper = _called_wrapper(node.func, aliases)
            if wrapper is not None:
                hits.append((node.lineno, f"calls {wrapper}, which builds the comms graph"))
    return hits


def _thread_method_hits(tree: ast.Module) -> list[tuple[int, str]]:
    """R3: (line, detail) for each graph run or state call in a module that holds the comms graph."""
    return [
        (node.lineno, f"calls .{node.func.attr}() in a module that holds the comms graph")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in GRAPH_THREAD_METHODS
    ]


def _module_hits(tree: ast.Module) -> list[tuple[int, str]]:
    ownership = _ownership_hits(tree)
    if not ownership:
        return []
    return sorted([*ownership, *_thread_method_hits(tree)])


def check(files: list[Path]) -> list[Violation]:
    """Flag comms-thread runs and writes outside the owner."""
    violations: list[Violation] = []
    for path in files:
        app_rel = _app_relative(path)
        if app_rel is None or _is_owner(app_rel):
            continue
        violations.extend(
            Violation(path=path, line=line, detail=detail, fix=_FIX)
            for line, detail in _module_hits(ast.parse(path.read_text(encoding="utf-8")))
        )
    return violations
