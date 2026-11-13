"""Voice adapter — the LiveKit entry points the voice worker registers.

Mirrors ``collect_worker_registry``: the wiring is parsed, never hardcoded.
``agent.py`` names the functions LiveKit invokes via the ``WorkerOptions``
call handed to ``cli.run_app`` (``entrypoint_fnc`` / ``prewarm_fnc``), and
``llm.py`` supplies the per-turn coroutine: LiveKit calls ``chat()`` on the
``LLM`` subclass, which returns an ``LLMStream`` subclass whose ``_run`` LiveKit
drives as the turn's task. That coroutine owns the ``wide_task`` boundary, so it
is the entry point, and deleting the boundary fails the scan instead of hiding
from it.

The registry maps each module's resolved path to the qualified names
(``entrypoint``, ``_VoiceStream._run``) that are voice entry points there.
"""

from __future__ import annotations

import ast
from pathlib import Path

_WORKER_OPTIONS = "WorkerOptions"
_WORKER_OPTION_ENTRY_KWARGS = ("entrypoint_fnc", "prewarm_fnc")
_LLM_BASE = "LLM"
_LLM_TURN_METHOD = "chat"
_STREAM_BASE = "LLMStream"
_STREAM_TURN_METHOD = "_run"


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


def _turn_entries(llm_module: Path) -> frozenset[str]:
    """Qualified name(s) of the per-turn coroutine in the LLM adapter module.

    LiveKit invokes ``chat()`` on the ``LLM`` subclass and drives ``_run`` on the
    ``LLMStream`` subclass it returns; that ``_run`` carries the per-turn wide-event
    boundary, so it is the scored entry point. When ``chat`` builds no same-file
    stream, ``chat`` itself is the entry point.
    """
    tree = ast.parse(llm_module.read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    llm_class = next((cls for cls in classes.values() if _subclasses(cls, _LLM_BASE)), None)
    if llm_class is None:
        raise ValueError(f"no {_LLM_BASE} subclass found in {llm_module} — adapter moved?")
    chat = _methods(llm_class).get(_LLM_TURN_METHOD)
    if chat is None:
        raise ValueError(f"{llm_class.name} in {llm_module} has no {_LLM_TURN_METHOD}() method")

    streams = {
        name
        for node in ast.walk(chat)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and (name := node.func.id) in classes
        and _subclasses(classes[name], _STREAM_BASE)
        and _STREAM_TURN_METHOD in _methods(classes[name])
    }
    entries = {f"{name}.{_STREAM_TURN_METHOD}" for name in streams}
    return frozenset(entries) if entries else frozenset({f"{llm_class.name}.{_LLM_TURN_METHOD}"})


def _subclasses(cls: ast.ClassDef, base: str) -> bool:
    return any(isinstance(b, ast.Name) and b.id == base for b in cls.bases)


def collect_voice_registry(agent_module: Path, llm_module: Path) -> dict[str, frozenset[str]]:
    """Voice entry points per module: resolved path → qualified function names."""
    return {
        agent_module.resolve().as_posix(): _worker_option_entries(agent_module),
        llm_module.resolve().as_posix(): _turn_entries(llm_module),
    }
