"""The four Opik dashboards, grouped by what they measure.

One board per *thing being measured*, not per project: the two external
benchmarks (LongMemEval, GAIA) each get their own, our memory suite gets its
own, and the six suites we wrote about our own product share one. Re-running is
idempotent — a board is matched by name and updated in place — and any dashboard
this file does not define is deleted, so the script is the whole truth about
what exists.

Every board answers questions rather than ranking runs:

* accuracy is broken out **by category**, never as a single number. An aggregate
  hides which capability is broken — LongMemEval's aggregate looks fine while
  ``single-session-user`` scores nothing at all;
* a **wrong answer and a broken machine are never the same bar**. Opik's own
  ``error_count`` conflates them (see ``_OUTCOME_NOTE``), so no card uses it;
* cost, tokens and latency are per category too, and latency is a distribution.

Four schema details silently produce empty panels when wrong. They are mirrored
from the frontend the container actually serves (``src/types/dashboard.ts``,
``src/lib/dashboard/layout.ts``, and each widget's zod schema):

* the grid is **6 columns wide**, not 12;
* the config must declare ``version = DASHBOARD_VERSION``. A lower version makes
  the frontend run its migrations, and the v3→v4 migration overwrites every
  widget's ``projectId`` with the empty string — the widget then renders
  "Project not configured";
* a widget resolves its project from its own ``projectId``, a project **UUID**;
  a workspace dashboard supplies no runtime project to fall back on;
* a breakdown on ``FEEDBACK_SCORES``/``DURATION``/``TOKEN_USAGE`` is dropped
  unless **exactly one** score, percentile or usage key is selected — the
  frontend needs it as the breakdown's ``subMetric``. Two scores plus a group-by
  silently renders ungrouped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import time
from typing import Literal

import opik
from opik.rest_api.types.breakdown_config_public import BreakdownConfigPublic
from opik.rest_api.types.dashboard_public import DashboardPublic
from opik.rest_api.types.trace_filter_public import TraceFilterPublic

from .seed import PROJECT_DESCRIPTIONS

# Mirrors DASHBOARD_VERSION in opik-frontend src/lib/dashboard/utils.ts.
DASHBOARD_VERSION = 4
GRID_COLUMNS = 6
PAGE_SIZE = 200
MAX_ROWS = 25
# MAX_WIDGET_HEIGHT in opik-frontend src/lib/dashboard/layout.ts; taller is clamped.
MAX_WIDGET_HEIGHT = 12

ChartKind = Literal["line", "bar", "radar"]

# A project holds two kinds of trace: the eval records this harness writes
# (`case-<id>`, carrying the run metadata) and the `evaluation_task` / scorer
# traces opik.evaluation.evaluate writes during finalize. Only the former are
# cases, so every widget is scoped to them — otherwise counts, durations and
# cost all double-count the scoring machinery.
CASE_FILTER: list[dict[str, str]] = [
    {
        "id": "case-traces",
        "field": "name",
        "type": "string",
        "operator": "starts_with",
        "key": "",
        "value": "case-",
    }
]

# The verdicts the harness journals. `failed` is the agent being wrong;
# `errored` is the harness or a backend falling over. Keeping them apart is the
# entire point of the outcome section.
PASSED, FAILED, ERRORED = "passed", "failed", "errored"

# The harness writes this verdict string into Opik's error envelope, so it shows
# up beside real exception types in an `error_type` breakdown. It is a grade, not
# a fault, and every count of "what actually broke" has to exclude it.
GATE_VERDICT = "gate score below threshold"
# What Opik names the group of traces carrying no error at all.
NO_FAULT = "No Error"

# The scores that stand for a whole case rather than one aspect of it, most
# meaningful first: the judge's verdict, the memory suite's probe aggregate, and
# the exact-match both external benchmarks are defined by. Anything else grades
# a single gate, which is a poor headline for a suite.
AGGREGATE_SCORERS: tuple[str, ...] = ("overall", "probes", "gaia_exact")

_OUTCOME_NOTE = (
    "**A wrong answer and a broken machine are counted separately here.** "
    "*Passed* / *failed* / *errored* come from each case's own verdict "
    "(`metadata.status`): failed means the agent answered and was graded wrong, "
    "errored means it never produced an answer. Opik's built-in *error count* is "
    "**not** used on any card — the harness writes both real exceptions and the "
    "verdict string `gate score below threshold` into Opik's error envelope, so "
    "that number is the two added together and means nothing on its own. "
    "*Faults by exception type* below is the honest version: every bar except "
    "`gate score below threshold` is a real fault."
)


def _status_filter(status: str) -> list[dict[str, str]]:
    """Case traces carrying one verdict."""
    return [
        *CASE_FILTER,
        {
            "id": f"status-{status}",
            "field": "metadata",
            "type": "dictionary",
            "operator": "=",
            "key": "status",
            "value": status,
        },
    ]


# A trace whose run journal no longer exists on disk was never rewritten with a
# category, and Opik charts that empty group as a bar with a blank legend entry.
# An unlabelled bar is worse than a missing one — nobody can tell whether it is a
# real category or a bug — so the per-category panels ask for categorised traces
# and the header says how many were left out. Both numbers move on their own as
# the orphans are cleared.
_HAS_CATEGORY: dict[str, str] = {
    "id": "has-category",
    "field": "metadata",
    "type": "dictionary",
    "operator": "is_not_empty",
    "key": "category",
    "value": "",
}


def _category_filter(status: str | None = None) -> list[dict[str, str]]:
    """Case traces that carry a category, optionally narrowed to one verdict."""
    base = _status_filter(status) if status else list(CASE_FILTER)
    return [*base, _HAS_CATEGORY]


@dataclass
class Widget:
    """One widget plus the grid cell it occupies."""

    id: str
    title: str
    type: str
    config: dict[str, object]
    x: int
    y: int
    w: int
    h: int

    @property
    def spec(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "type": self.type, "config": self.config}

    @property
    def layout(self) -> dict[str, object]:
        return {"i": self.id, "x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass
class Section:
    id: str
    title: str
    widgets: list[Widget] = field(default_factory=list)

    @property
    def spec(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "widgets": [w.spec for w in self.widgets],
            "layout": [w.layout for w in self.widgets],
        }


@dataclass(frozen=True)
class Suite:
    """What one project actually holds, read back from Opik.

    ``primary_scorer`` is the score that grades the most cases — the one whose
    per-category mean is worth charting. A suite that scores each case against
    bespoke probes has dozens of scorers covering one case each; charting those
    buries the signal, so only the broadest one gets the accuracy panel.
    """

    project: str
    project_id: str
    cases: int
    primary_scorer: str
    categories: dict[str, int]
    status_counts: dict[str, int]
    # Exception types on traces judged `failed` — the records that claim the
    # agent was wrong while carrying evidence the machine broke.
    failed_faults: dict[str, int]

    @property
    def label(self) -> str:
        """The suite's name without the `gaia-` prefix every project carries."""
        return self.project.removeprefix("gaia-")

    @property
    def unclassifiable(self) -> int:
        """Cases whose verdict and whose evidence disagree.

        Journalled ``failed`` — the agent answered and was graded wrong — while
        carrying a real exception, which says it never got that far. Every one of
        these is scored as a zero, so accuracy is understated by an unknown
        amount until the run is re-journalled.
        """
        return sum(self.failed_faults.values())

    @property
    def trustworthy(self) -> bool:
        """Whether the accuracy on this board can be quoted at all."""
        return not self.unclassifiable

    @property
    def uncategorised(self) -> int:
        """Cases the per-category panels leave out.

        ``categories`` is read from the same grouped query the panels run and
        drops the empty group, so whatever it does not account for is exactly
        what those panels exclude — no second query can disagree with them.
        """
        return self.cases - sum(self.categories.values())

    @property
    def thin_categories(self) -> list[str]:
        """Categories too small for a percentage to mean anything."""
        return sorted(name for name, n in self.categories.items() if n < 5)


