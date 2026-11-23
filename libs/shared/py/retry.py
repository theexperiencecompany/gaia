"""The one retry rule for Python clients: a bounded policy per kind of call, run by tenacity.

Holds the tiers a Python client uses, at the values libs/shared/ts/src/retry.ts gives them. Nothing
retries forever: past a tier's last attempt the failure is raised, and what follows is the caller's.
"""

from collections.abc import Callable
from typing import NamedTuple

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)


class RetryPolicy(NamedTuple):
    """How often a call is retried, and the jittered backoff between tries (doubling from min_s)."""

    retries: int
    min_s: float
    max_s: float


#: Reopening a live event stream.
STREAM_RECONNECT = RetryPolicy(retries=8, min_s=0.5, max_s=10.0)

_REQUEST_TIMEOUT = 408
_TOO_MANY_REQUESTS = 429
_CLIENT_ERROR_MIN = 400
_CLIENT_ERROR_MAX = 499


def is_retryable_status(status: int) -> bool:
    """Whether a call that answered status may pass on a resend: a 4xx other than 408 and 429 never does."""
    if status in (_REQUEST_TIMEOUT, _TOO_MANY_REQUESTS):
        return True
    return not _CLIENT_ERROR_MIN <= status <= _CLIENT_ERROR_MAX


def retrying(
    policy: RetryPolicy,
    transient: Callable[[BaseException], bool],
    on_retry: Callable[[int, BaseException], None],
) -> AsyncRetrying:
    """Return the retry loop for policy: only failures transient() accepts are retried, the last is reraised.

    on_retry hears each failed attempt's number and error before the wait that follows it.
    """

    def before_sleep(state: RetryCallState) -> None:
        error = state.outcome.exception() if state.outcome else None
        if error is not None:
            on_retry(state.attempt_number, error)

    return AsyncRetrying(
        stop=stop_after_attempt(policy.retries + 1),
        wait=wait_random_exponential(multiplier=policy.min_s, max=policy.max_s),
        retry=retry_if_exception(transient),
        before_sleep=before_sleep,
        reraise=True,
    )
