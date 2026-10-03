"""What a task that retries itself with backoff reads from its ARQ job."""

from typing import TypedDict

# A retrying task defers try n by its base delay times this to the power n-1.
RETRY_BACKOFF_BASE = 2


class ArqJobContext(TypedDict, total=False):
    """The ARQ job context, narrowed to the key a retrying task reads.

    job_try is absent only when a caller invokes the task with a bare context.
    """

    job_try: int