class Panels:
    """Widget factory bound to one project, so panel definitions stay readable."""

    def __init__(self, suite: Suite) -> None:
        self.suite = suite

    def _id(self, slug: str) -> str:
        return f"{self.suite.project}-{slug}"

    def stat(
        self,
        slug: str,
        title: str,
        metric: str,
        x: int,
        y: int,
        filters: list[dict[str, str]] | None = None,
    ) -> Widget:
        """A single number from the trace-statistics endpoint.

        ``metric`` is a statistic name (``trace_count``, ``duration.p50``,
        ``total_estimated_cost_sum``, ``usage.total_tokens``) or
        ``feedback_scores.<scorer>`` for that scorer's mean.
        """
        config: dict[str, object] = {
            "source": "traces",
            "projectId": self.suite.project_id,
            "metric": metric,
            "traceFilters": CASE_FILTER if filters is None else filters,
        }
        return Widget(self._id(slug), title, "project_stats_card", config, x, y, 1, 2)

    def chart(
        self,
        slug: str,
        title: str,
        metric_type: str,
        x: int,
        y: int,
        *,
        w: int = 3,
        h: int = 4,
        kind: ChartKind = "bar",
        filters: list[dict[str, str]] | None = None,
        score: str | None = None,
        usage: str | None = None,
        duration: str | None = None,
        group_by: str | None = None,
        group_field: str = "metadata",
        over_time: bool = False,
    ) -> Widget:
        """A grouped total, or — with ``over_time`` — a time series.

        ``group_by`` names a trace-metadata key; ``group_field`` swaps that for
        one of Opik's built-in breakdowns (``error_type``, ``name``). Totals are
        the default because a suite that ran inside one day charts as a single
        lonely point on a time axis.

        The single-valued ``score`` / ``usage`` / ``duration`` arguments are not
        a simplification: a breakdown is dropped outright unless exactly one is
        selected, so the type makes the working shape the only expressible one.
        """
        config: dict[str, object] = {
            "projectId": self.suite.project_id,
            "metricType": metric_type,
            "chartType": kind,
            "traceFilters": CASE_FILTER if filters is None else filters,
        }
        if score is not None:
            config["feedbackScores"] = [score]
        if usage is not None:
            config["usageMetrics"] = [usage]
        if duration is not None:
            config["durationMetrics"] = [duration]
        if group_by is not None or group_field != "metadata":
            breakdown: dict[str, object] = {
                "field": group_field,
                "aggregateTotal": not over_time,
            }
            if group_by is not None:
                breakdown["metadataKey"] = group_by
            config["breakdown"] = breakdown
        return Widget(self._id(slug), title, "project_metrics", config, x, y, w, h)

    def durations(self, slug: str, title: str, x: int, y: int, w: int, h: int) -> Widget:
        """p50/p90/p99 together — a distribution, which a mean cannot show.

        This is the one duration panel with no breakdown, because selecting
        three percentiles is exactly what disables one.
        """
        config: dict[str, object] = {
            "projectId": self.suite.project_id,
            "metricType": "DURATION",
            "chartType": "line",
            "traceFilters": CASE_FILTER,
            "durationMetrics": ["p50", "p90", "p99"],
        }
        return Widget(self._id(slug), title, "project_metrics", config, x, y, w, h)


