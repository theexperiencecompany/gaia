"""Brief scouts: one per connected integration, watching what needs the user now or soon."""

from datetime import timedelta
from typing import Final

#: Integrations another part of the brief already covers: mail through the inbox desk,
#: the day's events through the calendar section. A scout there would count them twice.
SCOUTED_ELSEWHERE: Final[frozenset[str]] = frozenset({"gmail", "googlecalendar"})

#: Graph steps a learn run may take; each tool call costs two (the model turn and the call).
SCOUT_LEARN_RECURSION_LIMIT: Final[int] = 24
#: Wall clock a learn run gets before it is abandoned as a skipped scout.
SCOUT_LEARN_TIMEOUT: Final = timedelta(seconds=120)
#: Wall clock one scout gets, learn or replay, before it is skipped so the next scout still runs.
SCOUT_TURN_TIMEOUT: Final = timedelta(minutes=5)
#: Scouts one brief runs at once; each holds an app connection, so the rest wait their turn.
SCOUT_CONCURRENCY: Final[int] = 4
#: Safety ceiling on read-only tools bound onto one learn run (provider caps sit near 128);
#: past it the tools most relevant to SCOUT_TOOL_QUERY are bound.
SCOUT_MAX_BOUND_TOOLS: Final[int] = 100
#: What a learn run looks for, as the tool index is searched for it.
SCOUT_TOOL_QUERY: Final[str] = (
    "what needs my attention: my notifications, items assigned to me, review requests, "
    "mentions, messages waiting on my reply, open tasks due soon or overdue, pending approvals"
)

#: Longest one criterion a scout keeps; a learn run's longer text is cut, never stored whole.
SCOUT_CRITERION_MAX_CHARS: Final[int] = 200

#: Safety ceiling on signals one scout may hand the brief: a runaway list, not a quota.
SCOUT_SIGNAL_CEILING: Final[int] = 50
#: How long the brief remembers an item no brief has seen since; the TTL index expires the rest.
SIGNAL_MEMORY_RETENTION: Final = timedelta(days=90)
#: How recently an app must say an item was created for a brief to call its first sighting new.
SIGNAL_NEW_WITHIN: Final = timedelta(days=1)

#: What one user's scouts may spend in a UTC day before the rest are skipped. Scouts book
#: here, never into the user's own allowance, so the brief writer is never starved by them.
SCOUT_DAILY_COST_CEILING_USD: Final[float] = 0.05
#: The slice of that ceiling one learn reserves before it starts: a brief's worth of
#: concurrent learns fits the day, and each later connection waits its turn in order.
SCOUT_LEARN_RESERVATION_USD: Final[float] = SCOUT_DAILY_COST_CEILING_USD / SCOUT_CONCURRENCY
#: The tally counts whole micro-dollars, so concurrent increments add up exactly.
SCOUT_SPEND_MICROS_PER_USD: Final[int] = 1_000_000
#: Redis tally of that spend, in micro-dollars, per user per UTC day.
SCOUT_SPEND_KEY: Final[str] = "scouts:spend:{user_id}:{day}"
SCOUT_SPEND_TTL_SECONDS: Final[int] = 2 * 24 * 60 * 60

#: Wait before the next learn after the 1st, 2nd and 3rd-or-later failed learn in a row.
SCOUT_RELEARN_BACKOFF: Final[tuple[timedelta, ...]] = (
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
)

#: Briefs in a row a working scout's app may fail to answer before the scout learns again:
#: an outage or rate limit passes, while calls the app now refuses for good never will.
SCOUT_REPLAY_FAILURES_BEFORE_RELEARN: Final[int] = 3

#: The ARQ task a newly connected integration enqueues so the next brief already scouts it.
LEARN_SCOUT_TASK: Final[str] = "learn_scout"

#: Keys an app names a person object by, in the order the first present one is read.
PERSON_NAME_KEYS: Final[tuple[str, ...]] = (
    "name",
    "display_name",
    "displayName",
    "full_name",
    "username",
    "login",
    "email",
    "emailAddress",
)

#: The identity keys of a connected account that name the person who connected it, never their
#: workspace or team: a person on an item holding one of these values is the user.
ACCOUNT_PERSON_KEYS: Final[frozenset[str]] = frozenset({"email", "username", "user_id"})
#: Keys an app identifies a person object by, beyond its name: the user is matched on these too.
PERSON_ID_KEYS: Final[tuple[str, ...]] = ("id", "user_id", "login", "username", "email")

#: Stored as a scout playbook's result brief: a scout is never narrated.
SCOUT_RESULT_BRIEF: Final[str] = "Replayed without narration; its items become brief signals."

#: What a learn run's graph is metered and logged as.
SCOUT_AGENT_NAME: Final[str] = "brief_scout"
