"""What a tracked todo's record says of its work: its state, its latest run report and its recent activity.

Comms reads this as level 1 of answering a follow-up. Everything is as the run filed it,
with the age of the observation beside it, so a stale volatile fact is never read as current.
"""

from collections.abc import Sequence
from datetime import datetime

from app.agents.tools.tracked_todo_formatting import format_tracked_todo_full
from app.constants.tasks import FACT_FRESHNESS_TEXT, TASK_ACTIVITY_CHARS
from app.constants.todos import CANVAS_DONE_WHEN_SECTION
from app.models.outbox_models import OutboxItemDocument
from app.models.task_report_models import ReportFact, TaskReport
from app.models.todo_models import TodoDocument
from app.services.canvas_markdown import section_body
from app.services.outbox.models import RunReport

NO_RUN_REPORTED = "No run has reported on this task yet."


def latest_run_report(items: Sequence[OutboxItemDocument]) -> RunReport | None:
    """Return the newest run report among items, which are newest first; notices are not run reports."""
    return next((item.report for item in items if isinstance(item.report, RunReport)), None)


def age_text(since: datetime, now: datetime) -> str:
    """Say how long ago since was, in the largest whole unit."""
    minutes = int((now - since).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 60 * 48:
        return f"{minutes // 60} h"
    return f"{minutes // (60 * 24)} d"


def _fact_line(fact: ReportFact) -> str:
    extras = [
        f"{fact.time.meaning.value} {fact.time.at}" if fact.time else None,
        f"counterparty {fact.counterparty}" if fact.counterparty else None,
        f'quote "{fact.quote}"' if fact.quote else None,
    ]
    detail = "; ".join(extra for extra in extras if extra)
    return f"- [{fact.kind.value}] {fact.text}" + (f" ({detail})" if detail else "")


def _report_lines(report: TaskReport, result: str) -> list[str]:
    lines = [f"Outcome: {report.outcome.value if report.outcome else 'not stated'}"]
    if result:
        lines.append(f"Result as the run handed it back:\n{result}")
    if report.facts:
        lines.extend(["Facts:", *(_fact_line(fact) for fact in report.facts)])
    if report.answer:
        lines.append(
            f"Answer: verdict {report.answer.verdict.value if report.answer.verdict else 'none'}; "
            f"recommendation {report.answer.recommendation or 'none'}"
        )
    if report.scope:
        gaps = "; ".join(report.scope.gaps) or "none"
        lines.append(
            f"Scope: covered {report.scope.covered} (complete: {report.scope.complete}); gaps: {gaps}"
        )
    if report.needs_you:
        lines.append(f"Needs the user: {report.needs_you.ask}")
    if report.failure:
        lines.append(
            f"Failure: {report.failure.reason.value} (recovery {report.failure.recovery.value})"
        )
    return lines


def render_task_report(
    todo: TodoDocument, items: Sequence[OutboxItemDocument], now: datetime
) -> str:
    """Render the task's state and the latest run report with its age, for a follow-up answered at level 1."""
    lines = [format_tracked_todo_full(todo, now)]
    if done_when := section_body(todo.canvas_content, CANVAS_DONE_WHEN_SECTION):
        lines.append(f"Done when:\n{done_when}")
    run = latest_run_report(items)
    if run is None:
        lines.append(NO_RUN_REPORTED)
    else:
        lines.append(
            f"Latest report, observed {age_text(run.occurred_at, now)} ago "
            f"({run.occurred_at.isoformat(timespec='minutes')}). Volatile facts older than their "
            f"window ({FACT_FRESHNESS_TEXT}) are not current: re-check them."
        )
        lines.extend(_report_lines(run.report, run.result))
    if todo.activity_content:
        lines.append(f"Recent activity:\n{todo.activity_content[-TASK_ACTIVITY_CHARS:]}")
    return "\n\n".join(lines)