def markdown(wid: str, content: str, x: int, y: int, w: int, h: int) -> Widget:
    return Widget(wid, "", "text_markdown", {"content": content}, x, y, w, h)


def _category_note(suite: Suite) -> str:
    """Every category with its case count, so no percentage is read blind."""
    if not suite.categories:
        return "_No case carries a category — the accuracy breakdown cannot be drawn._"
    ranked = sorted(suite.categories.items(), key=lambda kv: (-kv[1], kv[0]))
    listing = " · ".join(f"`{name}` {n}" for name, n in ranked)
    note = f"**Cases per category** ({len(ranked)} categories): {listing}."
    thin = suite.thin_categories
    if thin:
        note += (
            f"\n\n_Read {', '.join(f'`{t}`' for t in thin)} as raw counts, not "
            "percentages — fewer than 5 cases each._"
        )
    if suite.uncategorised:
        note += (
            f"\n\n⚠️ **{suite.uncategorised} of {suite.cases} cases carry no category** and are "
            "excluded from every per-category panel below; the totals above still count them. "
            "These are traces whose run journal is no longer on disk, so nothing can say which "
            "category they belonged to. `python -m scripts.evals ingest` rebuilds the projects "
            "from the journals and clears them."
        )
    return note


def _trust_warning(suite: Suite) -> str:
    """The banner that refuses to let a contaminated accuracy read as clean.

    An honest "this cannot be quoted, N records are unclassifiable" is worth
    more than a tidy percentage computed over records that never ran. Written
    from measured counts, so it disappears by itself once the data is sound —
    there is no flag to remember to turn off.
    """
    if suite.trustworthy:
        return ""
    faults = ", ".join(
        f"`{name}` ×{n}" for name, n in sorted(suite.failed_faults.items(), key=lambda kv: -kv[1])
    )
    share = suite.unclassifiable / suite.status_counts.get(FAILED, suite.unclassifiable)
    return (
        f"# ⚠️ Accuracy on this board is NOT trustworthy\n\n"
        f"**{suite.unclassifiable} of {suite.status_counts.get(FAILED, 0)} failures "
        f"({share:.0%}) are unclassifiable.** They are journalled `failed` — meaning "
        "the agent answered and was graded wrong — while carrying a real exception, "
        "which means it never got that far. Both cannot be true, and nothing left in "
        "the data decides which: only re-running or re-journalling can.\n\n"
        f"What they actually carry: {faults}.\n\n"
        "Every one of these is averaged in as a zero, so **the real accuracy is "
        "higher than every score below, by an unknown amount**. Do not quote a "
        "number off this board until this count is zero.\n\n---\n"
    )


