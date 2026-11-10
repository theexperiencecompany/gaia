"""A finish_task report as the text comms receives it.

Comms voices what the run's result says, so the structured report is rendered
into that text: every fact under its kind, what was not covered, what the user
must do, what failed. Call ids are the run's own wiring and stay out.
"""

from collections.abc import Mapping

from pydantic import ValidationError

from app.models.task_report_models import (
    FinishTaskArgs,
    ReportAnswer,
    ReportFact,
    ReportFailure,
    ReportNeedsYou,
    ReportScope,
)


def _fact_line(fact: ReportFact) -> str:
    parts = [f"- {fact.kind}: {fact.text}"]
    if fact.time:
        when = f"{fact.time.meaning} {fact.time.at}"
        parts.append(
            f"({when}; if missed: {fact.time.if_missed})" if fact.time.if_missed else f"({when})"
        )
    if fact.counterparty:
        parts.append(f"(toward {fact.counterparty})")
    if fact.quote:
        parts.append(f'(quote: "{fact.quote}")')
    if fact.unprompted:
        parts.append("(found along the way, not asked for)")
    return " ".join(parts)


def _answer_lines(answer: ReportAnswer) -> list[str]:
    lines = []
    if answer.recommendation:
        lines.append(f"Recommendation: {answer.recommendation}")
    if answer.verdict:
        lines.append(f"Verdict: {answer.verdict}")
    return lines


def _scope_line(scope: ReportScope) -> str:
    completeness = "complete" if scope.complete else "not complete"
    gaps = f" Not covered: {'; '.join(scope.gaps)}." if scope.gaps else ""
    return f"Covered: {scope.covered} ({completeness}).{gaps}"


def _needs_you_lines(needs_you: ReportNeedsYou) -> list[str]:
    expiry = f" (matters until {needs_you.expires_at})" if needs_you.expires_at else ""
    lines = [f"Needs the user ({needs_you.kind}): {needs_you.ask}{expiry}"]
    lines.extend(f"- {option.label}: {option.consequence}" for option in needs_you.options)
    return lines


def _failure_line(failure: ReportFailure) -> str:
    return f"Failure: {failure.reason} (recovery: {failure.recovery})"


def render_task_report(args: FinishTaskArgs) -> str:
    """Return the result followed by whatever the report adds, as plain text for comms."""
    sections: list[list[str]] = []
    if args.facts:
        sections.append(["Facts:", *(_fact_line(fact) for fact in args.facts)])
    if args.answer:
        sections.append(_answer_lines(args.answer))
    if args.scope:
        sections.append([_scope_line(args.scope)])
    if args.needs_you:
        sections.append(_needs_you_lines(args.needs_you))
    if args.failure:
        sections.append([_failure_line(args.failure)])
    blocks = [args.result, *("\n".join(lines) for lines in sections if lines)]
    return "\n\n".join(block for block in blocks if block)


def finish_task_content(raw_args: Mapping[str, object]) -> str:
    """Return the text a finish_task call hands to its parent.

    A report that breaks its schema still delivers the result text: the run's
    outcome review names the break, so the run is never taken as verified.
    """
    try:
        return render_task_report(FinishTaskArgs.model_validate(raw_args))
    except ValidationError:
        result = raw_args.get("result")
        return str(result) if result is not None else ""
