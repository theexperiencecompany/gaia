"""
Todo Constants.

Constants for todo service operations.
"""

from typing import Any, Final

ONBOARDING_TODO_LIMIT = 3

# DEPRECATED: legacy discriminator for GAIA-owned todos, superseded by the
# ``assignee`` field on the todo model. Retained only for the one-release
# dual-read migration window (see ``gaia_assigned_filter``); removed once the
# backfill (scripts/migrate_todo_assignee.py) has run everywhere. New code MUST
# key off ``assignee`` / ``ASSIGNEE_GAIA``, never this label.
GAIA_TRACKED_LABEL: Final[str] = "gaia-tracked"

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


def gaia_assigned_filter() -> dict[str, Any]:
    """Mongo fragment selecting GAIA-assigned todos.

    Dual-read for the migration window: a todo is GAIA-owned if
    ``assignee == "gaia"`` OR it still carries the legacy ``gaia-tracked``
    label. Retired to ``{"assignee": ASSIGNEE_GAIA}`` once the backfill lands.
    """
    return {"$or": [{"assignee": ASSIGNEE_GAIA}, {"labels": GAIA_TRACKED_LABEL}]}


def user_assigned_filter() -> dict[str, Any]:
    """Mongo fragment excluding GAIA-assigned todos (inverse of dual-read).

    Matches user todos: ``assignee != "gaia"`` (covers unmigrated docs with no
    ``assignee`` field) AND no legacy ``gaia-tracked`` label.
    """
    return {"assignee": {"$ne": ASSIGNEE_GAIA}, "labels": {"$nin": [GAIA_TRACKED_LABEL]}}


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
        return value
    if facet == FACET_NOTES:
        return doc.get(_LEGACY_CANVAS_FIELD) or ""
    if facet == FACET_DELIVERABLE and allow_canvas_fallback:
        return doc.get(_LEGACY_CANVAS_FIELD) or ""
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