def _headline(suite: Suite, panels: Panels) -> Section:
    """The trust verdict, what the suite measures, and the outcome split.

    Infrastructure faults lead, before a single accuracy figure: the whole
    failure mode being designed against is an outage quietly averaged into a
    score, and a warning below the fold is a warning nobody reads.
    """
    content = (
        f"{_trust_warning(suite)}"
        f"## {suite.label}\n\n{PROJECT_DESCRIPTIONS.get(suite.project, '')}\n\n"
        f"{_OUTCOME_NOTE}\n\nOne trace is one case execution (`case-<id>`), carrying "
        "the run that produced it, the provider and model that served it, its "
        "category and its verdict. Every panel is scoped to those, so the scorer "
        "traces Opik writes while finalising an experiment never inflate a count."
        f"\n\n{_category_note(suite)}"
    )
    cards: list[tuple[str, str, str, list[dict[str, str]] | None]] = [
        ("cases", "Cases run", "trace_count", None),
        ("passed", "Passed (agent right)", "trace_count", _status_filter(PASSED)),
        ("failed", "Failed (agent wrong)", "trace_count", _status_filter(FAILED)),
        ("errored", "Errored (infra, unscored)", "trace_count", _status_filter(ERRORED)),
        ("p50", "Latency p50", "duration.p50", None),
        ("p99", "Latency p99", "duration.p99", None),
    ]
    # The category listing and both warnings are what make this card long, and
    # all three grow with the suite — so the height follows them instead of being
    # a fixed guess that either clips a wide suite or leaves a narrow one half
    # empty.
    header_height = min(
        MAX_WIDGET_HEIGHT,
        6 + len(suite.categories) // 4 + bool(suite.uncategorised) + 4 * (not suite.trustworthy),
    )
    widgets = [markdown(f"{suite.project}-about", content, 0, 0, GRID_COLUMNS, header_height)]
    for index, (slug, title, metric, filters) in enumerate(cards):
        widgets.append(
            panels.stat(slug, title, metric, index % GRID_COLUMNS, header_height, filters)
        )
    # The fault breakdown sits on the first screen rather than three sections
    # down: a suite whose backend fell over must not be discoverable only by
    # scrolling past its accuracy charts.
    widgets.append(
        panels.chart(
            "faults-headline",
            "Infrastructure faults by exception type (count) — "
            f"every bar except '{GATE_VERDICT}' is a real fault, not a wrong answer",
            "TRACE_COUNT",
            0,
            header_height + 2,
            w=6,
            h=5,
            group_field="error_type",
        )
    )
    return Section(f"{suite.project}-s1", f"{suite.label} — what this measures", widgets)


def _accuracy(suite: Suite, panels: Panels) -> Section:
    """Accuracy per category, then the counts behind each percentage."""
    widgets: list[Widget] = []
    row = 0
    # Repeated here rather than left in the header alone: this is the section
    # whose numbers get screenshotted and quoted, and a caveat two scrolls above
    # them does not travel with the screenshot.
    if not suite.trustworthy:
        widgets.append(
            markdown(
                f"{suite.project}-acc-warning",
                f"⚠️ **Every score in this section is a floor, not a measurement.** "
                f"{suite.unclassifiable} failures carry a real exception, are counted "
                "as zeros, and cannot be told apart from genuine wrong answers. The "
                "true value of each bar is higher by an unknown amount.",
                0,
                0,
                GRID_COLUMNS,
                2,
            )
        )
        row = 2
    if suite.primary_scorer:
        widgets.append(
            panels.chart(
                "acc-by-category",
                f"Mean {suite.primary_scorer} by category (0–1, higher is better)",
                "FEEDBACK_SCORES",
                0,
                row,
                w=6,
                h=5,
                filters=_category_filter(),
                score=suite.primary_scorer,
                group_by="category",
            )
        )
        row += 5
    widgets.append(
        panels.chart(
            "passed-by-category",
            "Cases PASSED by category (count)",
            "TRACE_COUNT",
            0,
            row,
            w=3,
            filters=_category_filter(PASSED),
            group_by="category",
        )
    )
    # Opik renders a chart with no matching traces as "No data", which reads as
    # a broken panel rather than as "nothing failed". A suite with a clean sweep
    # says so through the stat cards instead.
    if suite.status_counts.get(FAILED):
        widgets.append(
            panels.chart(
                "failed-by-category",
                "Cases FAILED — agent wrong — by category (count)",
                "TRACE_COUNT",
                3,
                row,
                w=3,
                filters=_category_filter(FAILED),
                group_by="category",
            )
        )
    if suite.status_counts.get(ERRORED):
        widgets.append(
            panels.chart(
                "errored-by-category",
                "Cases ERRORED — infrastructure, never scored — by category (count)",
                "TRACE_COUNT",
                0,
                row + 4,
                w=6,
                filters=_category_filter(ERRORED),
                group_by="category",
            )
        )
    return Section(
        f"{suite.project}-s2",
        f"{suite.label} — accuracy by category (an aggregate hides which capability is broken)",
        widgets,
    )


def _outcomes(suite: Suite, panels: Panels) -> Section:
    """The verdict split and who served the cases.

    The fault breakdown that used to live here now leads the board — see
    ``_headline``. One chart, one place.
    """
    widgets = [
        panels.chart(
            "by-status",
            "Cases by verdict (passed / failed / errored, count)",
            "TRACE_COUNT",
            0,
            0,
            w=6,
            group_by="status",
        ),
        panels.chart(
            "by-provider",
            "Cases by provider (count)",
            "TRACE_COUNT",
            0,
            4,
            w=3,
            group_by="provider",
        ),
        panels.chart(
            "by-model",
            "Cases by model (count)",
            "TRACE_COUNT",
            3,
            4,
            w=3,
            group_by="model",
        ),
    ]
    return Section(f"{suite.project}-s3", f"{suite.label} — verdicts and who served them", widgets)


