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
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "wide-events-logging"
WHY = "stdlib logging / bare loguru bypasses the wide-event wrapper, so those lines never join the per-request canonical event"
DOC = "tools/lints/README.md#wide-events-logging"

_BANNED_MODULES = frozenset({"logging", "loguru"})

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


def check(files: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        posix = path.as_posix()
        if "/app/" not in posix:
            continue
        if any(posix.endswith(suffix) for suffix in ALLOWLIST_SUFFIXES):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, detail in _banned_import_lines(tree):
            violations.append(
                Violation(
                    path=path,
                    line=line,
                    detail=f"logs outside wide events ({detail})",
                    fix="replace with `from shared.py.wide_events import log` and use log.set()/log.info()/log.error()",
                )
            )
    return violations
