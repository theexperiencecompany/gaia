"""ARQ task: take a submitted report into the outbox."""

from collections.abc import Mapping

from pydantic import TypeAdapter

from app.services.outbox.intake import process_report
from app.services.outbox.models import NoticeReport, OutboxReport, RunReport

_REPORT: TypeAdapter[RunReport | NoticeReport] = TypeAdapter(OutboxReport)


async def outbox_intake(_ctx: Mapping[str, object], report: Mapping[str, object]) -> str:
    """Validate the submitted report and run it through intake; a malformed payload raises."""
    parsed = _REPORT.validate_python(report)
    await process_report(parsed)
    return parsed.report_id
