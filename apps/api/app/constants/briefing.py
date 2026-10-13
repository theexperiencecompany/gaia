"""Daily/weekly briefing constants.

Single source of truth for the briefing engine: system-workflow keys, cron
schedules, budgets the prompt is held to, and the deterministic hue rotation. Shared by the service, the system-workflow definitions, and the
workflow-execution branch so nothing hardcodes these values.
"""

from enum import StrEnum
from typing import Final, Literal

# System-workflow keys. The workflow ARQ path special-cases these to route into
# the briefing service instead of the generic chat execution.
# Hard ceiling on the weekly digest's payload-generation agent run. The weekly
# run is cron-fired and unsupervised; without a bound a stalled agent run hangs
# the worker slot forever (observed live 2026-08-07). Expiry raises — a missed
# digest fails loud and retries next week rather than half-delivering.
WEEKLY_GENERATION_TIMEOUT_SECONDS: Final[int] = 420

DAILY_BRIEFING_WORKFLOW_KEY: Final[str] = "daily_briefing"
WEEKLY_DIGEST_WORKFLOW_KEY: Final[str] = "weekly_digest"

# Briefing rhythm crons are product plumbing, never user automations: the
# workflow list excludes them so briefings don't present as user workflows.
BRIEFING_RHYTHM_WORKFLOW_KEYS: Final[tuple[str, ...]] = (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)

# Schedules (user-local timezone; the provisioner stamps the tz onto the trigger).
DAILY_BRIEFING_CRON: Final[str] = "0 8 * * *"  # every day 08:00
WEEKLY_DIGEST_CRON: Final[str] = "0 17 * * 0"  # Sunday 17:00

# Briefing kinds — key the payload variant and the unique-per-day constraint.
BRIEFING_KIND_DAILY: Final[Literal["daily"]] = "daily"
BRIEFING_KIND_WEEKLY: Final[Literal["weekly"]] = "weekly"

# A brief is finite: at most this many items across all its sections, so it reads
# in under a minute. The daily brief keeps the highest-priority items (needs-you
# first); a weekly payload over the cap fails generation.
MAX_BRIEF_ITEMS: Final[int] = 8

# Telegram's (and WhatsApp's) caption limit: the skim splits into follow-up
# messages past it.
CHAT_CAPTION_MAX_CHARS: Final[int] = 1024

# Rows per list in the weekly edition (shipped, handled, the week ahead).
WEEK_LIST_LIMIT: Final[int] = 5

# Consecutive unacknowledged briefings (no open, no activity) that flip a run into
# winback mode. At/above this the run sends one adaptive winback then backs off.
WINBACK_THRESHOLD: Final[int] = 3

# Idle wind-down: consecutive daily runs that found nothing to work on (no goal,
# no tracked work) before the brief warns plainly, then pauses the whole loop
# (brief, weekly digest) until a reactivation signal.
IDLE_WARN_DAYS: Final[int] = 2
IDLE_DORMANT_DAYS: Final[int] = 3

# Existing-user rollout: a briefing whose user still lacks a derivable goal is
# held (bootstrap interview pending) until a goal memory arrives or this many
# days pass, after which a triage-derived best-effort briefing fires.
BOOTSTRAP_GRACE_DAYS: Final[int] = 3

# Deterministic per-day hue rotation of the bands-gradient hero. Coprime step
# over 360 so consecutive days are visually distinct but the sequence is stable.
HUE_ROTATION_STEP: Final[int] = 137
HUE_MAX: Final[int] = 360


def hue_for_day(day_of_year: int) -> int:
    """Deterministic bands-gradient hue (0-359) for a given day-of-year."""
    return (day_of_year * HUE_ROTATION_STEP) % HUE_MAX


# The weekly recap's edition family (never drawn for a daily brief) and the Air
# Mail family, the only one that carries a city stamp.
WEEKLY_FAMILY: Final[str] = "weekly"
POSTAL_FAMILY: Final[str] = "postal"


class BriefingBag(StrEnum):
    """The per-user shuffle bags kept on the user doc (``briefing_shuffle_bags``)."""

    EDITION_FAMILY = "edition_family"
    STAMP_CITY = "stamp_city"
