"""The report-only CSP soak behind analytics.py csp-soak: what the site serves, what PostHog holds, what to say."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

ENFORCED_HEADER = "content-security-policy"
REPORT_ONLY_HEADER = "content-security-policy-report-only"
SCRIPT_SRC = "script-src"
ENFORCE_PR = "#1765"
CLEAN_WEEKS_TO_ENFORCE = 4
RUNBOOK_URL = "https://internal.lab.heygaia.io/production/csp-soak"
RUNBOOK_LINE = f"What this means and what to do: {RUNBOOK_URL}"
TOP_SOURCES = 10
SECONDS_PER_WEEK = 7 * 86_400
# HogQL's own cap on returned rows; a result this long may be cut, so it is refused.
ROW_CAP = 50_000

# One row per (directive, blocked origin, page) over the last year of report-only
# $csp_violation events from {host}. A URL keeps its origin (default port dropped),
# a keyword (inline, eval) stays as is, and extension-injected resources are skipped.
QUERY = """
SELECT directive, blocked, page,
    countIf(timestamp > now() - INTERVAL 7 DAY) AS last_7d,
    toString(toDate(min(timestamp))) AS first_day,
    toString(today()) AS today,
    dateDiff('second', max(timestamp), now()) AS quiet_seconds
FROM (
    SELECT timestamp,
        coalesce(properties.$csp_effective_directive, properties.$csp_violated_directive) AS directive,
        replaceRegexpOne(
            coalesce(
                nullIf(extract(toString(properties.$csp_blocked_url), '^([a-z][a-z0-9+.-]*://[^/?#]+)'), ''),
                toString(properties.$csp_blocked_url)
            ),
            ':443$', ''
        ) AS blocked,
        path(toString(properties.$csp_document_url)) AS page
    FROM events
    WHERE event = '$csp_violation'
        AND properties.$csp_disposition = 'report'
        AND domain(toString(properties.$csp_document_url)) = {host}
        AND NOT match(toString(properties.$csp_blocked_url), '^[a-z-]*extension:')
        AND timestamp > now() - INTERVAL 365 DAY
)
GROUP BY directive, blocked, page
ORDER BY last_7d DESC
LIMIT 50000
"""


class Policy(StrEnum):
    """Which CSP the live site serves."""

    REPORT_ONLY = "report-only"
    ENFORCED = "enforced"
    MISSING = "missing"


def _directives(policy: str) -> set[str]:
    return {
        directive.split()[0].lower()
        for one_policy in policy.split(",")
        for directive in one_policy.split(";")
        if directive.strip()
    }


def policy_of(headers: Mapping[str, str]) -> Policy:
    """Classify a response by its CSP headers; keys must be lowercase."""
    if SCRIPT_SRC in _directives(headers.get(ENFORCED_HEADER, "")):
        return Policy.ENFORCED
    if REPORT_ONLY_HEADER in headers:
        return Policy.REPORT_ONLY
    return Policy.MISSING


@dataclass(frozen=True)
class Source:
    """One (directive, blocked origin, page) group and its violations in the last 7 days."""

    directive: str
    blocked: str
    page: str
    count: int


@dataclass(frozen=True)
class Soak:
    """What PostHog holds for the soak; day and dates are in the project's timezone."""

    violations_7d: int
    sources_7d: int
    first_day: date | None
    day: int | None
    clean_weeks: int | None
    top: Sequence[Source]


def soak_from_rows(rows: Sequence[Sequence[object]]) -> Soak:
    """Fold QUERY's rows into the soak; raise when the result may have been cut at the row cap."""
    if len(rows) >= ROW_CAP:
        raise ValueError(
            f"CSP query returned {len(rows)} rows, at HogQL's cap: the totals would be wrong"
        )
    groups = [
        (
            Source(str(d), str(b), str(p), int(str(n))),
            date.fromisoformat(str(f)),
            date.fromisoformat(str(t)),
            int(str(q)),
        )
        for d, b, p, n, f, t, q in rows
    ]
    if not groups:
        return Soak(0, 0, None, None, None, ())
    recent = [source for source, *_ in groups if source.count > 0]
    first_day = min(first for _, first, _, _ in groups)
    today = groups[0][2]
    return Soak(
        violations_7d=sum(source.count for source in recent),
        sources_7d=len({(source.directive, source.blocked) for source in recent}),
        first_day=first_day,
        day=(today - first_day).days + 1,
        clean_weeks=min(quiet for *_, quiet in groups) // SECONDS_PER_WEEK,
        top=recent[:TOP_SOURCES],
    )


def verdict(soak: Soak) -> str:
    """Say in one line whether to enforce."""
    if soak.clean_weeks is None:
        return "Keep soaking: no report-only violation has reached PostHog yet, so the report sink is unproven"
    if soak.clean_weeks >= CLEAN_WEEKS_TO_ENFORCE:
        return f"Clean for {soak.clean_weeks} weeks, ready to enforce ({ENFORCE_PR})"
    if soak.violations_7d == 0:
        return (
            f"Keep soaking: clean for {soak.clean_weeks} week(s), {CLEAN_WEEKS_TO_ENFORCE} needed"
        )
    return f"Keep soaking: {soak.sources_7d} source(s) to allow or fix"


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def soak_message(soak: Soak, host: str) -> str:
    """Render the weekly message: headline, top sources, verdict, what day 1 is, and the runbook link."""
    day = "?" if soak.day is None else str(soak.day)
    lines = [f"*CSP soak, day {day}: {soak.violations_7d} violations in 7 days*"]
    lines += [
        f"• `{_slack_escape(s.directive)}` {_slack_escape(s.blocked)} on {_slack_escape(s.page)}: {s.count}"
        for s in soak.top
    ]
    lines.append(verdict(soak))
    if soak.first_day is not None:
        lines.append(
            f"_Day 1 is {soak.first_day.isoformat()}, the first report-only violation PostHog holds"
            f" from {host}. Browser-extension reports are not counted._"
        )
    lines.append(RUNBOOK_LINE)
    return "\n".join(lines)


def enforced_message(host: str) -> str:
    """Render the one message the run that finds the policy enforced posts before it disables the workflow."""
    return (
        f"*CSP enforced, soak over*: {host} serves an enforced script-src policy."
        " The weekly soak report has switched itself off."
        f"\n{RUNBOOK_LINE}"
    )


def missing_message(host: str) -> str:
    """Render the warning for a site that serves no CSP at all."""
    return (
        f"*CSP soak broken*: {host} serves neither Content-Security-Policy-Report-Only nor an"
        " enforced script-src policy, so no violation can be reported. Check the worker's security headers."
        f"\n{RUNBOOK_LINE}"
    )
