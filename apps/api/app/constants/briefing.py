"""Daily/weekly briefing constants.

Single source of truth for the briefing engine: system-workflow keys, cron
schedules, budgets the prompt is held to, and the deterministic hue rotation. Shared by the service, the system-workflow definitions, and the
workflow-execution branch so nothing hardcodes these values.
"""

from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

# Hard ceiling on a brief's voice call, daily or weekly; expiry raises so a stalled
# run fails loud and retries at its next run instead of hanging the worker slot.
BRIEF_VOICE_TIMEOUT_SECONDS: Final[int] = 420

# System-workflow keys; the workflow ARQ path routes these into the briefing service.
DAILY_BRIEFING_WORKFLOW_KEY: Final[str] = "daily_briefing"
WEEKLY_DIGEST_WORKFLOW_KEY: Final[str] = "weekly_digest"


class BriefingKind(StrEnum):
    """Which brief a run makes; keys the payload variant and the one-per-day constraint."""

    DAILY = "daily"
    WEEKLY = "weekly"


#: Which kind of brief each briefing system workflow's cron runs.
BRIEFING_KIND_BY_WORKFLOW_KEY: Final[Mapping[str, BriefingKind]] = MappingProxyType(
    {
        DAILY_BRIEFING_WORKFLOW_KEY: BriefingKind.DAILY,
        WEEKLY_DIGEST_WORKFLOW_KEY: BriefingKind.WEEKLY,
    }
)
# Briefing rhythm crons are product plumbing, never user automations: the
# workflow list excludes them so briefings don't present as user workflows.
BRIEFING_RHYTHM_WORKFLOW_KEYS: Final[tuple[str, ...]] = tuple(BRIEFING_KIND_BY_WORKFLOW_KEY)

# Schedules (user-local timezone; the provisioner stamps the tz onto the trigger).
# The daily brief's default local hour; the user picks their own, and quiet hours
# covering it push it to when they end (briefing.schedule).
DAILY_BRIEFING_HOUR: Final[int] = 8
#: The weekly digest's local hour, on Sunday; quiet hours covering it push it to when they end.
WEEKLY_DIGEST_HOUR: Final[int] = 17
# The weekdays (Monday 0) a brief lands on.
EVERY_DAY: Final[frozenset[int]] = frozenset(range(7))
MONDAY_TO_FRIDAY: Final[frozenset[int]] = frozenset(range(5))
SUNDAY: Final[frozenset[int]] = frozenset({6})

# Retention. A sent brief stays in the archive and on the postmark globe for a year, then a
# nightly sweep deletes it with its edition image; a held result the loop neither carried nor
# released is dropped after a month (its full run stays in its workflow's or todo's conversation).
BRIEFING_RETENTION: Final = timedelta(days=365)
#: How many expired briefs one page of the nightly sweep reads before deleting them.
BRIEFING_EXPIRY_PAGE: Final[int] = 200
PENDING_BRIEF_ITEM_RETENTION_SECONDS: Final[int] = 30 * 24 * 60 * 60


#: The most candidates one source puts in a brief's pool, so the composition prompt stays bounded.
BRIEF_POOL_PER_SOURCE: Final[int] = 40
#: Past its first day overdue, a daily brief shows an overdue item at most once in this many days.
OVERDUE_RESHOW_DAYS: Final[int] = 3


# Masthead labels, set by code on each kind's payload (never by the model).
DAILY_KICKER: Final[str] = "THE MORNING BRIEF"
WEEKLY_KICKER: Final[str] = "THE WEEKLY DIGEST"


class BriefAction(StrEnum):
    """What a brief item asks the reader to do; set only on items that need them."""

    APPROVE = "approve"
    REPLY = "reply"
    REVIEW = "review"
    RETRY = "retry"
    READ = "read"
    ATTEND = "attend"


#: What GAIA offers to do about the lead, by what it asks of the reader: a fixed act GAIA really
#: does, never words a model wrote over the item's third-party text.
LEAD_OFFERS: Final[Mapping[BriefAction, str]] = MappingProxyType(
    {
        BriefAction.APPROVE: "Walk you through it before you approve",
        BriefAction.REPLY: "Draft the reply for you to send",
        BriefAction.REVIEW: "Pull together what you need to review it",
        BriefAction.RETRY: "Run it again and tell you how it went",
        BriefAction.READ: "Sum it up for you",
        BriefAction.ATTEND: "Prepare your notes for it",
    }
)


