"""Instant reaction: the one JEV call that decides whether GAIA taps an emoji on a user's message.

Three questions ride one request: is the user upset, what does the message do, and which emoji
fits it. GAIA reacts only when (1 - P(upset)) * (P(task) + P(sign_off)) reaches the threshold;
the emoji question never vetoes. Wording is the tuning study's V5 with the 30-emoji palette.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.constants.hil import JevFailure


class ReactionKind(StrEnum):
    """What a user's message does, as the kind question's choices name it."""

    TASK = "task"
    SIGN_OFF = "sign_off"
    NEEDS_WORDS = "needs_words"


class ReactionReason(StrEnum):
    """Why the instant reaction was or was not given; the first four are JEV answers."""

    REACTED = "reacted"
    # (1 - P(upset)) alone is under the threshold: no message that upset gets a tap.
    UPSET = "upset"
    # P(task) + P(sign_off) alone is under the threshold: the message needs a written reply.
    NEEDS_WORDS = "needs_words"
    # Each factor clears the threshold but their product does not.
    BELOW_THRESHOLD = "below_threshold"
    # JEV gave no usable answer, named as every JEV caller names it; an off-palette emoji is MALFORMED.
    UNCONFIGURED = JevFailure.UNCONFIGURED.value
    TIMEOUT = JevFailure.TIMEOUT.value
    ERROR = JevFailure.ERROR.value
    MALFORMED = JevFailure.MALFORMED.value


class ReactionOutcome(StrEnum):
    """Whether the message got an instant reaction."""

    REACTED = "reacted"
    NONE = "none"


REACTION_THRESHOLD: Final = 0.5
# Measured p50 about 250 ms; a slower answer leaves the message without an instant reaction.
REACTION_TIMEOUT_SECONDS: Final = 1.0
# The previous assistant message as JEV reads it, so a short follow-up has its context.
REACTION_CONTEXT_MAX_CHARS: Final = 300

REACTION_STATE_USER_MESSAGE: Final = "user_message"
REACTION_STATE_PREVIOUS_ASSISTANT: Final = "assistant_previous_message"

REACTION_UPSET_QUESTION_KEY: Final = "upset"
REACTION_KIND_QUESTION_KEY: Final = "kind"
REACTION_EMOJI_QUESTION_KEY: Final = "emoji"

REACTION_UPSET_INSTRUCTIONS: Final = (
    "A user just texted their personal assistant. Is the user upset, pushing back or emotional in "
    "this message? True if they are frustrated, annoyed, angry, swearing, complaining, correcting "
    "the assistant, telling it to stop or not do something, scolding it or implying its last "
    "attempt was wrong (a terse 'dude do it again', 'just do X', 'stop doing X'), criticising or "
    "rejecting what it produced, disagreeing, venting, or sharing stress, fear or a personal "
    "struggle. False if the message is neutral, friendly or plainly instructional."
)
REACTION_UPSET_CRITERIA: Final[Mapping[str, str]] = MappingProxyType(
    {
        "true": (
            "frustrated, annoyed, angry, swearing, complaining; correcting a mistake; 'no need "
            "to...', 'still make sure you don't...', 'stop', 'nah', 'meh'; criticising or "
            "rejecting output ('this sounds cringe', 'you didn't do it'); disagreeing; venting; "
            "sharing stress, fear or a personal struggle; a terse scolding order that implies the "
            "last attempt failed ('dude do it again', 'stop exploring, just use X')"
        ),
        "false": (
            "neutral, friendly or plainly instructional; no complaint, no correction, no emotion; "
            "a polite request, even a retry ('please try again', 'could you try now')"
        ),
    }
)

REACTION_KIND_INSTRUCTIONS: Final = (
    "A user just texted their personal assistant. What does the message do? 'task': hands the "
    "assistant a concrete job to go do (fetch, find, search, draft, write, send, create, cancel, "
    "remind, schedule, connect, fix, retry, rewrite); a short follow-up that extends a job in "
    "progress ('them too', 'actually do it', 'try now') is also a task. 'sign_off': a short "
    "confirmation or approval that needs no words back (yes, ok, sure, approved, go ahead, "
    "perfect, thanks). 'needs_words': a question, request for opinion, advice or explanation, a "
    "remark, a greeting, small talk, sharing information, asking for more suggestions, ideas or "
    "options ('also best restaurants too', 'give suggestions accordingly'), or pasted text with no "
    "instruction; the reply must be written out. When unsure choose 'needs_words'."
)
REACTION_KIND_CRITERIA: Final[Mapping[ReactionKind, str]] = MappingProxyType(
    {
        ReactionKind.TASK: (
            "hands the assistant a concrete job to go do (fetch, find, draft, write, send, "
            "create, cancel, remind, schedule, connect, fix, retry), or extends a job in progress "
            "('them too', 'try now')"
        ),
        ReactionKind.SIGN_OFF: (
            "short confirmation, approval or thanks that needs no words back: yes, ok, sure, "
            "approved, go ahead, perfect, thanks"
        ),
        ReactionKind.NEEDS_WORDS: (
            "a question (including about personal, health or sensitive matters), request for "
            "opinion, advice or explanation, a remark, greeting, small talk, asking for more "
            "suggestions, ideas or options, sharing information, or pasted text with no "
            "instruction; the reply must be written out"
        ),
    }
)

REACTION_EMOJI_INSTRUCTIONS: Final = (
    "Pick the single emoji that best matches what the user's message asks the assistant to do or "
    "confirms. The emoji is a quick tap-back on the user's message."
)
# Each emoji JEV may pick, with what it means; the order is the order JEV reads them in.
REACTION_PALETTE: Final[Mapping[str, str]] = MappingProxyType(
    {
        "🔎": "looking something up, searching, researching, checking a fact or their data",
        "👍": "plain agreement or approval: ok, got it, sure, will do",
        "✅": "confirming it is done or settled; thanks, perfect, great",
        "🛠️": "building, fixing, changing, updating or setting something up",
        "🗂️": "organizing files, notes, memory or todos",
        "📥": "fetching or reading emails, messages or the inbox",
        "🔧": "configuring or reconnecting an integration or setting",
        "🔌": "connecting an app, MCP server or integration",
        "🔍": "digging deep, investigating, analysing in depth",
        "🧭": "opening an app or navigating somewhere, planning a route",
        "📝": "writing, rewriting or editing text or notes",
        "✍️": "drafting an email, message, post or tweet",
        "📅": "scheduling, calendar events, meetings",
        "📋": "lists, todos, tasks, creating an issue or ticket",
        "📊": "metrics, analytics, graphs, dashboards, reports",
        "📨": "sending or replying to an email or message",
        "📤": "sending, posting or publishing something that is ready",
        "⏰": "reminders, alarms, timers",
        "🔗": "links, URLs, a page to read or summarise",
        "🎨": "design, images, visuals, UI",
        "🔐": "security, passwords, auth, permissions",
        "🌅": "morning briefing, daily summary",
        "🔁": "retrying or redoing something that failed",
        "⏳": "approving something so work continues in the background",
        "🧹": "cancelling, deleting, removing or cleaning up",
        "📸": "taking a screenshot or capturing the screen",
        "🚀": "deploying, launching or shipping",
        "🙏": "thanks, gratitude",
        "🧠": "remembering something or editing memory",
        "💻": "code, repos, GitHub, the computer or desktop",
    }
)

#: Told to comms when the instant reaction landed before its input was built: it stops a second acknowledgement.
REACTION_NOTE_TEMPLATE: Final = (
    "[GAIA already reacted {emoji} to the user's message below. That reaction is the "
    "acknowledgement: do not acknowledge it again.]"
)

#: How long a finished turn waits for its instant reaction to land: the decision bound plus one write.
REACTION_SETTLE_SECONDS: Final = REACTION_TIMEOUT_SECONDS + 1.0
