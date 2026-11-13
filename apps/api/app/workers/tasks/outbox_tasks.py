"""ARQ task: take a submitted report into the outbox."""

from collections.abc import Mapping

from pydantic import TypeAdapter

from app.services.outbox.flush import flush_due, sweep_lost_flushes
from app.services.outbox.intake import process_report
from app.services.outbox.models import NoticeReport, OutboxReport, RunReport

_REPORT: TypeAdapter[RunReport | NoticeReport] = TypeAdapter(OutboxReport)


async def outbox_intake(
    _ctx: Mapping[str, object], report: Mapping[str, object], batched: bool = False
) -> str:
    """Validate the submitted report and run it through intake; a malformed payload raises."""
    parsed = _REPORT.validate_python(report)
    await process_report(parsed, batched=batched)
    return parsed.report_id


async def outbox_flush(_ctx: Mapping[str, object], user_id: str) -> int:
    """Tell what the user's holds have released; a job with nothing due does nothing."""
    return await flush_due(user_id)


async def outbox_flush_sweep(_ctx: Mapping[str, object]) -> str:
    """Flush the users a lost flush job left waiting."""
    return f"{await sweep_lost_flushes()} users flushed"