class BriefOutcome(StrEnum):
    """The state a reported brief item reached; set only on items that need nothing from the reader."""

    APPROVED = "approved"
    LANDED = "landed"
    DRAFTED = "drafted"
    BOOKED = "booked"
    SENT = "sent"
    FINISHED = "finished"
    STARTED = "started"
    CHANGED = "changed"
    FAILED = "failed"


# Title of the in-app note that releases what was held when no daily brief will carry it.
HELD_RELEASE_TITLE: Final[str] = "While you were away"
#: What the lead's section is headed: the composition gives the lead no heading of its own.
LEAD_HEADING: Final[str] = "First up"
#: A group code heads (a salvage, a misfit heading) when every item asks one act.
ACTION_HEADINGS: Final[Mapping[BriefAction, str]] = MappingProxyType(
    {
        BriefAction.APPROVE: "To approve",
        BriefAction.REPLY: "Replies to send",
        BriefAction.REVIEW: "To review",
        BriefAction.RETRY: "To retry",
        BriefAction.READ: "To read",
        BriefAction.ATTEND: "To do",
    }
)
#: A group code heads when it holds only the user's own undated todos.
BACKLOG_HEADING: Final[str] = "Still on your list"
#: Section numerals, in reading order, for the editions that number their sections.
SECTION_NUMERALS: Final[tuple[str, ...]] = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
# Every brief item is a short noun-phrase title and at most one muted detail line.
BRIEF_ITEM_TITLE_MAX_CHARS: Final[int] = 50
BRIEF_ITEM_DETAIL_MAX_CHARS: Final[int] = 80
#: Composition calls per brief: one more when the answer breaks the contract, then code
#: salvages what holds of it (briefing.checked_call).
MAX_COMPOSITION_ATTEMPTS: Final[int] = 2
#: The composition call's metering label, and its heading check's.
BRIEF_COMPOSITION_LABEL: Final[str] = "brief_composition"
BRIEF_HEADING_CHECK_LABEL: Final[str] = "brief_heading_check"
#: The voice call's metering label: the brief's headline, lede, caption and message.
BRIEF_VOICE_LABEL: Final[str] = "brief_voice"
#: The heading check judges, it does not write: the same groups get the same verdict.
BRIEF_HEADING_CHECK_TEMPERATURE: Final[float] = 0.0
# The page budget a composition is held to: what one edition image and a minute's read can carry.
MAX_BRIEF_BLOCKS: Final[int] = 7
MAX_BRIEF_ITEMS: Final[int] = 10
MAX_ITEMS_PER_BLOCK: Final[int] = 5
#: Rows an edition prints in one group or the calendar; the rest are "+N more in the full brief".
EDITION_ROWS_SHOWN: Final[int] = 3
MAX_BRIEF_CHARTS: Final[int] = 2
# The model-written strings of a composition, each one line on the narrowest edition.
BRIEF_HEADING_MAX_CHARS: Final[int] = 40
BRIEF_CHART_TITLE_MAX_CHARS: Final[int] = 48
BRIEF_TAKEAWAY_MAX_CHARS: Final[int] = 140
BRIEF_NOTE_MAX_CHARS: Final[int] = 240
# A line or spark chart reads a trend only over at least this many days; a bar reads at most this many bars.
MIN_TREND_POINTS: Final[int] = 5
#: Lines one chart may draw: every family's two line styles, then the same two dotted.
MAX_LINE_SERIES: Final[int] = 4
MAX_BAR_CATEGORIES: Final[int] = 12
#: The days a series covers: the week ending today.
SERIES_WINDOW_DAYS: Final[int] = 7
# A quote is a whole sentence or two of someone's own words, short enough to set large.
QUOTE_MIN_CHARS: Final[int] = 24
QUOTE_MAX_CHARS: Final[int] = 200
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
RECENT_BRIEFS_RECALLED: Final[int] = 5
#: Words that say how often something happens; the voice may use one only where a fact does.
FREQUENCY_CLAIMS: Final[tuple[str, ...]] = (
    "rare",
    "rarely",
    "seldom",
    "unusual",
    "unusually",
    "usual",
    "usually",
    "typical",
    "typically",
    "for once",
    "as always",
    "once again",
)
#: Words that say one thing causes, blocks or gates another; prose may use one only where a fact does.
DEPENDENCY_CLAIMS: Final[tuple[str, ...]] = (
    "because",
    "blocks",
    "blocked",
    "blocking",
    "blocker",
    "unblock",
    "unblocks",
    "unblocking",
    "holding up",
    "holds up",
    "held up",
    "bottleneck",
    "caused by",
    "depends on",
    "dependent on",
    "opens up",
    "frees up",
)
# Voice attempts per brief: one mend of the last brief when its slots fail the facts (the
# mend shows it what it wrote), then code voices it plainly from its facts (briefing.checked_call).
MAX_VOICE_ATTEMPTS: Final[int] = 2
#: The plain voice a brief gets when the model's never holds to its facts.
PLAIN_BRIEF_HEADLINE: Final[str] = "Your brief"
PLAIN_BRIEF_EMPTY: Final[str] = "Here is your brief."

