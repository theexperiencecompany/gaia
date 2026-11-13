"""Tasks-only comms: the names comms works tasks by, and the bounds on what it reads of one."""

from datetime import timedelta
from enum import StrEnum
from typing import Final

from app.constants.cache import ONE_HOUR_TTL

#: Provider name of the comms graph built for users on the TASKS_ONLY flag.
TASKS_ONLY_COMMS_GRAPH_NAME: Final = "comms_agent_tasks_only"

#: Marks a task that is not in the user's todo list; it is still searchable and still a tracked todo.
HIDDEN_TASK_LABEL: Final = "gaia-task-hidden"

#: A task that starts now is armed this far ahead: an open todo needs a future next check.
TASK_START_DELAY: Final = timedelta(seconds=1)

#: Open tasks listed in comms' context, and results returned by one search.
TASK_CONTEXT_LIST_MAX: Final = 8
TASK_FIND_RESULTS: Final = 5

#: The tail of a task's activity log one read returns.
TASK_ACTIVITY_CHARS: Final = 1_500


class VolatileFact(StrEnum):
    """The kinds of fact that go stale: a report older than the window for its kind is re-checked, never restated as current."""

    PRICE = "price"
    AVAILABILITY = "availability"
    STATUS = "status"
    BALANCE = "balance"
    ETA = "eta"


FACT_FRESHNESS_SECONDS: Final[dict[VolatileFact, int]] = {
    VolatileFact.PRICE: ONE_HOUR_TTL,
    VolatileFact.AVAILABILITY: ONE_HOUR_TTL // 2,
    VolatileFact.STATUS: 2 * ONE_HOUR_TTL,
    VolatileFact.BALANCE: 6 * ONE_HOUR_TTL,
    VolatileFact.ETA: ONE_HOUR_TTL,
}

#: The windows above, as one line comms reads in its rules and in every task report.
FACT_FRESHNESS_TEXT: Final = ", ".join(
    f"{kind.value} {seconds // 60} min" for kind, seconds in FACT_FRESHNESS_SECONDS.items()
)
