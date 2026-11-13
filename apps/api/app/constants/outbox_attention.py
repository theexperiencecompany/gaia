"""How much of what the outbox has to say reaches the user, and when: the Rails' limits.

Every number is the default of a user setting or a bound the Rails keep whatever the Judge
said. The user-facing ones (budget, check-in times, quiet hours, DND) live in AttentionSettings.
"""

from datetime import time
from enum import StrEnum
from typing import Final

from app.constants.cache import FIVE_MINUTES_TTL, ONE_DAY_TTL, ONE_HOUR_TTL, THIRTY_MINUTES_TTL

ATTENTION_SETTINGS_COLLECTION: Final = "attention_settings"

# --- The user's settings ---

#: Unsolicited routine messages per day; 0 leaves routine items to the check-ins.
DEFAULT_UNSOLICITED_BUDGET: Final = 6
MAX_UNSOLICITED_BUDGET: Final = 50
#: Check-in slots on the user's own clock, besides the one that opens each day when quiet hours end.
CHECKIN_DEFAULT_TIMES: Final = (time(13, 0), time(18, 0))
CHECKIN_MAX_SLOTS: Final = 6
ATTENTION_RULES_MAX: Final = 20
ATTENTION_RULE_MAX_CHARS: Final = 300

# --- Who is here ---

#: A user who wrote this recently is here: quiet hours do not hold what is told to them.
ACTIVITY_OVERRIDE_SECONDS: Final = 15 * 60
#: An answer to something the user asked is still told in quiet hours when they wrote this recently.
ANSWER_QUIET_GRACE_SECONDS: Final = THIRTY_MINUTES_TTL

# --- Unsolicited messages ---

MIN_UNSOLICITED_GAP_SECONDS: Final = THIRTY_MINUTES_TTL
#: A message about one subject that nobody answered is repeated after the first of these, then the
#: next, and after the last one only once per REPEAT_MUTE_SECONDS.
REPEAT_BACKOFF_SECONDS: Final = (ONE_DAY_TTL, 3 * ONE_DAY_TTL, 7 * ONE_DAY_TTL)
REPEAT_MUTE_SECONDS: Final = 30 * ONE_DAY_TTL
#: An item whose deliver_by is this close is told whatever the repeat back-off says.
DEADLINE_PROXIMITY_SECONDS: Final = ONE_DAY_TTL

# --- Holds ---

#: A held item is told this long before its deliver_by at the latest.
TIMELY_LEAD_SECONDS: Final = 15 * 60
#: An item waits for a named run only when the run's hit rate, and the time it would wait, allow it.
WAIT_MIN_HIT_RATE: Final = 0.5
WAIT_MAX_SECONDS: Final = 45 * 60
MAX_DEFERRALS: Final = 3
#: The oldest held item reaching this age releases everything held, whatever is still upcoming.
MAX_DAYTIME_HOLD_SECONDS: Final = 90 * 60
#: A held item this old is promoted one urgency class.
STALL_ESCALATE_AFTER_SECONDS: Final = 3 * ONE_HOUR_TTL
#: No hold outlives this; the item is told when it is reached.
MAX_HOLD_AGE_SECONDS: Final = 18 * ONE_HOUR_TTL
#: Still held at this age means a flush was lost: it is logged at error.
HELD_AGE_ALERT_SECONDS: Final = 20 * ONE_HOUR_TTL

# --- Flush ---

#: Releases that land on a shared instant (quiet end, check-in slots) are spread over this window.
FLUSH_JITTER_MAX_SECONDS: Final = 20 * 60
#: A user's return flushes what waits for a check-in after this, so the reply goes first.
RETURN_FLUSH_DELAY_SECONDS: Final = 20.0
#: The flush job of one user and instant; a held item scheduled twice is flushed once.
OUTBOX_FLUSH_TASK: Final = "outbox_flush"
OUTBOX_FLUSH_JOB_ID_PREFIX: Final = "outbox:flush:"
#: The sweep that flushes a user whose flush job was lost.
FLUSH_SWEEP_INTERVAL_MINUTES: Final = FIVE_MINUTES_TTL // 60
#: Concurrent compose calls in one process while a quiet-end herd flushes.
FLUSH_MAX_CONCURRENT_COMPOSES: Final = 4
FLUSH_COMPOSE_CONCURRENCY_KEY: Final = "outbox_flush_compose"


class HoldReason(StrEnum):
    """Why an item waits instead of being told now."""

    QUIET_HOURS = "quiet_hours"
    DND = "dnd"
    #: The creator of the producer chose a time.
    NOT_BEFORE = "not_before"
    #: Background, or routine with the day's budget spent: told at the next check-in or return.
    CHECKIN = "checkin"
    #: Told too soon after the last unsolicited message.
    GAP = "gap"
    WAIT_FOR_RUN = "wait_for_run"