# The user's own todos due today or overdue the daily brief weighs as candidates.
DUE_TODO_CANDIDATES_LIMIT: Final[int] = 20

# Their oldest open todos with no due date, offered for GAIA to show or skip.
UNDATED_TODO_CANDIDATES_LIMIT: Final[int] = 3

# Days a daily brief looks back at most, however long ago the last one went out.
LOOKBACK_MAX_DAYS: Final[int] = 7

# Events the weekly recap carries from the week ahead.
WEEK_LIST_LIMIT: Final[int] = 5

# Consecutive unacknowledged briefings (no open, no activity) that flip a run into
# winback mode. At/above this the run sends one adaptive winback then backs off.
WINBACK_THRESHOLD: Final[int] = 3


class BriefForm(StrEnum):
    """What a stored brief is: a drawn edition, or the plain note a quiet day sends instead."""

    EDITION = "edition"
    QUIET_NOTE = "quiet_note"


#: A quiet day's or week's note: nothing new and nothing on the calendar, so no edition, no
#: filler. Its first line says what is new, then how the calendar stands; a quiet brief after
#: a quiet brief says it is still quiet and since when, so a quiet streak never reads the same.
DAILY_QUIET_HEADLINE: Final[str] = "Nothing needs you today"
WEEKLY_QUIET_HEADLINE: Final[str] = "Nothing needs you this week"
DAILY_QUIET_NOTHING_NEW: Final[str] = "Nothing new needs you today"
WEEKLY_QUIET_NOTHING_NEW: Final[str] = "Nothing moved this week"
QUIET_NOTE_STILL: Final[str] = "Still nothing new, as in your last briefs"
QUIET_NOTE_STILL_SINCE: Final[str] = "Still nothing new since your brief {when}"
QUIET_NOTE_STILL_FOR: Final[str] = "Still nothing new: {days} days since your brief {when}"
DAILY_QUIET_CALENDAR_CLEAR: Final[str] = ", and your calendar is clear."
WEEKLY_QUIET_CALENDAR_CLEAR: Final[str] = ", and next week's calendar is clear."
QUIET_NOTE_NO_CALENDAR: Final[str] = "."
QUIET_NOTE_CALENDAR_UNREAD: Final[str] = (
    ". I couldn't read your calendar, so check it before you plan."
)
QUIET_NOTE_OVERDUE: Final[str] = "{count} of your own todos are past due."
#: A quiet brief that could not read every app: its quiet is only of what it read.
QUIET_NOTE_UNREAD_HEADLINE: Final[str] = "Nothing new in what I could read"
QUIET_NOTE_UNREAD: Final[str] = "I couldn't read {apps} this time, so I can't say what they hold."
QUIET_NOTE_SIGNED_OUT: Final[str] = (
    "Your {apps} sign-in expired: reconnect it in Settings, Integrations and I'll read it again."
)
QUIET_NOTE_SIGNED_OUT_MANY: Final[str] = (
    "Your {apps} sign-ins expired: reconnect them in Settings, Integrations and I'll read them "
    "again."
)
QUIET_NOTE_WATCH: Final[str] = "I'll flag anything that comes in."


class BriefingFrequency(StrEnum):
    """How often the user wants briefs: the one setting the briefing workflows follow."""

    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKLY_ONLY = "weekly_only"
    OFF = "off"


