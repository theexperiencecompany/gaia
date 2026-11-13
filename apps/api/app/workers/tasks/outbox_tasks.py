"""ARQ tasks: take a submitted report into the outbox, and tell what its holds released.

A failed attempt is retried a bounded number of times, later each time; the last one fails with
the error itself. What the attempt left half done is safe to redo: every step is a compare-and-set.
"""

from collections.abc import Mapping
from datetime import timedelta

from arq import Retry
from pydantic import TypeAdapter

from app.constants.log_tags import LogTag
from app.constants.outbox import OUTBOX_TASK_MAX_TRIES, OUTBOX_TASK_RETRY_DELAY_SECONDS
from app.services.outbox.flush import flush_due, sweep_lost_flushes
from app.services.outbox.intake import process_report
from app.services.outbox.models import NoticeReport, OutboxReport, RunReport
from app.workers.task_envelope import RETRY_BACKOFF_BASE, ArqJobContext
from shared.py.wide_events import log

_REPORT: TypeAdapter[RunReport | NoticeReport] = TypeAdapter(OutboxReport)


def _retry_or_fail(ctx: ArqJobContext, task: str, error: Exception) -> Retry:
    """Return the Retry that runs the job again later, or raise the error when this was the last try."""
    job_try = ctx.get("job_try", 1)
    if job_try >= OUTBOX_TASK_MAX_TRIES:
        raise error
    defer = timedelta(seconds=OUTBOX_TASK_RETRY_DELAY_SECONDS * RETRY_BACKOFF_BASE ** (job_try - 1))
    log.warning(
        f"{LogTag.NOTIFICATION} Outbox job failed; retrying",
        task=task,
        job_try=job_try,
        error=str(error),
        error_type=type(error).__name__,
        defer_seconds=defer.total_seconds(),
    )
    return Retry(defer=defer)


async def outbox_intake(
    ctx: ArqJobContext, report: Mapping[str, object], batched: bool = False
) -> str:
    """Validate the submitted report and run it through intake; a malformed payload raises, a failed attempt retries."""
    parsed = _REPORT.validate_python(report)
    try:
        await process_report(parsed, batched=batched)
    except Exception as e:
        raise _retry_or_fail(ctx, "outbox_intake", e) from e
    return parsed.report_id


async def outbox_flush(ctx: ArqJobContext, user_id: str) -> int:
    """Tell what the user's holds have released; a job with nothing due does nothing, a failed one retries."""
    try:
        return await flush_due(user_id)
    except Exception as e:
        raise _retry_or_fail(ctx, "outbox_flush", e) from e


async def outbox_flush_sweep(_ctx: Mapping[str, object]) -> str:
    """Flush the users a lost flush job left waiting."""
    return f"{await sweep_lost_flushes()} users flushed"
