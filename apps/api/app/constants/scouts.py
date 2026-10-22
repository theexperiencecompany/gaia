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
#: Safety ceiling on read-only tools bound onto one learn run (provider caps sit near 128);
#: past it the tools most relevant to SCOUT_TOOL_QUERY are bound.
SCOUT_MAX_BOUND_TOOLS: Final[int] = 100
#: What a learn run looks for, as the tool index is searched for it.
SCOUT_TOOL_QUERY: Final[str] = (
    "what needs my attention: my notifications, items assigned to me, review requests, "
    "mentions, messages waiting on my reply, open tasks due soon or overdue, pending approvals"
)

#: Safety ceiling on signals one scout may hand the brief: a runaway list, not a quota.
SCOUT_SIGNAL_CEILING: Final[int] = 50

#: What one user's scouts may spend in a UTC day before the rest are skipped. Scouts book
#: here, never into the user's own allowance, so the brief writer is never starved by them.
SCOUT_DAILY_COST_CEILING_USD: Final[float] = 0.05
#: Redis tally of that spend, per user per UTC day.
SCOUT_SPEND_KEY: Final[str] = "scouts:spend:{user_id}:{day}"
SCOUT_SPEND_TTL_SECONDS: Final[int] = 2 * 24 * 60 * 60

#: Wait before the next learn after the 1st, 2nd and 3rd-or-later failed learn in a row.
SCOUT_RELEARN_BACKOFF: Final[tuple[timedelta, ...]] = (
    timedelta(days=1),
    timedelta(days=3),
    timedelta(days=7),
)

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

#: Stored as a scout playbook's result brief: a scout is never narrated.
SCOUT_RESULT_BRIEF: Final[str] = "Replayed without narration; its items become brief signals."

#: What a learn run's graph is metered and logged as.
SCOUT_AGENT_NAME: Final[str] = "brief_scout"
#: What the one batched judge call over every replayed signal is metered as.
SIGNAL_JUDGE_LABEL: Final[str] = "brief_signal_judge"