def _failing_cases(suite: Suite, panels: Panels) -> Section:
    """The individual cases that went wrong, by name, so a trace is one click away."""
    note = (
        "**Each bar is one case.** Click a bar to open that case's traces in the "
        "project view, where its prompt, the agent's answer and every scorer's "
        "verdict are on the trace itself. Failed and errored are drawn "
        "separately on purpose: the first list is work for whoever owns the "
        "agent, the second is work for whoever owns the harness.\n\n"
        "_Opik dashboards have no table widget — a bar per case is the closest "
        "the widget API gets to listing them. Long suites are legible only after "
        "narrowing the date range._"
    )
    widgets = [markdown(f"{suite.project}-fail-note", note, 0, 0, GRID_COLUMNS, 4)]
    if suite.status_counts.get(FAILED):
        widgets.append(
            panels.chart(
                "failed-cases",
                "FAILED cases — agent answered and was graded wrong (1 bar = 1 case)",
                "TRACE_COUNT",
                0,
                4,
                w=6,
                h=6,
                filters=_status_filter(FAILED),
                group_field="name",
            )
        )
    if suite.status_counts.get(ERRORED):
        widgets.append(
            panels.chart(
                "errored-cases",
                "ERRORED cases — never produced an answer (1 bar = 1 case)",
                "TRACE_COUNT",
                0,
                10,
                w=6,
                h=6,
                filters=_status_filter(ERRORED),
                group_field="name",
            )
        )
    return Section(f"{suite.project}-s4", f"{suite.label} — the cases that went wrong", widgets)


def _cost(suite: Suite, panels: Panels) -> Section:
    """What a case costs, in money and in tokens, per category and per run."""
    widgets = [
        panels.stat("cost-total", "Paid cost, total (USD)", "total_estimated_cost_sum", 0, 0),
        panels.stat("cost-case", "Paid cost per case (USD)", "total_estimated_cost", 1, 0),
        panels.stat("tokens-case", "Tokens per case (avg)", "usage.total_tokens", 2, 0),
        panels.stat("tokens-in", "Prompt tokens per case (avg)", "usage.prompt_tokens", 3, 0),
        panels.stat(
            "tokens-out", "Completion tokens per case (avg)", "usage.completion_tokens", 4, 0
        ),
        panels.chart(
            "cost-by-category",
            "Paid cost by category (USD)",
            "COST",
            0,
            2,
            w=3,
            filters=_category_filter(),
            group_by="category",
        ),
        panels.chart(
            "tokens-by-category",
            "Total tokens by category (count)",
            "TOKEN_USAGE",
            3,
            2,
            w=3,
            filters=_category_filter(),
            usage="total_tokens",
            group_by="category",
        ),
        panels.chart(
            "cost-by-run", "Paid cost per run (USD)", "COST", 0, 6, w=3, group_by="run_id"
        ),
        panels.chart(
            "cost-by-model", "Paid cost by model (USD)", "COST", 3, 6, w=3, group_by="model"
        ),
    ]
    return Section(f"{suite.project}-s5", f"{suite.label} — cost and tokens per case", widgets)


def _latency(suite: Suite, panels: Panels) -> Section:
    """A distribution, not a mean — the tail is where the timeouts live."""
    widgets = [
        panels.durations("duration-spread", "Latency distribution p50/p90/p99 (ms)", 0, 0, 3, 4),
        panels.chart(
            "p99-by-category",
            "Latency p99 by category (ms) — the slowest tenth of a percent",
            "DURATION",
            3,
            0,
            w=3,
            filters=_category_filter(),
            duration="p99",
            group_by="category",
        ),
        panels.chart(
            "p50-by-model",
            "Latency p50 by model (ms)",
            "DURATION",
            0,
            4,
            w=3,
            duration="p50",
            group_by="model",
        ),
        panels.chart(
            "p99-by-provider",
            "Latency p99 by provider (ms)",
            "DURATION",
            3,
            4,
            w=3,
            duration="p99",
            group_by="provider",
        ),
    ]
    return Section(f"{suite.project}-s6", f"{suite.label} — latency distribution", widgets)


