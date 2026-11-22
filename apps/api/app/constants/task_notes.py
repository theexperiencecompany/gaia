"""A GAIA task's notes: the sections its notes.md carries, observations.md, and how much of each a prompt reads."""

from typing import Final

from app.constants.chat import MAX_MESSAGE_LENGTH

# The sections every task's notes carry exactly once, in this order. The dated run
# trail belongs in the task's log, never here.
CANVAS_STANDING_RULES_SECTION: Final[str] = "Standing rules"
CANVAS_KEY_DETAILS_SECTION: Final[str] = "Key Details"
# What makes the task done, and where the proof will show up: what every run checks against.
CANVAS_DONE_WHEN_SECTION: Final[str] = "Done when"
CANVAS_EVIDENCE_SECTION: Final[str] = "Evidence"
CANVAS_CURRENT_STATE_SECTION: Final[str] = "Current State"
CANVAS_LEARNINGS_SECTION: Final[str] = "Learnings"
CANVAS_SECTIONS: Final[tuple[str, ...]] = (
    CANVAS_STANDING_RULES_SECTION,
    CANVAS_DONE_WHEN_SECTION,
    CANVAS_EVIDENCE_SECTION,
    CANVAS_KEY_DETAILS_SECTION,
    CANVAS_CURRENT_STATE_SECTION,
    "Context",
    CANVAS_LEARNINGS_SECTION,
)
# The Inbox desk's notes section from before observations.md; its run moves it there.
CANVAS_OBSERVATIONS_SECTION: Final[str] = "Observations"

# Most a Standing rules section may hold. Every prompt carries it whole, never
# trimmed, so a notes write that grows it past this is refused instead.
STANDING_RULES_MAX_CHARS: Final[int] = 2_000

# How much of the notes a prompt carries, head and tail kept, middle trimmed. Uncapped
# notes pushed a run past MAX_MESSAGE_LENGTH and failed it on every retry; two fifths
# of that cap leaves room for the rest of the prompt.
CANVAS_PROMPT_MAX_CHARS: Final[int] = MAX_MESSAGE_LENGTH * 2 // 5
# How much of the run trail (from the end) a run sees in its prompt: enough for the
# recent trail, bounded so a long-lived repeating task does not grow the prompt without limit.
ACTIVITY_PROMPT_TAIL_CHARS: Final[int] = 4_000

# observations.md: one block per pattern, its evidence kept across runs.
OBSERVATIONS_SENDERS_SECTION: Final[str] = "Senders"
OBSERVATIONS_RECURRING_SECTION: Final[str] = "Recurring"
OBSERVATIONS_PEOPLE_SECTION: Final[str] = "People"
OBSERVATION_CONCLUSION: Final[str] = "conclusion"
OBSERVATION_CONFIDENCE: Final[str] = "confidence"
OBSERVATION_FIRST_SEEN: Final[str] = "first seen"
OBSERVATION_LAST_SEEN: Final[str] = "last seen"
OBSERVATION_DAILY_COUNTS: Final[str] = "daily counts"
OBSERVATION_EARLIER: Final[str] = "earlier"
# When the desk last suggested a Gmail change from this pattern; it never suggests it twice.
OBSERVATION_SUGGESTED: Final[str] = "suggested"
# Days of per-day counts an entry keeps; older days fold into its "earlier" average.
OBSERVATION_DAILY_COUNT_DAYS: Final[int] = 14
# Messages from one sender in a run before it gets an entry: a one-off is not a pattern.
OBSERVATION_MIN_MESSAGES: Final[int] = 3
# Most observations.md may hold; a write past it is refused.
OBSERVATIONS_MAX_CHARS: Final[int] = 12_000
# Most of observations.md a run prompt carries; past it, the conclusions alone.
OBSERVATIONS_PROMPT_MAX_CHARS: Final[int] = 6_000
# Most of a task's Key Details its delivery decision reads.
DELIVERY_KEY_DETAILS_MAX_CHARS: Final[int] = 1500
