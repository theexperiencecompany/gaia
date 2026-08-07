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
this catches the mistake at commit instead. Only setters whose keywords land at
the JSON top level are checked: ``set_ns`` merges its kwargs under the namespace
(sub-keys can safely be named ``level`` etc.), so only its namespace argument is
a top-level write.

Finally it flags emit calls (``log.info`` / ``log.error`` / ...) whose message is
an f-string that interpolates data. A wide-event message is an identifier, not a
sentence: grouping, alerting and Loki queries all key off the literal string, so
``f"upload failed for {user_id}"`` shards one event into as many distinct messages
as there are users and the data lands nowhere queryable. The only interpolation a
message may carry is the leading ``{LogTag.X}`` prefix; everything else belongs in
structured kwargs (``error_type=type(e).__name__``, ``user_id=...``).
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import Violation

RULE = "wide-events-logging"
WHY = (
    "stdlib logging / bare loguru bypasses the wide-event wrapper, so those lines never join "
    "the per-request canonical event; reserved keys passed to log.set()/set_ns()/bind() collide "
    "with the JSON line's core fields and are re-emitted as ctx_<key> instead of where expected, "
    "and passing one to an emit call (log.warning(message=...)) is a TypeError that kills the "
    "process the moment that branch runs; "
    "data interpolated into a message shards one event into thousands of unqueryable strings"
)
DOC = "tools/lints/README.md#wide-events-logging"

_BANNED_MODULES = frozenset({"logging", "loguru"})

_WIDE_EVENTS_MODULE = "shared.py.wide_events"
_EVENT_SETTER_METHODS = frozenset({"set", "set_ns", "bind"})
_EMIT_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical", "audit"})
# The one interpolation a message may carry: a leading `{LogTag.X}` prefix.
_LOG_TAG_NAME = "LogTag"
# The JSON sink's top-level keys (see _CORE_KEYS in libs/shared/py/logging.py).
_RESERVED_EVENT_KEYS = frozenset(
    {
        # Core keys of the emitted JSON line (see shared.py.logging).
        "time",
        "level",
        "message",
        "logger",
        "module",
        "line",
        "worker",
        # Infra identity stamped by env_context(); `service` must equal the
        # Promtail label for the process, so app code may not set it.
        "env",
        "service",
        "commit",
    }
)

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
        # Emit methods are checked too, and for a harsher reason than setters:
        # `message` is their first positional parameter, so `log.warning(tag,
        # message=...)` is not a silent collision but a TypeError that takes the
        # process down when that branch runs. Two of these shipped and broke
        # startup while the whole test suite stayed green.
        if func.attr not in _EVENT_SETTER_METHODS | _EMIT_METHODS:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
            continue
        # set_ns keywords merge UNDER the namespace — only the namespace
        # argument itself is a top-level write, so it is the sole collision
        # candidate (and only when it is a literal that can be compared).
        if func.attr == "set_ns":
            namespace = (
                node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else None
            )
            reserved = [str(namespace)] if namespace in _RESERVED_EVENT_KEYS else []
        else:
            reserved = sorted(kw.arg for kw in node.keywords if kw.arg in _RESERVED_EVENT_KEYS)
        if reserved:
            hits.append((node.lineno, f"{func.value.id}.{func.attr}({', '.join(reserved)}=...)"))
    return hits


def _is_log_tag_prefix(node: ast.FormattedValue) -> bool:
    """True for ``{LogTag.X}`` — the one interpolation a message may carry."""
    value = node.value
    return (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == _LOG_TAG_NAME
    )


def _interpolated_message_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """Emit calls whose message f-string interpolates anything but the LogTag prefix."""
    aliases = _wide_event_log_aliases(tree)
    if not aliases:
        return []
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = node.func
        if func.attr not in _EMIT_METHODS:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id in aliases):
            continue
        if not (node.args and isinstance(node.args[0], ast.JoinedStr)):
            continue
        message = node.args[0]
        offenders = [
            ast.unparse(part.value)
            for index, part in enumerate(message.values)
            if isinstance(part, ast.FormattedValue)
            and not (index == 0 and _is_log_tag_prefix(part))
        ]
        if offenders:
            rendered = ", ".join(f"{{{expr}}}" for expr in offenders)
            hits.append((node.lineno, f'{func.value.id}.{func.attr}(f"... {rendered} ...")'))
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
        for line, detail in _interpolated_message_calls(tree):
            violations.append(
                Violation(
                    path=path,
                    line=line,
                    detail=f"data interpolated into the log message ({detail})",
                    fix='keep the message a constant string (only a leading f"{LogTag.X} " prefix is allowed) and move the data to kwargs — log.error(f"{LogTag.X} upload failed", error_type=type(e).__name__, user_id=user_id)',
                )
            )
    return violations