#: The briefing workflows each frequency runs, by key, and the weekdays each lands on;
#: a workflow a frequency leaves out does not run.
BRIEF_RUN_DAYS: Final[Mapping[BriefingFrequency, Mapping[str, frozenset[int]]]] = {
    BriefingFrequency.DAILY: {
        DAILY_BRIEFING_WORKFLOW_KEY: EVERY_DAY,
        WEEKLY_DIGEST_WORKFLOW_KEY: SUNDAY,
    },
    BriefingFrequency.WEEKDAYS: {
        DAILY_BRIEFING_WORKFLOW_KEY: MONDAY_TO_FRIDAY,
        WEEKLY_DIGEST_WORKFLOW_KEY: SUNDAY,
    },
    BriefingFrequency.WEEKLY_ONLY: {WEEKLY_DIGEST_WORKFLOW_KEY: SUNDAY},
    BriefingFrequency.OFF: {},
}

# Idle wind-down: consecutive daily runs that found nothing to work on (no goal,
# no tracked work) before the brief warns plainly, then pauses the whole loop
# (brief, weekly digest) until a reactivation signal.
IDLE_WARN_DAYS: Final[int] = 2
IDLE_DORMANT_DAYS: Final[int] = 3
#: How long a goal question waits before a brief asks about the same goal again.
GOAL_QUESTION_REASK: Final = timedelta(days=7)
#: How long a goal's open todo sits untouched before the weekly calls it stuck.
GOAL_WORK_STALLED_AFTER: Final = timedelta(days=7)
# A new account's first days never wind down: the brief helps them get started instead.
FIRST_WEEK_DAYS: Final[int] = 7

# Deterministic per-day hue rotation of the bands-gradient hero. Coprime step
# over 360 so consecutive days are visually distinct but the sequence is stable.
HUE_ROTATION_STEP: Final[int] = 137
HUE_MAX: Final[int] = 360


def hue_for_day(day_of_year: int) -> int:
    """Deterministic bands-gradient hue (0-359) for a given day-of-year."""
    return (day_of_year * HUE_ROTATION_STEP) % HUE_MAX


class EditionFamily(StrEnum):
    """Every edition family a brief is drawn in, one per vendored explorer template.

    WEEKLY is the weekly recap's, never drawn for a daily brief; POSTAL (Air Mail) alone
    carries a city stamp. The editions package checks this set against the templates at import.
    """

    ALMANAC = "almanac"
    BAND = "band"
    BOARDINGPASS = "boardingpass"
    BROADSHEET = "broadsheet"
    EXHIBITION = "exhibition"
    FLIGHTPLAN = "flightplan"
    GRADIENT = "gradient"
    INSTRUMENT = "instrument"
    INVOICE = "invoice"
    LIBRARYCARD = "librarycard"
    MEMO = "memo"
    MENU = "menu"
    METROMAP = "metromap"
    PLAYFAIR = "playfair"
    POSTAL = "postal"
    RECEIPT = "receipt"
    SWISS = "swiss"
    WEEKLY = "weekly"


# Families whose paper lies on a desk: rendered without it, and trimmed to the paper.
DESK_FAMILIES: Final[frozenset[EditionFamily]] = frozenset(
    {
        EditionFamily.BOARDINGPASS,
        EditionFamily.INVOICE,
        EditionFamily.LIBRARYCARD,
        EditionFamily.MEMO,
        EditionFamily.MENU,
        EditionFamily.POSTAL,
        EditionFamily.RECEIPT,
    }
)
# Room around a desk family's root, in CSS px, so its widest shadow is captured whole
# (Air Mail's envelope: 44px blur, 26px drop) before the trim cuts back to the paper.
DESK_SHADOW_BLEED_PX: Final[int] = 48


# The explorer families' export density: their 540px canvas rasterizes at 3x.
EXPLORER_SCALE: Final[int] = 3


class ArtFamily(StrEnum):
    """The edition families that hang a painting (their template reads ed.art)."""

    EXHIBITION = EditionFamily.EXHIBITION.value
    BROADSHEET = EditionFamily.BROADSHEET.value
    ALMANAC = EditionFamily.ALMANAC.value


# The web page that shows the user's collected Air Mail stamps.
POSTMARKS_PATH: Final[str] = "/settings/postmarks"


class SilentTurnSource(StrEnum):
    """The silent agent turns whose prompt GAIA writes itself, so nothing in them is the user's."""

    DAY_ZERO_HELLO = "day_zero_hello"


class BriefItemSource(StrEnum):
    """What held a result for the user's next brief instead of sending it."""

    WORKFLOW = "workflow"
    TODO = "todo"


class EditionChoice(StrEnum):
    """Where the user put a daily edition family: in the rotation, out of it, or a favourite."""

    ON = "on"
    OFF = "off"
    FAVOURITE = "favourite"


