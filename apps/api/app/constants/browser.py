"""Constants for the Steel + Browser-Use browser-automation capability.

Single source of truth for the tool name, the SSE card-event keys, the Redis
handoff namespace, and the heuristics that decide when the browser agent must
hand control to the human. Values a deployment may tune live in ``settings``;
values that are part of the wire/UI contract live here so backend and frontend
cannot drift.

The *startup* gate ("do you want me to use a browser?") is handled by the shared
HIL system (``browser_task`` is registered destructive). This module governs the
*mid-run* gate: when the agent reaches a payment / credential / irreversible
step, a per-task policy decides whether to hand off to the user (live-view),
proceed autonomously (e.g. a configured agent card), or abort.
"""

from enum import Enum

# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------
BROWSER_TOOL_NAME = "browser_task"
BROWSER_TOOL_CATEGORY = "browser"

# ---------------------------------------------------------------------------
# SSE card-event key (must match `tool_fields` in app/models/chat_models.py and
# the frontend TOOL_RENDERERS / toolRegistry registration).
# ---------------------------------------------------------------------------
BROWSER_TASK_EVENT = "browser_task_data"


class BrowserEventKind(str, Enum):
    """Discriminator for a single ``browser_task_data`` snapshot entry."""

    SESSION = "session"
    STEP = "step"
    HANDOFF = "handoff"
    RESULT = "result"


class BrowserSessionStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SensitiveCategory(str, Enum):
    """Why a planned browser step is sensitive."""

    NONE = "none"
    PAYMENT = "payment"
    CREDENTIALS = "credentials"
    IRREVERSIBLE = "irreversible"


class HandoffStrategy(str, Enum):
    """What to do when the agent reaches a sensitive step."""

    HANDOFF = "handoff"  # pause, surface live-view, let the human do it, then continue
    PROCEED = "proceed"  # let the agent do it autonomously (e.g. a configured agent card)
    ABORT = "abort"  # stop the task rather than do it


class HandoffStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"  # user finished the step in live-view → resume
    CANCELLED = "cancelled"  # user cancelled → abort
    TIMEOUT = "timeout"  # nobody acted → abort


class HandoffDecision(str, Enum):
    CONTINUE = "continue"
    CANCEL = "cancel"


# ---------------------------------------------------------------------------
# Redis handoff bridge. A running browser task blocks on one of these keys; the
# `/browser/handoffs/{id}/decision` endpoint writes the resolution from a
# possibly-different worker process. This is a browser-session continue/cancel
# signal, NOT tool-call approval — the shared HIL system owns the latter.
# ---------------------------------------------------------------------------
BROWSER_HANDOFF_KEY_PREFIX = "browser:handoff:"
HANDOFF_POLL_INTERVAL_SECONDS = 1.0
HANDOFF_KEY_TTL_SECONDS = 3600

# ---------------------------------------------------------------------------
# Concurrency registry. A Redis sorted set (member = slot id, score = expiry
# deadline) is the cluster-wide source of truth for how many browser sessions
# are live, so the cap holds across workers/replicas. A crashed worker's slot
# self-heals: its member expires by score and is pruned on the next acquire.
# ---------------------------------------------------------------------------
BROWSER_ACTIVE_SESSIONS_KEY = "browser:active_sessions"

# ---------------------------------------------------------------------------
# Steel REST API paths (self-hosted Steel, ghcr.io/steel-dev/steel-browser-api).
# ---------------------------------------------------------------------------
STEEL_SESSIONS_PATH = "/v1/sessions"
STEEL_SESSION_RELEASE_PATH = "/v1/sessions/{session_id}/release"
STEEL_HEALTH_PATH = "/health"

# ---------------------------------------------------------------------------
# Sensitive-action classification. A structural allowlist of Browser-Use action
# names that can never commit or leak secrets (pure navigation / reading). Steps
# whose planned actions are ALL in this set skip the LLM classifier — a
# deterministic fast path. Interactive actions go to the classifier.
# ---------------------------------------------------------------------------
NON_COMMITTING_ACTIONS: frozenset[str] = frozenset(
    {
        "go_to_url",
        "search",
        "search_google",
        "go_back",
        "scroll",
        "scroll_down",
        "scroll_up",
        "scroll_to_text",
        "wait",
        "wait_for_captcha_solution",
        "extract_content",
        "extract_structured_data",
        "read_content",
        "get_dropdown_options",
        "done",
    }
)
