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
MAX_PENDING_PROPOSALS: Final[int] = 3  # execution_status == proposed

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


# Canvas skeleton for a GAIA-assigned todo's working memory (canvas.md). Lives
# here so the lifecycle module and canvas service share one source of truth.
CANVAS_TEMPLATE: Final[str] = """# {title}

## Key Details
<!-- email addresses, thread IDs, calendar IDs, issue IDs — everything needed to take action -->

## Current State
<!-- what's true RIGHT NOW — updated after every action -->

## Activity Log
<!-- which agent did what, which tools it used, what the outcome was — add entries HERE, not in Learnings -->

## Timeline
<!-- chronological list of actions taken and results -->

## Context
<!-- accumulated context from signals, related information, decisions made -->

## Learnings
<!-- written on completion: what worked, what didn't, key decisions, timing insights, optimizations for next time -->
"""
