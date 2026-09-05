"""Daily/weekly briefing constants.

Single source of truth for the briefing engine: system-workflow keys, cron
schedules, budgets the prompt is held to, badge keys, and the deterministic
hue rotation. Shared by the service, the system-workflow definitions, and the
workflow-execution branch so nothing hardcodes these values.
"""

from typing import Final, Literal

# System-workflow keys. The workflow ARQ path special-cases these to route into
# the briefing service instead of the generic chat execution.
# Hard ceiling on the weekly digest's payload-generation agent run. The weekly
# run is cron-fired and unsupervised; without a bound a stalled agent run hangs
# the worker slot forever (observed live 2026-08-07). Expiry raises — a missed
# digest fails loud and retries next week rather than half-delivering.
WEEKLY_GENERATION_TIMEOUT_SECONDS: Final[int] = 420

DAILY_BRIEFING_WORKFLOW_KEY: Final[str] = "daily_briefing"
OVERNIGHT_WORK_WORKFLOW_KEY: Final[str] = "overnight_work"
WEEKLY_DIGEST_WORKFLOW_KEY: Final[str] = "weekly_digest"

# Briefing rhythm crons are product plumbing, never user automations: the
# workflow list excludes them so briefings don't present as user workflows.
BRIEFING_RHYTHM_WORKFLOW_KEYS: Final[tuple[str, ...]] = (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
    OVERNIGHT_WORK_WORKFLOW_KEY,
)

# Schedules (user-local timezone; the provisioner stamps the tz onto the trigger).
DAILY_BRIEFING_CRON: Final[str] = "0 8 * * *"  # every day 08:00
# The night shift runs well before the briefing so the 8am brief reports real,
# finished work instead of intentions.
OVERNIGHT_WORK_CRON: Final[str] = "0 5 * * *"  # every day 05:00
WEEKLY_DIGEST_CRON: Final[str] = "0 17 * * 0"  # Sunday 17:00

# Briefing kinds — key the payload variant and the unique-per-day constraint.
BRIEFING_KIND_DAILY: Final[Literal["daily"]] = "daily"
BRIEFING_KIND_WEEKLY: Final[Literal["weekly"]] = "weekly"

# The you-item budget the prompt is held to (max user-facing asks per brief).
MAX_YOU_ITEMS: Final[int] = 3

# Consecutive unacknowledged briefings (no open, no approve) that flip a run into
# winback mode. At/above this the run sends one adaptive winback then backs off.
WINBACK_THRESHOLD: Final[int] = 3

# Idle wind-down: consecutive daily runs that found nothing to work on (no goal,
# no lanes) before the brief warns plainly, then pauses the whole loop (brief,
# night shift, weekly digest) until a reactivation signal.
IDLE_WARN_DAYS: Final[int] = 2
IDLE_DORMANT_DAYS: Final[int] = 3

# Weekly digest hours-saved heuristic: every completed GAIA todo is credited this
# many minutes of user time. Named so the estimate is auditable, not magic.
MINUTES_SAVED_PER_GAIA_TODO: Final[int] = 20

# Existing-user rollout: a briefing whose user still lacks a derivable goal is
# held (bootstrap interview pending) until a goal memory arrives or this many
# days pass, after which a triage-derived best-effort briefing fires.
BOOTSTRAP_GRACE_DAYS: Final[int] = 3

# Deterministic per-day hue rotation of the bands-gradient hero. Coprime step
# over 360 so consecutive days are visually distinct but the sequence is stable.
HUE_ROTATION_STEP: Final[int] = 137
HUE_MAX: Final[int] = 360

# Badge keys (awards collection). Each earnable once per user.
BADGE_FIRST_APPROVE: Final[str] = "first_approve"
BADGE_FIRST_OVERNIGHT_SHIPMENT: Final[str] = "first_overnight_shipment"
BADGE_GAIA_100_TODOS: Final[str] = "gaia_100_todos"
BADGE_STREAK_7: Final[str] = "streak_7"
BADGE_STREAK_30: Final[str] = "streak_30"

# Thresholds behind the count/streak badges.
GAIA_TODOS_CENTURY: Final[int] = 100
STREAK_7_DAYS: Final[int] = 7
STREAK_30_DAYS: Final[int] = 30

# Overnight-shipment window (user-local hours) for first_overnight_shipment.
OVERNIGHT_START_HOUR: Final[int] = 22
OVERNIGHT_END_HOUR: Final[int] = 7


def hue_for_day(day_of_year: int) -> int:
    """Deterministic bands-gradient hue (0-359) for a given day-of-year."""
    return (day_of_year * HUE_ROTATION_STEP) % HUE_MAX
