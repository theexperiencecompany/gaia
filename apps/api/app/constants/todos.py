"""
Todo Constants.

Constants for todo service operations.
"""

from datetime import datetime
from typing import Any, Final

from app.utils.timezone import Timezone

ONBOARDING_TODO_LIMIT = 3

# Label marking a todo seeded during onboarding — used to fetch and to purge them.
ONBOARDING_LABEL: Final[str] = "onboarding"

# Label added by the maintenance sweep to an overdue todo with no scheduled
# follow-up, so the UI can surface it for attention.
NEEDS_FOLLOW_UP_LABEL: Final[str] = "needs-follow-up"

# Stand-in shown wherever a todo's title is surfaced but was never set (agent
# prompts, notifications, digests) — one wording across every surface.
UNTITLED_TODO_TITLE: Final[str] = "Untitled Todo"

# DEPRECATED: legacy discriminator for GAIA-owned todos, fully superseded by the
# ``assignee`` field. Nothing writes it any more. Two readers remain, both for
# docs the backfill has not reached yet: the one-time backfill itself
# (scripts/migrate_todo_assignee.py), and signal_context, which strips the label
# so it never shows up in rendered agent context. Delete all three once the
# backfill has run everywhere.
GAIA_TRACKED_LABEL: Final[str] = "gaia-tracked"

# Bookkeeping label the executor stamps on a todo that has exhausted its retry
# attempts; the execution loop reads it to skip permanently-failed todos, and the
# retry transition clears it to let the re-run proceed.
FAILED_LABEL: Final[str] = "failed"

# Labels that mean "this todo is waiting on something outside GAIA". The
# maintenance sweep reads them to decide whether an overdue todo is genuinely
# stuck, and the trigger-subscription paths set and clear them — so they live
# here rather than inside either consumer.
WAITING_FOR_REPLY_LABEL: Final[str] = "waiting-for-reply"
WAITING_FOR_APPROVAL_LABEL: Final[str] = "waiting-for-approval"
BLOCKING_LABEL: Final[str] = "blocked"

BLOCKING_LABELS: Final[frozenset[str]] = frozenset(
    {WAITING_FOR_REPLY_LABEL, WAITING_FOR_APPROVAL_LABEL, BLOCKING_LABEL}
)

# Cap on user-initiated retries of a failed GAIA todo. Distinct from the
# executor's internal per-run backoff counter (``gaia_retry_count``): this bounds
# how many times a human may re-run a todo that keeps failing.
MAX_GAIA_USER_RETRIES: Final[int] = 3

# Todo assignee values. ``assignee`` replaces GAIA_TRACKED_LABEL as the
# discriminator for who owns a todo. Kept as constants (not a magic string)
# for every read/write filter and lifecycle transition.
ASSIGNEE_USER: Final = "user"
ASSIGNEE_GAIA: Final = "gaia"

# Server-enforced budgets on GAIA-assigned todos. Scarcity forces the agent to
# rank rather than spawn junk (see tracked_todo_service creation gate).
MAX_GAIA_TODOS_IN_FLIGHT: Final[int] = 5  # execution_status in {queued, running, needs_you}
MAX_PENDING_PROPOSALS: Final[int] = 3

# Goal lanes are exempt from the in-flight cap (they live for months) but are
# themselves capped: each active goal costs nightly planning attention.
MAX_ACTIVE_GOALS: Final[int] = 3  # execution_status == proposed

# A proposed GAIA todo the user never acts on expires after this window and is
# swept by the curation pass (writes a proposal_rejected memory signal).
PROPOSAL_TTL_HOURS: Final[int] = 72

# A proposal actively used as a tier-upgrade pitch is exempt from PROPOSAL_TTL
# for this longer window (pitch_expires_at) so the conversion surface survives.
PITCH_TTL_DAYS: Final[int] = 7

# A proposal "kind" dismissed or expired this many times is not re-proposed
# unless the user explicitly asks again.
REJECTION_STRIKE_THRESHOLD: Final[int] = 3

# Memory folder that holds structured ``proposal_rejected`` signals so dismiss /
# expiry teach the agent which kinds to stop proposing.
PROPOSAL_REJECTED_MEMORY_CATEGORY: Final[str] = "gaia/proposals/rejected"

# Tiered rate-limit feature key metering GAIA todo executions (approve/queue
# transition). Defined here so the service enforcing it and the FEATURE_LIMITS
# registry share one source of truth.
GAIA_TODO_EXECUTIONS_FEATURE: Final[str] = "gaia_todo_executions"

