"""Freeze the set of modules that run or write the comms agent's conversation thread.

The comms graph checkpoints each conversation on a thread whose id is the
conversation id. Two writers on that thread at once fork it, and one side's
messages drop out of the model's memory. The conversation runtime step
(``app/services/conversation/step.py``) is the one owner; until every caller has
moved there, the callers that predate it sit in a shrink-only ``ALLOWLIST``.

Outside the builder package and the step, three checks:

1. R1: no reference to ``GraphName.COMMS``, and no ``"comms_agent"`` string passed
   to a graph lookup (``GraphManager.get_graph`` / ``providers.get`` / ``providers.aget``).
2. R2: no call to a comms entry wrapper or a comms thread writer (``COMMS_ENTRY_FUNCTIONS``).
3. R3: in a module that trips R1 or R2, no ``astream`` / ``ainvoke`` / state read or
   write call (``GRAPH_THREAD_METHODS``). Syntactic, not data flow: a graph handed to
   a module that names neither the symbol nor a wrapper is not seen.

An allowlisted file that no longer trips any check is reported as removable, as
is an entry whose file no longer exists.
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

COMMS_ENTRY_FUNCTIONS = frozenset(
    {
        # app/agents/core/agent.py: the chat and silent comms runs.
        "call_agent",
        "call_agent_silent",
        # app/agents/core/graph_builder/build_graph.py: the graph constructors.
        "build_comms_graph",
        "build_comms_agent",
        # app/agents/core/background/comms_narrator.py: the thread writers.
        "narrate_executor_result",
        "record_executor_report",
        "record_executor_cancellation",
        "record_platform_delivery",
        "record_exchange_in_thread",
        "_append_to_thread",
    }
)

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

# Paths relative to app/; a prefix ending in "/" allows a whole package.
_OWNERS = (
    "agents/core/graph_builder/",
    "services/conversation/step.py",
)

# Ratchet allowlist: the comms-thread callers that predate the conversation runtime
# step. Entries are only ever removed; a new caller goes through the step.
ALLOWLIST: frozenset[str] = frozenset(
    {
        # Fetches the comms graph and runs it for call_agent and call_agent_silent;
        # removed when the step takes this over (plan PR 7 for call_agent, PR 9 deletes call_agent_silent).
        "agents/core/agent.py",
        # Runs the interactive chat turn through call_agent; removed when the step takes this over (plan PR 7).
        "services/chat/stream.py",
        # Narrates executor results with a silent comms run and appends reports, cancellations,
        # platform deliveries and browser exchanges to the thread; removed when the step takes this over (plan PR 8).
        "agents/core/background/comms_narrator.py",
        # Narrates a finished executor result and records a platform delivery; removed when the step takes this over (plan PR 8).
        "agents/core/background/result_delivery.py",
        # Records and narrates a todo run's result; removed when the step takes this over (plan PR 8).
        "agents/core/background/todo_run_delivery.py",
        # Records a cancelled executor run in the thread; removed when the step takes this over (plan PR 8).
        "agents/core/background/executor_runner.py",
        # Records a workflow message posted to a platform; removed when the step takes this over (plan PR 8).
        "agents/core/background/workflow_platform_delivery.py",
        # Records a browser handoff button exchange; removed when the step takes this over (plan PR 8).
        "services/browser/handoff_buttons.py",
        # Runs a workflow as a chat turn through call_agent_silent; removed when the step takes this over (plan PR 9).
        "workers/tasks/workflow_tasks.py",
    }
)


def _app_split(path: Path) -> tuple[Path, str] | None:
    """Split a path into its ``app/`` package root and the path relative to it."""
    posix = path.as_posix()
    marker = "/app/"
    idx = posix.rfind(marker)
    if idx == -1:
        return None
    return Path(posix[: idx + len(marker)]), posix[idx + len(marker) :]


def _is_owner(app_rel: str) -> bool:
    return any(app_rel.startswith(o) if o.endswith("/") else app_rel == o for o in _OWNERS)


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
                hits.append(
                    (node.lineno, f"calls {wrapper}, which runs or writes the comms thread")
                )
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


def _allowlist_line(entry: str) -> int:
    for number, text in enumerate(Path(__file__).read_text(encoding="utf-8").splitlines(), 1):
        if f'"{entry}"' in text:
            return number
    return 1


def _stale(entry: str, reason: str) -> Violation:
    return Violation(
        path=Path(__file__),
        line=_allowlist_line(entry),
        detail=f"ALLOWLIST entry '{entry}' {reason}",
        fix="delete the entry; the allowlist only shrinks",
    )


def check(files: list[Path]) -> list[Violation]:
    """Flag comms-thread runs and writes outside the owners, plus allowlist entries that went stale."""
    violations: list[Violation] = []
    scanned: set[str] = set()
    app_roots: set[Path] = set()
    for path in files:
        split = _app_split(path)
        if split is None:
            continue
        app_root, app_rel = split
        app_roots.add(app_root)
        if _is_owner(app_rel):
            continue
        hits = _module_hits(ast.parse(path.read_text(encoding="utf-8")))
        if app_rel in ALLOWLIST:
            scanned.add(app_rel)
            if not hits:
                violations.append(_stale(app_rel, "no longer runs or writes the comms thread"))
            continue
        violations.extend(
            Violation(
                path=path,
                line=line,
                detail=detail,
                fix="run or write the conversation through app/services/conversation/step.py",
            )
            for line, detail in hits
        )
    for entry in sorted(ALLOWLIST - scanned):
        if app_roots and not any((root / entry).is_file() for root in app_roots):
            violations.append(_stale(entry, "names a file that no longer exists"))
    return violations
