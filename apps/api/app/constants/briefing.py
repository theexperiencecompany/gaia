"""Daily/weekly briefing constants.

Single source of truth for the briefing engine: system-workflow keys, cron
schedules, budgets the prompt is held to, and the deterministic hue rotation. Shared by the service, the system-workflow definitions, and the
workflow-execution branch so nothing hardcodes these values.
"""

from enum import StrEnum
from typing import Final, Literal

# Hard ceiling on the unsupervised weekly agent run; expiry raises so a stalled
# run fails loud and retries next week instead of hanging the worker slot.
WEEKLY_GENERATION_TIMEOUT_SECONDS: Final[int] = 420

# System-workflow keys; the workflow ARQ path routes these into the briefing service.
DAILY_BRIEFING_WORKFLOW_KEY: Final[str] = "daily_briefing"
WEEKLY_DIGEST_WORKFLOW_KEY: Final[str] = "weekly_digest"

# Briefing rhythm crons are product plumbing, never user automations: the
# workflow list excludes them so briefings don't present as user workflows.
BRIEFING_RHYTHM_WORKFLOW_KEYS: Final[tuple[str, ...]] = (
    DAILY_BRIEFING_WORKFLOW_KEY,
    WEEKLY_DIGEST_WORKFLOW_KEY,
)

# Schedules (user-local timezone; the provisioner stamps the tz onto the trigger).
# The daily brief's default local hour; the user picks their own, and quiet hours
# covering it push it to when they end (briefing.schedule).
DAILY_BRIEFING_HOUR: Final[int] = 8
# Cron day-of-week field for a brief that runs every day, and for Monday to Friday.
EVERY_DAY_CRON_DAYS: Final[str] = "*"
WEEKDAYS_CRON_DAYS: Final[str] = "1-5"
WEEKLY_DIGEST_CRON: Final[str] = "0 17 * * 0"  # Sunday 17:00

# Briefing kinds — key the payload variant and the unique-per-day constraint.
BRIEFING_KIND_DAILY: Final[Literal["daily"]] = "daily"
BRIEFING_KIND_WEEKLY: Final[Literal["weekly"]] = "weekly"

# Masthead labels, set by code on each kind's payload (never by the model).
DAILY_KICKER: Final[str] = "THE MORNING BRIEF"
WEEKLY_KICKER: Final[str] = "THE WEEKLY DIGEST"


class SectionKey(StrEnum):
    """What one section of a brief holds; every surface reads the key, never the title or position."""

    LEAD = "lead"
    NEEDS_YOU = "needs_you"
    UPDATES = "updates"
    GAIA_DID = "gaia_did"
    WEEK = "week"


# Daily brief section heads, numbered in order. Display casing: every surface shows
# these as written; an edition that sets its heads in capitals does so in its own CSS.
SECTION_TITLES: Final[dict[SectionKey, str]] = {
    SectionKey.LEAD: "First up",
    SectionKey.NEEDS_YOU: "Needs you",
    SectionKey.UPDATES: "From your apps",
    SectionKey.GAIA_DID: "GAIA's work",
    SectionKey.WEEK: "This week",
}
SECTION_NUMERALS: Final[tuple[str, ...]] = ("I", "II", "III", "IV")
# The daily brief's sections in reading order, and the most items the selection judge
# may put in each: the brief reads in under a minute.
DAILY_SECTION_ORDER: Final[tuple[SectionKey, ...]] = (
    SectionKey.LEAD,
    SectionKey.NEEDS_YOU,
    SectionKey.UPDATES,
    SectionKey.GAIA_DID,
)
SECTION_CAPS: Final[dict[SectionKey, int]] = {
    SectionKey.LEAD: 1,
    SectionKey.NEEDS_YOU: 4,
    SectionKey.UPDATES: 3,
    SectionKey.GAIA_DID: 3,
}
# The model-written weekly payload holds at most this many items across its sections.
MAX_BRIEF_ITEMS: Final[int] = 8
#: Selection judge calls per brief: one more when its answer breaks the contract, then the run fails.
MAX_SELECTION_ATTEMPTS: Final[int] = 2
#: The selection judge's metering label.
BRIEF_SELECTION_LABEL: Final[str] = "brief_selection_judge"
#: What a candidate's source is when GAIA itself, not a connected app, produced it.
GAIA_SOURCE: Final[str] = "gaia"
GAIA_APP_NAME: Final[str] = "GAIA"
# Longest render that fits (Chromium, real renderers, worst of 20 skin seeds): headline 3 lines
# of gradient's 46px h1, the tightest family; lede 3 lines, caption 1, of the classic edition.
MAX_BRIEF_HEADLINE_CHARS: Final[int] = 52
MAX_BRIEF_LEDE_CHARS: Final[int] = 247
MAX_BRIEF_CAPTION_CHARS: Final[int] = 148
# The message is a text, not a wall: about 20 short lines on the busiest day.
MAX_BRIEF_MESSAGE_CHARS: Final[int] = 2700
# How many recent briefs' opening lines the model sees, so today's opens differently.
RECENT_OPENINGS_SHOWN: Final[int] = 5
# Voice attempts per daily brief: one regeneration when its slots or its claims fail the
# facts, then the run fails rather than ship it.
MAX_VOICE_ATTEMPTS: Final[int] = 2
#: The faithfulness check's metering label.
BRIEF_FAITHFULNESS_LABEL: Final[str] = "brief_faithfulness_check"
#: The check judges, it does not write: the same draft gets the same verdict.
BRIEF_FAITHFULNESS_TEMPERATURE: Final[float] = 0.0

