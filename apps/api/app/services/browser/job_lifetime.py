"""How long a browser job may live: every clock that must outlast a run is derived here.

The worker's deadline, the TTL of the job's Redis state, feed and flags, and the
relay's wait all read these two functions, so none of them can fall behind the
settings that bound a run.
"""

from app.config.settings import settings
from app.constants.browser import (
    BROWSER_AGENT_GUIDANCE_MAX,
    BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS,
    BROWSER_JOB_OVERHEAD_SECONDS,
    BROWSER_JOB_RETENTION_SECONDS,
    MAX_HANDOFFS_PER_TASK,
)


def browser_job_deadline_seconds() -> int:
    """Return the longest a browser job may legitimately run, which the worker cuts it off at.

    The run's active-work budget, every handoff and agent-guidance round it may
    make waiting its full window, and the job's own overhead.
    """
    task_budget: int = settings.BROWSER_USE_TASK_TIMEOUT_SECONDS
    handoff_window: int = settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
    return (
        task_budget
        + MAX_HANDOFFS_PER_TASK * handoff_window
        + BROWSER_AGENT_GUIDANCE_MAX * BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS
        + BROWSER_JOB_OVERHEAD_SECONDS
    )


def browser_job_ttl_seconds() -> int:
    """Return how long a job's Redis state lives: past the latest it can end, by the retention window."""
    return browser_job_deadline_seconds() + BROWSER_JOB_RETENTION_SECONDS
