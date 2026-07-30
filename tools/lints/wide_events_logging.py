"""App code logs through wide events, not the stdlib ``logging`` or bare loguru.

``apps/api/CLAUDE.md`` -> Code Style: structured logging uses
``from shared.py.wide_events import log``. That wrapper is what emits one
context-rich canonical event per request; a module that reaches for stdlib
``logging`` or imports ``loguru`` directly bypasses it and its output never joins
the wide event, so it is invisible to the per-request Loki/Grafana queries.

This flags ``import logging`` / ``from logging import ...`` and direct ``loguru``
imports anywhere under ``app/``. The app is already fully migrated, so the
``ALLOWLIST`` holds the single legitimate exception (the loguru -> Sentry sink
bridge). Ratchet: remove entries as they are fixed, never add one.

It also flags ``log.set(...)`` / ``log.set_ns(...)`` / ``log.bind(...)`` calls
that pass a reserved keyword — the JSON sink's core keys (time, level, message,
logger, module, line, worker). The sink runtime-guards collisions by re-emitting
them as ``ctx_<key>``, so a reserved key never lands where the caller expects;
this catches the mistake at commit instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "wide-events-logging"
WHY = (
    "stdlib logging / bare loguru bypasses the wide-event wrapper, so those lines never join "
    "the per-request canonical event; reserved keys passed to log.set()/set_ns()/bind() collide "
    "with the JSON line's core fields and are re-emitted as ctx_<key> instead of where expected"
)
DOC = "tools/lints/README.md#wide-events-logging"

_BANNED_MODULES = frozenset({"logging", "loguru"})

_WIDE_EVENTS_MODULE = "shared.py.wide_events"
_EVENT_SETTER_METHODS = frozenset({"set", "set_ns", "bind"})
# The JSON sink's top-level keys (see _CORE_KEYS in libs/shared/py/logging.py).
_RESERVED_EVENT_KEYS = frozenset({"time", "level", "message", "logger", "module", "line", "worker"})

# Ratchet allowlist of path suffixes that legitimately use loguru/logging
# directly. Remove an entry when it is migrated; never add one.
ALLOWLIST_SUFFIXES: tuple[str, ...] = (
    # Configures the loguru -> Sentry sink; it is logging infrastructure, not
    # app logging, and must touch loguru directly to install the sink.
    "app/config/sentry.py",
)


def _banned_import_lines(tree: ast.Module) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _BANNED_MODULES:
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            # level > 0 is a relative import (e.g. `from .logging import ...`),
            # which resolves to a local module, never stdlib logging/loguru.
            root = node.module.split(".")[0]
            if root in _BANNED_MODULES:
                hits.append((node.lineno, f"from {node.module} import ..."))
    return hits


def _wide_event_log_aliases(tree: ast.Module) -> frozenset[str]:
    """Names the wide-event facade is imported as (``log``, or an alias)."""
    aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == _WIDE_EVENTS_MODULE
        for alias in node.names
        if alias.name == "log"
    }
    return frozenset(aliases)


def _reserved_key_calls(tree: ast.Module) -> list[tuple[int, str]]:
    aliases = _wide_event_log_aliases(tree)
    if not aliases:
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = node.func
        if func.attr not in _EVENT_SETTER_METHODS:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
            continue
        reserved = sorted(kw.arg for kw in node.keywords if kw.arg in _RESERVED_EVENT_KEYS)
        if reserved:
            hits.append((node.lineno, f"{func.value.id}.{func.attr}({', '.join(reserved)}=...)"))
    return hits


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        posix = path.as_posix()
        if "/app/" not in posix:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if not any(posix.endswith(suffix) for suffix in ALLOWLIST_SUFFIXES):
            for line, detail in _banned_import_lines(tree):
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        detail=f"logs outside wide events ({detail})",
                        fix="replace with `from shared.py.wide_events import log` and use log.set()/log.info()/log.error()",
                    )
                )
        for line, detail in _reserved_key_calls(tree):
            violations.append(
                Violation(
                    path=path,
                    line=line,
                    detail=f"reserved wide-event key ({detail})",
                    fix="rename the field to a domain-specific name — time/level/message/logger/module/line/worker are the JSON line's core keys, and the sink re-emits collisions as ctx_<key>",
                )
            )
    return violations