def _trend(suite: Suite, panels: Panels) -> Section:
    """Run against run, so a regression is visible rather than inferred."""
    widgets = [
        panels.chart(
            "cases-per-run",
            "Cases per run (count) — a short bar means the run did not finish",
            "TRACE_COUNT",
            0,
            0,
            w=3,
            group_by="run_id",
        )
    ]
    if suite.status_counts.get(FAILED):
        widgets.append(
            panels.chart(
                "failed-per-run",
                "Failed cases per run (count)",
                "TRACE_COUNT",
                3,
                0,
                w=3,
                filters=_status_filter(FAILED),
                group_by="run_id",
            )
        )
    if suite.primary_scorer:
        widgets.append(
            panels.chart(
                "score-per-run",
                f"Mean {suite.primary_scorer} per run (0–1) — a dip is a regression",
                "FEEDBACK_SCORES",
                0,
                4,
                w=3,
                score=suite.primary_scorer,
                group_by="run_id",
            )
        )
        widgets.append(
            panels.chart(
                "score-over-time",
                f"Mean {suite.primary_scorer} over time (0–1)",
                "FEEDBACK_SCORES",
                3,
                4,
                w=3,
                kind="line",
                score=suite.primary_scorer,
                filters=_category_filter(),
                over_time=True,
                group_by="category",
            )
        )
    return Section(f"{suite.project}-s7", f"{suite.label} — trend across runs", widgets)


def suite_sections(suite: Suite) -> list[Section]:
    """Every section a suite has the data to fill.

    A project with no case traces gets its header alone rather than seven
    sections of "No data" — an empty panel reads as a broken dashboard, not an
    empty suite.
    """
    panels = Panels(suite)
    sections = [_headline(suite, panels)]
    if not suite.cases:
        return sections
    if suite.categories:
        sections.append(_accuracy(suite, panels))
    sections.append(_outcomes(suite, panels))
    # A suite where nothing went wrong needs no post-mortem section.
    if suite.status_counts.get(FAILED) or suite.status_counts.get(ERRORED):
        sections.append(_failing_cases(suite, panels))
    sections.append(_cost(suite, panels))
    sections.append(_latency(suite, panels))
    sections.append(_trend(suite, panels))
    return sections


def compact_sections(suite: Suite) -> list[Section]:
    """One suite's share of a shared board: outcome, accuracy, and what broke.

    The internal board carries six suites, so each gets the panels that answer
    "is this suite healthy and which category is dragging" and leaves cost and
    latency to the roll-up — six suites × seven sections is a scroll nobody reads.
    """
    panels = Panels(suite)
    sections = [_headline(suite, panels)]
    if not suite.cases:
        return sections
    if suite.categories:
        sections.append(_accuracy(suite, panels))
    sections.append(_outcomes(suite, panels))
    # A suite where nothing went wrong needs no post-mortem section.
    if suite.status_counts.get(FAILED) or suite.status_counts.get(ERRORED):
        sections.append(_failing_cases(suite, panels))
    return sections


