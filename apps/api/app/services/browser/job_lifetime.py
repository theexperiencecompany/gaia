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


def run_wall_clock_seconds(task_budget: int, handoff_window: int) -> int:
    """Return the longest a run may take: its active-work budget plus every handoff and guidance round waiting its full window."""
    return (
        task_budget
        + MAX_HANDOFFS_PER_TASK * handoff_window
        + BROWSER_AGENT_GUIDANCE_MAX * BROWSER_AGENT_GUIDANCE_TIMEOUT_SECONDS
    )


def browser_job_deadline_seconds() -> int:
    """Return the longest a browser job may legitimately run, which the worker cuts it off at: the run's wall clock and the job's own overhead."""
    task_budget: int = settings.BROWSER_USE_TASK_TIMEOUT_SECONDS
    handoff_window: int = settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
    return run_wall_clock_seconds(task_budget, handoff_window) + BROWSER_JOB_OVERHEAD_SECONDS


def browser_job_ttl_seconds() -> int:
    """Return how long a job's Redis state lives: past the latest it can end, by the retention window."""
    return browser_job_deadline_seconds() + BROWSER_JOB_RETENTION_SECONDS