# A favourite appears this many times its usual weight in each pass of the edition bag.
FAVOURITE_WEIGHT_FACTOR: Final[int] = 2


class BriefingBag(StrEnum):
    """The per-user shuffle bags kept in briefing_state (shuffle_bags)."""

    EDITION_FAMILY = "edition_family"
    STAMP_CITY = "stamp_city"
    ARTWORK = "artwork"


class WindDown(StrEnum):
    """The idle ladder's rungs: the plain warning, then the one goodbye before the loop sleeps."""

    WARN = "warn"
    FINAL = "final"


class BriefingRunOutcome(StrEnum):
    """How one scheduled briefing run ended: sent, or skipped before any delivery."""

    SENT = "sent"
    ALREADY_DELIVERED = "already_delivered"
    DORMANT = "dormant"
    WINBACK_BACKOFF = "winback_backoff"
    #: Another quiet day after a quiet note: nothing is sent until something real happens.
    SILENT = "silent"


# The workflow execution's summary for each outcome, shown in the run history.
BRIEFING_RUN_SUMMARIES: Final[dict[BriefingRunOutcome, str]] = {
    BriefingRunOutcome.SENT: "Briefing delivered",
    BriefingRunOutcome.ALREADY_DELIVERED: "Skipped: this briefing was already delivered today",
    BriefingRunOutcome.DORMANT: "Skipped: briefings are paused until the user is active again",
    BriefingRunOutcome.WINBACK_BACKOFF: "Skipped: backing off after an unanswered winback",
    BriefingRunOutcome.SILENT: "Skipped: still quiet since the last quiet note",
}

# Every surface shows the edition at most 540 CSS px wide (email column, chat
# bubble); 2x covers retina screens, so the stored variants are capped at this width.
EDITION_DELIVERY_MAX_WIDTH_PX: Final[int] = 1080

# Every edition template marks the top of its first body block, after the header, with
# this attribute: the gap where the folded letter's front panel ends.
FOLD_MARKER_SELECTOR: Final[str] = "[data-fold]"

# An edition laid on a desk marks each of its paper sheets with this attribute; the box
# they cover is recorded so the letter and the unfold show the paper alone.
PAPER_MARKER_SELECTOR: Final[str] = "[data-paper]"


# A desk family's edition is transparent around its paper; a JPG has no alpha, so it is
# flattened onto Air Mail's desk base.
EDITION_JPG_BACKGROUND: Final[tuple[int, int, int]] = (0x23, 0x26, 0x2A)
EDITION_JPG_QUALITY: Final[int] = 85

# How long a handed-out edition URL loads: an email opened weeks later still shows its image.
EDITION_URL_TTL_DAYS: Final[int] = 365
# How long a browser may reuse an edition image: a same-day re-render keeps its URL.
EDITION_IMAGE_MAX_AGE_SECONDS: Final[int] = 3_600
# How long a browser may reuse a stamp's art: one file for everyone, rebuilt rarely.
STAMP_ART_MAX_AGE_SECONDS: Final[int] = 2_592_000
# The widest a stamp is drawn on the web is 200 CSS px; the display variant is twice that.
STAMP_DISPLAY_WIDTH_PX: Final[int] = 400
STAMP_DISPLAY_MAX_BYTES: Final[int] = 70_000
STAMP_ART_CONTENT_TYPE: Final[str] = "image/webp"
# A brief's notification ranks just below an urgent one (1 is highest).
BRIEF_NOTIFICATION_PRIORITY: Final[int] = 2
BRIEF_NOTIFICATION_ACTION_LABEL: Final[str] = "Open briefing"

# An edition key's length in hex characters: 128 bits, unguessable.
EDITION_KEY_CHARS: Final[int] = 32
# Signs edition URLs apart from every other use of the instance secret.
EDITION_URL_SALT: Final[str] = "brief-edition-url"


class EditionVariant(StrEnum):
    """One stored encoding of a brief's edition, at most EDITION_DELIVERY_MAX_WIDTH_PX wide."""

    #: The app and the email: lossless, keeping a desk family's transparency.
    PNG = "png"
    #: Chat platforms, which pick photo vs document by size: compact, flattened on the desk base.
    JPG = "jpg"


# What the agent hears when a schedule it set will not run because the user is on the free plan.
BRIEFS_PAUSED_FOR_PLAN_NOTE = (
    "None of these run yet: briefs on a schedule need Pro, and the user is on the free plan."
)