def _roll_up(suites: list[Suite], blurb: str) -> Section:
    """Every suite on the shared board side by side, before the per-suite detail."""
    lines = "\n".join(
        f"- **{s.label}** — {s.cases} cases · {s.status_counts.get(PASSED, 0)} passed · "
        f"{s.status_counts.get(FAILED, 0)} failed · {s.status_counts.get(ERRORED, 0)} errored · "
        f"{len(s.categories)} categories"
        + ("" if s.trustworthy else f" · ⚠️ **{s.unclassifiable} unclassifiable**")
        for s in suites
    )
    # The shared board is where someone skims six suites at once, so a suite
    # whose accuracy cannot be trusted has to be called out before the listing,
    # not left as a footnote against one bullet.
    tainted = [s for s in suites if not s.trustworthy]
    banner = (
        ""
        if not tainted
        else "# ⚠️ "
        + ", ".join(f"`{s.label}` ({s.unclassifiable})" for s in tainted)
        + " cannot be scored\n\nThose suites journalled failures that carry real "
        "exceptions — an outage recorded as a wrong answer. Their scores below are "
        "floors, not measurements. Open the suite for the exception breakdown.\n\n---\n"
    )
    content = f"{banner}{blurb}\n\n{_OUTCOME_NOTE}\n\n{lines}"
    # One row per two suites on top of the prose, rather than a flat guess: the
    # listing is the part that grows, and a card taller than its text is a screen
    # of blank nobody scrolls past.
    header_height = min(MAX_WIDGET_HEIGHT, 6 + (len(suites) + 1) // 2 + 2 * bool(tainted))
    widgets = [markdown("internal-about", content, 0, 0, GRID_COLUMNS, header_height)]
    for index, suite in enumerate(suites):
        panels = Panels(suite)
        row = header_height + (index // 2) * 2
        col = (index % 2) * 3
        widgets.append(panels.stat("ru-cases", f"{suite.label} · cases", "trace_count", col, row))
        widgets.append(
            panels.stat(
                "ru-failed",
                f"{suite.label} · failed",
                "trace_count",
                col + 1,
                row,
                _status_filter(FAILED),
            )
        )
        widgets.append(
            panels.stat(
                "ru-errored",
                f"{suite.label} · errored",
                "trace_count",
                col + 2,
                row,
                _status_filter(ERRORED),
            )
        )
    return Section("internal-s0", "Every internal suite at a glance", widgets)


@dataclass(frozen=True)
class Board:
    """One dashboard: a name, why it exists, and the projects it reads."""

    name: str
    description: str
    projects: tuple[str, ...]
    blurb: str


BOARDS: tuple[Board, ...] = (
    Board(
        name="LongMemEval",
        description=(
            "External long-term-memory benchmark: accuracy per question type, "
            "separating wrong answers from infrastructure faults."
        ),
        projects=("gaia-longmemeval",),
        blurb="",
    ),
    Board(
        name="Our memory bench",
        description=(
            "Our own memory suite: recall, consolidation, contradiction handling "
            "and abstention, broken down by probe category."
        ),
        projects=("gaia-memory",),
        blurb="",
    ),
    Board(
        name="GAIA bench",
        description=(
            "The external GAIA benchmark: accuracy per difficulty level, with "
            "infrastructure faults held apart from wrong answers."
        ),
        projects=("gaia-bench",),
        blurb="",
    ),
    Board(
        name="Internal bench",
        description=(
            "The suites we wrote about our own product — capability, quality, "
            "safety, comms, human-in-the-loop and smoke — each by category."
        ),
        projects=(
            "gaia-capability",
            "gaia-quality",
            "gaia-safety",
            "gaia-comms",
            "gaia-hil",
            "gaia-smoke",
        ),
        blurb=(
            "## Internal bench\n\nThe suites we wrote about our own product. Each "
            "suite below is scored on its own terms — capability checks whether a "
            "tool did the right thing, quality grades how the answer reads, safety "
            "probes adversarial input, comms tests the front-door agent, hil the "
            "approval gate, and smoke only the harness plumbing. There is "
            "deliberately no combined pass rate: averaging a safety refusal against "
            "a todo creation produces a number that means nothing."
        ),
    ),
)


def board_sections(board: Board, suites: dict[str, Suite]) -> list[Section]:
    """The sections for one board, from the suites it could actually read."""
    present = [suites[name] for name in board.projects if name in suites]
    if not present:
        return []
    if len(present) == 1:
        return suite_sections(present[0])
    sections = [_roll_up(present, board.blurb)]
    for suite in present:
        sections.extend(compact_sections(suite))
    return sections


def _upsert(
    client: opik.Opik, name: str, description: str, sections: list[Section]
) -> DashboardPublic:
    """Create the dashboard, or update the one already carrying this name."""
    dashboards = client.rest_client.dashboards
    config: dict[str, object] = {
        "version": DASHBOARD_VERSION,
        "sections": [s.spec for s in sections],
        "lastModified": int(time.time() * 1000),
    }
    existing = next(
        (
            d
            for d in dashboards.find_dashboards(page=1, size=PAGE_SIZE).content or []
            if d.name == name
        ),
        None,
    )
    if existing is None:
        return dashboards.create_dashboard(
            name=name, description=description, config=config, type="multi_project"
        )
    dashboards.update_dashboard(
        existing.id, name=name, description=description, config=config, type="multi_project"
    )
    return dashboards.get_dashboard_by_id(existing.id)


def _delete_others(client: opik.Opik, keep: set[str]) -> list[str]:
    """Remove every dashboard this file does not define.

    Called only once all four have been written, so a failure part-way through
    leaves the old boards in place rather than none at all.
    """
    dashboards = client.rest_client.dashboards
    stale = [
        d
        for d in dashboards.find_dashboards(page=1, size=PAGE_SIZE).content or []
        if d.name not in keep
    ]
    for dashboard in stale:
        dashboards.delete_dashboard(dashboard.id)
    return [d.name for d in stale if d.name]


def _grouped_counts(
    client: opik.Opik,
    project_id: str,
    breakdown: BreakdownConfigPublic,
    status: str | None = None,
) -> dict[str, int]:
    """How many case traces fall in each group, optionally within one verdict.

    Read through the same metrics endpoint the widgets use, so a group that
    charts empty here charts empty there too — the check and the panel cannot
    disagree.
    """
    filters = [TraceFilterPublic(field="name", operator="starts_with", key="", value="case-")]
    if status is not None:
        filters.append(
            TraceFilterPublic(field="metadata", operator="=", key="status", value=status)
        )
    response = client.rest_client.projects.get_project_metrics(
        project_id,
        metric_type="TRACE_COUNT",
        interval="TOTAL",
        interval_start=datetime(2020, 1, 1, tzinfo=UTC),
        interval_end=datetime.now(UTC) + timedelta(days=1),
        trace_filters=filters,
        breakdown=breakdown,
    )
    counts: dict[str, int] = {}
    for series in response.results or []:
        total = sum(int(point.value or 0) for point in series.data or [])
        if series.name and total:
            counts[series.name] = total
    return counts


def _metadata_counts(client: opik.Opik, project_id: str, metadata_key: str) -> dict[str, int]:
    return _grouped_counts(
        client, project_id, BreakdownConfigPublic(field="metadata", metadata_key=metadata_key)
    )


def _failed_fault_counts(client: opik.Opik, project_id: str) -> dict[str, int]:
    """Exception types carried by cases the harness journalled as ``failed``.

    This is the measurement behind the trust warning. A case marked *failed*
    says "the agent answered and was wrong"; an exception on that same trace
    says "the machine broke". Both cannot be true, and nothing left in the data
    can decide which — only re-journalling from the run can. Counting them is
    what lets a board refuse to present its accuracy as trustworthy.
    """
    counts = _grouped_counts(
        client, project_id, BreakdownConfigPublic(field="error_type"), status=FAILED
    )
    return {name: n for name, n in counts.items() if name not in (NO_FAULT, GATE_VERDICT)}


def _scorer_coverage(client: opik.Opik, project_id: str, scorer: str) -> int:
    """How many case traces carry ``scorer``."""
    graded = [
        *CASE_FILTER,
        {
            "id": f"has-{scorer}",
            "field": "feedback_scores",
            "type": "feedback_scores_number",
            "operator": "is_not_empty",
            "key": scorer,
            "value": "",
        },
    ]
    page = client.rest_client.traces.get_traces_by_project(
        project_id=project_id, page=1, size=1, filters=json.dumps(graded), truncate=True
    )
    return page.total or 0


def _primary_scorer(client: opik.Opik, project_id: str, scorers: list[str]) -> str:
    """The score whose per-category mean is worth putting at the top of a board.

    Coverage alone is not enough. The quality suite grades ``overall``,
    ``bubble_boundary`` and ``tool_card`` on the same 184 cases, so a
    widest-coverage rule breaks the three-way tie on name and heads the board
    with `bubble_boundary` — a narrow structural check — instead of the judge's
    verdict. So a suite's own aggregate verdict wins when it grades a real share
    of the suite, and coverage only decides between the rest.
    """
    if not scorers:
        return ""
    coverage = {name: _scorer_coverage(client, project_id, name) for name in scorers}
    widest = max(coverage.values(), default=0)
    if not widest:
        return ""
    for aggregate in AGGREGATE_SCORERS:
        if coverage.get(aggregate, 0) * 2 >= widest:
            return aggregate
    return min(scorers, key=lambda name: (-coverage[name], name))


def _read_suite(client: opik.Opik, project: str, project_id: str) -> Suite:
    """Read back what this project holds, using the queries the widgets run."""
    rest = client.rest_client
    stats = rest.traces.get_trace_stats(project_id=project_id, filters=json.dumps(CASE_FILTER))
    counts = {s.name: s.value for s in stats.stats or []}
    trace_count = counts.get("trace_count")
    cases = int(trace_count) if isinstance(trace_count, int | float) else 0
    scorers = sorted(
        name for key in counts if (name := key.removeprefix("feedback_scores.")) != key
    )
    return Suite(
        project=project,
        project_id=project_id,
        cases=cases,
        primary_scorer=_primary_scorer(client, project_id, scorers) if cases else "",
        categories=_metadata_counts(client, project_id, "category") if cases else {},
        status_counts=_metadata_counts(client, project_id, "status") if cases else {},
        failed_faults=_failed_fault_counts(client, project_id) if cases else {},
    )


def build(client: opik.Opik | None = None) -> None:
    """Create or refresh the four dashboards, then delete every other one."""
    opik_client = client or opik.Opik()
    found = opik_client.rest_client.projects.find_projects(page=1, size=PAGE_SIZE)
    projects = {p.name: p.id for p in found.content or [] if p.name.startswith("gaia-")}
    if not projects:
        print("[dashboards] no gaia-* projects in Opik — run a suite first")
        return

    suites = {name: _read_suite(opik_client, name, pid) for name, pid in sorted(projects.items())}
    for suite in suites.values():
        print(
            f"[dashboards] read {suite.project:<18} {suite.cases:>4} cases · "
            f"{len(suite.categories)} categories · scorer={suite.primary_scorer or '-'}"
        )

    built: set[str] = set()
    for board in BOARDS:
        sections = board_sections(board, suites)
        if not sections:
            print(f"[dashboards] {board.name}: none of {board.projects} exist in Opik — skipped")
            continue
        dashboard = _upsert(opik_client, board.name, board.description, sections)
        built.add(board.name)
        panels = sum(len(s.widgets) for s in sections)
        print(
            f"[dashboards] {board.name:<18} {len(sections):>2} sections · {panels:>3} panels · "
            f"{dashboard.id}"
        )

    if len(built) == len(BOARDS):
        removed = _delete_others(opik_client, built)
        print(
            f"[dashboards] removed {len(removed)} stale dashboard(s): {', '.join(removed) or '-'}"
        )
    else:
        print("[dashboards] not every board built — keeping the existing ones")
    print("[dashboards] open http://localhost:5173 → Dashboards")