# The user's waking window (user-local hours, [start, end)). Gates only the
# completion-report nudge — a completion outside it still delivers, just
# without the suggestion line. Blocker and failure pushes are deliberately
# NOT gated (product decision 2026-08-07: no quiet hours).
WAKING_HOUR_START: Final[int] = 9
WAKING_HOUR_END: Final[int] = 22


def is_waking_hour(user_timezone: str | None) -> bool:
    """Whether it is currently within the user's waking window."""
    local_hour = datetime.now(Timezone.parse(user_timezone).tzinfo).hour
    return WAKING_HOUR_START <= local_hour < WAKING_HOUR_END


# How many open gaia_offer user todos the completion nudge considers when
# picking the highest-priority one — small on purpose, this is a cheap
# in-memory pick, not a paginated query.
NUDGE_OFFER_CANDIDATE_LIMIT: Final[int] = 20


def gaia_assigned_filter() -> dict[str, Any]:
    """Mongo fragment selecting GAIA-assigned todos (``assignee == "gaia"``).

    Assumes the assignee backfill (scripts/migrate_todo_assignee.py) has run, so
    every GAIA-owned todo carries ``assignee``; the legacy ``gaia-tracked`` label
    is no longer consulted.
    """
    return {"assignee": ASSIGNEE_GAIA}


def user_assigned_filter() -> dict[str, Any]:
    """Mongo fragment excluding GAIA-assigned todos (matches user todos).

    ``assignee != "gaia"`` also matches unmigrated docs with no ``assignee``
    field, which are user todos by default.
    """
    return {"assignee": {"$ne": ASSIGNEE_GAIA}}


# --- Facets --------------------------------------------------------------
#
# A tracked todo is a small workspace split into distinct facets, each stored
# as its own field on the todo document:
#   - deliverable — the polished, user-facing output Approve releases
#   - notes       — GAIA's private working memory (plan, key details, state)
#   - log         — the activity/timeline audit trail
# The legacy ``canvas_content`` field predates this split; it maps to the
# ``notes`` facet during the migration window (see ``facet_from_doc``).

FACET_DELIVERABLE: Final = "deliverable"
FACET_NOTES: Final = "notes"
FACET_LOG: Final = "log"

# Facet → Mongo field on the todo doc. The single source of truth for every
# read/write of facet content (storage primitives, endpoints, VFS projection).
FACET_FIELDS: Final[dict[str, str]] = {
    FACET_DELIVERABLE: "deliverable_content",
    FACET_NOTES: "notes_content",
    FACET_LOG: "log_content",
}

# Legacy field carrying the pre-facet combined blob. notes and deliverable both
# fall back to it until the backfill (scripts/migrate_todo_facets.py) runs.
_LEGACY_CANVAS_FIELD: Final = "canvas_content"


def facet_from_doc(doc: dict[str, Any], facet: str, *, allow_canvas_fallback: bool) -> str:
    """Resolve a facet's content from a raw todo doc, applying the migration bridge.

    Single source of truth for the dual-read fallback, shared by the storage
    primitives (``read_facet``) and the VFS projection (``_project``) so they
    can never diverge.

    MIGRATION BRIDGE (temporary): pre-facet todos stored everything in
    ``canvas_content``. ``notes`` always falls back to it (the old canvas WAS
    the working memory); ``deliverable`` falls back only for proposals — whose
    staged content lived in the old canvas — gated by ``allow_canvas_fallback``.
    Remove this fallback (and ``canvas_content``) once the backfill has run
    everywhere.
    """
    value = doc.get(FACET_FIELDS[facet])
    if value:
        return str(value)
    if facet == FACET_NOTES:
        return str(doc.get(_LEGACY_CANVAS_FIELD) or "")
    if facet == FACET_DELIVERABLE and allow_canvas_fallback:
        return str(doc.get(_LEGACY_CANVAS_FIELD) or "")
    return ""


# Skeleton for the deliverable facet — the send-ready output. Kept light: a
# proposal must supply its own finished content (the staging invariant), and an
# internal todo starts with just a heading to fill in.
DELIVERABLE_TEMPLATE: Final[str] = """# {title}

## Output
<!-- the polished, send-ready result — the exact content Approve releases -->
"""

# Skeleton for the notes facet — GAIA's working memory. Activity Log and
# Timeline deliberately live in the ``log`` facet, not here, so there is one
# home for chronological activity instead of two.
NOTES_TEMPLATE: Final[str] = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State
<!-- what's true RIGHT NOW — updated after every action -->

## Context
<!-- accumulated context from signals, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions, timing insights, optimizations for next time -->
"""