# Rows per list in the weekly edition (shipped, handled, the week ahead).
WEEK_LIST_LIMIT: Final[int] = 5

# Consecutive unacknowledged briefings (no open, no activity) that flip a run into
# winback mode. At/above this the run sends one adaptive winback then backs off.
WINBACK_THRESHOLD: Final[int] = 3


class BriefingFrequency(StrEnum):
    """How often the user wants briefs: the one setting the briefing workflows follow."""

    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY_ONLY = "weekly_only"
    OFF = "off"


# The briefing workflows each frequency keeps running.
ENABLED_BRIEFING_KEYS: Final[dict[BriefingFrequency, frozenset[str]]] = {
    BriefingFrequency.DAILY: frozenset(BRIEFING_RHYTHM_WORKFLOW_KEYS),
    BriefingFrequency.WEEKDAYS: frozenset(BRIEFING_RHYTHM_WORKFLOW_KEYS),
    BriefingFrequency.WEEKLY_ONLY: frozenset({WEEKLY_DIGEST_WORKFLOW_KEY}),
    BriefingFrequency.OFF: frozenset(),
}

# Idle wind-down: consecutive daily runs that found nothing to work on (no goal,
# no tracked work) before the brief warns plainly, then pauses the whole loop
# (brief, weekly digest) until a reactivation signal.
IDLE_WARN_DAYS: Final[int] = 2
IDLE_DORMANT_DAYS: Final[int] = 3
# A new account's first days never wind down: the brief helps them get started instead.
FIRST_WEEK_DAYS: Final[int] = 7

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
# The web page that shows the user's collected Air Mail stamps.
POSTMARKS_PATH: Final[str] = "/settings/postmarks"


class BriefItemSource(StrEnum):
    """What held a result for the user's next brief instead of sending it."""

    WORKFLOW = "workflow"
    TODO = "todo"


class BriefingBag(StrEnum):
    """The per-user shuffle bags kept on the user doc (briefing_shuffle_bags)."""

    EDITION_FAMILY = "edition_family"
    STAMP_CITY = "stamp_city"


class BriefingRunOutcome(StrEnum):
    """How one scheduled briefing run ended: sent, or skipped before any delivery."""

    SENT = "sent"
    ALREADY_DELIVERED = "already_delivered"
    DORMANT = "dormant"
    BOOTSTRAP_PENDING = "bootstrap_pending"
    WINBACK_BACKOFF = "winback_backoff"


# The workflow execution's summary for each outcome, shown in the run history.
BRIEFING_RUN_SUMMARIES: Final[dict[BriefingRunOutcome, str]] = {
    BriefingRunOutcome.SENT: "Briefing delivered",
    BriefingRunOutcome.ALREADY_DELIVERED: "Skipped: this briefing was already delivered today",
    BriefingRunOutcome.DORMANT: "Skipped: briefings are paused until the user is active again",
    BriefingRunOutcome.BOOTSTRAP_PENDING: "Skipped: held until the user's goal is known",
    BriefingRunOutcome.WINBACK_BACKOFF: "Skipped: backing off after an unanswered winback",
}

# Every surface shows the edition at most 540 CSS px wide (email column, chat
# bubble); 2x covers retina screens. The 2-6 MB original upload stays on the CDN,
# and each surface is served a delivery transformation capped at this width.
EDITION_DELIVERY_MAX_WIDTH_PX: Final[int] = 1080

# Every edition template marks the top of its first body block, after the header, with
# this attribute: the gap where the folded letter's front panel ends.
FOLD_MARKER_SELECTOR: Final[str] = "[data-fold]"

# An edition laid on a desk marks its paper element with this attribute; its box
# is recorded so the letter and the unfold show the paper alone.
PAPER_MARKER_SELECTOR: Final[str] = "[data-paper]"


class EditionDeliveryFormat(StrEnum):
    """Cloudinary fetch format for an edition delivery URL."""

    # Negotiated per client from its Accept header (AVIF/WebP, else PNG): browsers and email.
    AUTO = "auto"
    # Chat platforms download the file themselves and pick photo vs document by
    # its size, so they get one fixed, compact format.
    JPG = "jpg"
