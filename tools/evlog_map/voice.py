"""Voice adapter — the LiveKit entry points the voice worker registers.

Mirrors ``collect_worker_registry``: the wiring is parsed, never hardcoded.
``agent.py`` names the functions LiveKit invokes via the ``WorkerOptions``
call handed to ``cli.run_app`` (``entrypoint_fnc`` / ``prewarm_fnc``), and
``conversation.py`` supplies the per-turn hook: the session has no LLM, so
LiveKit calls ``on_user_turn_completed`` on the ``Agent`` subclass when the user
finishes speaking. That hook owns the ``wide_task`` boundary, so it is the entry
point, and deleting the boundary fails the scan instead of hiding from it.

The registry maps each module's resolved path to the qualified names
(``entrypoint``, ``VoiceTurnAgent.on_user_turn_completed``) that are voice entry
points there.
"""

from __future__ import annotations

import ast
from pathlib import Path

_WORKER_OPTIONS = "WorkerOptions"
_WORKER_OPTION_ENTRY_KWARGS = ("entrypoint_fnc", "prewarm_fnc")
_AGENT_BASE = "Agent"
_TURN_HOOK = "on_user_turn_completed"


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _worker_option_entries(agent_module: Path) -> frozenset[str]:
    """Return function names wired into ``WorkerOptions(entrypoint_fnc=…, prewarm_fnc=…)``."""
    tree = ast.parse(agent_module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_name(node) == _WORKER_OPTIONS):
            continue
        for kw in node.keywords:
            if kw.arg in _WORKER_OPTION_ENTRY_KWARGS and isinstance(kw.value, ast.Name):
                names.add(kw.value.id)
    if not names:
        raise ValueError(f"no {_WORKER_OPTIONS} wiring found in {agent_module} — registry moved?")
    return frozenset(names)


def _methods(cls: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        stmt.name: stmt
        for stmt in cls.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _turn_entries(turn_module: Path) -> frozenset[str]:
    """Qualified name of the per-turn hook in the turn module.

    The session has no LLM: LiveKit calls ``on_user_turn_completed`` on the ``Agent``
    subclass when the user finishes speaking, and that hook carries the per-turn
    wide-event boundary, so it is the scored entry point.
    """
    tree = ast.parse(turn_module.read_text(encoding="utf-8"))
    agent = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and _subclasses(node, _AGENT_BASE)
        ),
        None,
    )
    if agent is None:
        raise ValueError(f"no {_AGENT_BASE} subclass found in {turn_module} — turn hook moved?")
    if _TURN_HOOK not in _methods(agent):
        raise ValueError(f"{agent.name} in {turn_module} has no {_TURN_HOOK}() — turn hook moved?")
    return frozenset({f"{agent.name}.{_TURN_HOOK}"})


def _subclasses(cls: ast.ClassDef, base: str) -> bool:
    return any(isinstance(b, ast.Name) and b.id == base for b in cls.bases)


def collect_voice_registry(agent_module: Path, turn_module: Path) -> dict[str, frozenset[str]]:
    """Voice entry points per module: resolved path → qualified function names."""
    return {
        agent_module.resolve().as_posix(): _worker_option_entries(agent_module),
        turn_module.resolve().as_posix(): _turn_entries(turn_module),
    }
