"""Voice adapter — the LiveKit entry points the voice worker registers.

Mirrors ``collect_worker_registry``: the wiring is parsed, never hardcoded.
``agent.py`` names the functions LiveKit invokes via the ``WorkerOptions``
call handed to ``cli.run_app`` (``entrypoint_fnc`` / ``prewarm_fnc``), and
``llm.py`` supplies the per-turn coroutine: LiveKit calls ``chat()`` on the
``LLM`` subclass, which delegates each turn to a helper class whose driven
coroutine owns the ``wide_task`` boundary — that coroutine is the entry
point, so deleting the boundary fails the scan instead of hiding from it.

The registry maps each module's resolved path to the qualified names
(``entrypoint``, ``_VoiceTurn.run``) that are voice entry points there.
"""

from __future__ import annotations

import ast
from pathlib import Path

_WORKER_OPTIONS = "WorkerOptions"
_WORKER_OPTION_ENTRY_KWARGS = ("entrypoint_fnc", "prewarm_fnc")
_LLM_BASE = "LLM"
_LLM_TURN_METHOD = "chat"


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _worker_option_entries(agent_module: Path) -> frozenset[str]:
    """Function names wired into ``WorkerOptions(entrypoint_fnc=…, prewarm_fnc=…)``."""
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

    LiveKit invokes ``chat()`` on the ``LLM`` subclass; the turn itself runs in
    a same-file helper class (``chat`` instantiates it and drives one of its
    coroutines). That driven coroutine carries the per-turn wide-event
    boundary, so it is the scored entry point. When ``chat`` delegates to no
    helper class, ``chat`` itself is the entry point.
    """
    tree = ast.parse(llm_module.read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    llm_class = next(
        (
            cls
            for cls in classes.values()
            if any(isinstance(base, ast.Name) and base.id == _LLM_BASE for base in cls.bases)
        ),
        None,
    )
    if llm_class is None:
        raise ValueError(f"no {_LLM_BASE} subclass found in {llm_module} — adapter moved?")
    chat = _methods(llm_class).get(_LLM_TURN_METHOD)
    if chat is None:
        raise ValueError(f"{llm_class.name} in {llm_module} has no {_LLM_TURN_METHOD}() method")

    instantiated: set[str] = set()
    called_attrs: set[str] = set()
    for node in ast.walk(chat):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if isinstance(node.func, ast.Name) and name in classes and name != llm_class.name:
            instantiated.add(name)
        elif isinstance(node.func, ast.Attribute) and name:
            called_attrs.add(name)

    entries = {
        f"{cls_name}.{method}"
        for cls_name in sorted(instantiated)
        for method in _methods(classes[cls_name])
        if method in called_attrs
    }
    return frozenset(entries) if entries else frozenset({f"{llm_class.name}.{_LLM_TURN_METHOD}"})


def collect_voice_registry(agent_module: Path, llm_module: Path) -> dict[str, frozenset[str]]:
    """Voice entry points per module: resolved path → qualified function names."""
    return {
        agent_module.resolve().as_posix(): _worker_option_entries(agent_module),
        llm_module.resolve().as_posix(): _turn_entries(llm_module),
    }
