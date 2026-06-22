"""Greppable log-line prefixes.

A single registry of bracketed, uppercase tags prepended to real-time log
messages (``log.info`` / ``log.warning`` / ``log.error`` / ``log.debug``) so one
subsystem's activity can be filtered with a single token — ``grep '\\[SANDBOX\\]'``
locally or ``|= "[SANDBOX]"`` in LogQL.

This is the cross-cutting counterpart to ``FsOps`` (which centralizes latency-
metric op names): one canonical home so prefixes never drift or collide across
files. Add a subsystem's tag here, then prefix that subsystem's log lines with
it — never inline a bare ``"[foo]"`` literal at the call site.

A tag annotates the human-readable *message*. Structured business context still
belongs in ``log.set(...)`` wide-event fields (see the ``*Context`` TypedDicts in
``shared.py.wide_events``), not in the prefix.
"""

from __future__ import annotations

from typing import Final


class LogTag:
    """Stable, greppable prefixes for real-time log lines, one per subsystem."""

    # --- Agent runtime ---
    AGENT: Final[str] = "[AGENT]"  # agents/core, middleware, llm, prompts, workspace
    TOOL: Final[str] = "[TOOL]"  # agents/tools/* (generic; specific tools below)
    MEMORY: Final[str] = "[MEMORY]"  # agents/memory + memory tools/services
    SKILLS: Final[str] = "[SKILLS]"  # agents/skills

    # --- Coding sandbox subsystem ---
    SANDBOX: Final[str] = "[SANDBOX]"
    ARTIFACT_WATCHER: Final[str] = "[ARTIFACT-WATCHER]"

    # --- External integrations ---
    MCP: Final[str] = "[MCP]"  # services/mcp
    INTEGRATION: Final[str] = "[INTEGRATION]"  # services/integrations
    OAUTH: Final[str] = "[OAUTH]"  # services/oauth
    COMPOSIO: Final[str] = "[COMPOSIO]"  # services/composio, utils/composio_hooks
    TRIGGER: Final[str] = "[TRIGGER]"  # services/triggers
    MAIL: Final[str] = "[MAIL]"  # services/mail

    # --- Product domains ---
    CHAT: Final[str] = "[CHAT]"  # services/chat
    WORKFLOW: Final[str] = "[WORKFLOW]"  # services/workflow, system_workflows, utils
    ONBOARDING: Final[str] = "[ONBOARDING]"  # services/onboarding
    TODO: Final[str] = "[TODO]"  # services/todos
    PAYMENT: Final[str] = "[PAYMENT]"  # services/payments
    NOTIFICATION: Final[str] = "[NOTIFICATION]"  # utils/notification
    DESKTOP: Final[str] = "[DESKTOP]"  # services/desktop

    # --- Infra / platform ---
    API: Final[str] = "[API]"  # api/v1 endpoints + middleware (HTTP layer)
    WORKER: Final[str] = "[WORKER]"  # workers/tasks, workers/lifecycle
    STORAGE: Final[str] = "[STORAGE]"  # services/storage (JuiceFS, sessions, vfs)
    MONGO: Final[str] = "[MONGO]"  # db/mongodb
    CHROMA: Final[str] = "[CHROMA]"  # db/chroma (vector store)
    STARTUP: Final[str] = "[STARTUP]"  # app boot / provider registration / lifespan
