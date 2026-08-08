"""Build the Opik dashboards for every GAIA eval project.

One dashboard per suite plus a cross-suite overview, created idempotently: a
dashboard is matched by name and updated in place, so re-running never piles up
duplicates.

Every widget config mirrors the shapes the opik-frontend itself writes
(``src/types/dashboard.ts``, ``src/lib/dashboard/templates.ts`` and the per-widget
zod schemas). Four of those details silently produce empty panels when wrong:

* the grid is **6 columns wide**, not 12 (``lib/dashboard/layout.ts``);
* the config must declare ``version = DASHBOARD_VERSION``. A lower version makes
  the frontend run its migrations, and the v3→v4 migration overwrites every
  widget's ``projectId`` with the empty string — the widget then renders
  "Project not configured";
* a widget resolves its project from its own ``projectId``, which is a project
  **UUID**; a workspace dashboard supplies no runtime project to fall back on;
* leaderboard score columns are addressed as ``feedback_scores.<name>``. A bare
  scorer name resolves to nothing and the column renders blank.

Panels are built from what each project actually holds — case-trace count,
scorer names and its own experiments are all read back from Opik — so a new suite gets a
full dashboard without touching this file, and a suite whose cases have not been
seeded yet gets the sections it can fill instead of a wall of empty charts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Literal

import opik
from opik.rest_api.types.dashboard_public import DashboardPublic

from .seed import PROJECT_DESCRIPTIONS

# Mirrors DASHBOARD_VERSION in opik-frontend src/lib/dashboard/utils.ts.
DASHBOARD_VERSION = 4
GRID_COLUMNS = 6
PAGE_SIZE = 200
MAX_ROWS = 25
MAX_SCORER_PANELS = 8
# MAX_WIDGET_HEIGHT in opik-frontend src/lib/dashboard/layout.ts; taller is clamped.
MAX_WIDGET_HEIGHT = 12

# A project holds two kinds of trace: the eval records this harness writes
# (`case-<id>`, carrying the run metadata) and the `evaluation_task` / scorer
# traces opik.evaluation.evaluate writes during finalize. Only the former are
# cases, so every project widget is scoped to them — otherwise the counts,
# durations and cost all double-count the scoring machinery.
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

DashboardType = Literal["multi_project", "experiments"]


def _status_filter(status: str) -> list[dict[str, str]]:
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
    """What a project actually contains, as read back from Opik.

    Both scorer lists matter and they are not the same set: ``trace_scorers``
    are the scores attached to case traces (what the project widgets can chart),
    ``experiment_scorers`` are the ones the experiments carry (what the
    leaderboard can rank on). A scorer that only ever runs inside ``evaluate``
    appears in the second list and not the first.
    """

    project: str
    project_id: str
    cases: int
    trace_scorers: list[str]
    experiment_scorers: list[str]
    experiment_ids: list[str]


def markdown(wid: str, content: str, x: int, y: int, w: int, h: int) -> Widget:
    return Widget(wid, "", "text_markdown", {"content": content}, x, y, w, h)


def _experiment_filter(suite: Suite) -> list[dict[str, str]]:
    """Pin an experiment widget to this project's own experiments.

    The experiments API is workspace-wide, so an unfiltered widget lists every
    suite's runs. Filtering by dataset is not enough either — suites share
    datasets (longmemeval evaluates against ``gaia-memory-cases``), so only the
    explicit id set separates them.
    """
    if not suite.experiment_ids:
        return []
    return [
        {
            "id": "experiment-ids-filter",
            "field": "experiment_ids",
            "type": "string",
            "operator": "=",
            "key": "",
            "value": ",".join(suite.experiment_ids),
        }
    ]


def leaderboard(wid: str, suite: Suite, x: int, y: int, w: int, h: int) -> Widget:
    score_columns = [f"feedback_scores.{name}" for name in suite.experiment_scorers]
    # No duration column: an experiment replays stored outputs, so its duration
    # measures the replay, not the agent. The real timings are in Cost & speed.
    columns = ["dataset_id", "created_at", "trace_count", *score_columns]
    config: dict[str, object] = {
        "filters": _experiment_filter(suite),
        "selectedColumns": columns,
        "columnsOrder": columns,
        "scoresColumnsOrder": score_columns,
        "metadataColumnsOrder": [],
        "columnsWidth": {},
        "enableRanking": bool(score_columns),
        "rankingMetric": score_columns[0] if score_columns else None,
        "rankingDirection": True,
        "maxRows": MAX_ROWS,
        "sorting": [],
    }
    return Widget(wid, "Leaderboard", "experiment_leaderboard", config, x, y, w, h)


class Panels:
    """Widget factory bound to one project, so panel definitions stay readable."""

    def __init__(self, suite: Suite) -> None:
        self.suite = suite

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

        ``metric`` is a statistic name (``trace_count``, ``error_count``,
        ``duration.p50``, ``total_estimated_cost_sum``, ``usage.total_tokens``)
        or ``feedback_scores.<scorer>`` for that scorer's mean.
        """
        config: dict[str, object] = {
            "source": "traces",
            "projectId": self.suite.project_id,
            "metric": metric,
            "traceFilters": CASE_FILTER if filters is None else filters,
        }
        return Widget(
            f"{self.suite.project}-{slug}", title, "project_stats_card", config, x, y, 1, 2
        )

    def chart(
        self,
        slug: str,
        title: str,
        metric_type: str,
        x: int,
        y: int,
        w: int = 3,
        h: int = 4,
        kind: str = "line",
        scores: list[str] | None = None,
        usage: list[str] | None = None,
        durations: list[str] | None = None,
        group_by: str | None = None,
        total: bool = False,
    ) -> Widget:
        """A time series, or — with ``total`` — a bar chart of grouped totals.

        ``group_by`` names a trace-metadata key. ``total`` collapses the time
        axis to one bucket per group, which is what turns "cases over time" into
        "cases per provider"; without it a suite that ran inside a single day
        charts as one lonely point.
        """
        config: dict[str, object] = {
            "projectId": self.suite.project_id,
            "metricType": metric_type,
            "chartType": kind,
            "traceFilters": CASE_FILTER,
        }
        if scores is not None:
            config["feedbackScores"] = scores
        if usage is not None:
            config["usageMetrics"] = usage
        if durations is not None:
            config["durationMetrics"] = durations
        if group_by is not None:
            config["breakdown"] = {
                "field": "metadata",
                "metadataKey": group_by,
                "aggregateTotal": total,
            }
        return Widget(f"{self.suite.project}-{slug}", title, "project_metrics", config, x, y, w, h)

    def experiment_scores(self, slug: str, title: str, kind: str, x: int, y: int, w: int) -> Widget:
        config: dict[str, object] = {
            "chartType": kind,
            "filters": _experiment_filter(self.suite),
            "groups": [],
            "feedbackScores": self.suite.experiment_scorers,
            "maxExperimentsCount": MAX_ROWS,
        }
        wid = f"{self.suite.project}-{slug}"
        return Widget(wid, title, "experiments_feedback_scores", config, x, y, w, 4)


def _headline(suite: Suite, panels: Panels) -> Section:
    """The suite's purpose, its headline numbers and every scorer's mean."""
    content = (
        f"## {suite.project}\n\n{PROJECT_DESCRIPTIONS.get(suite.project, '')}\n\n"
        "**How to read this.** One trace is one case execution (`case-<id>`), "
        "carrying the run that produced it, the provider and model that served "
        "it, and its verdict. Every panel below is scoped to those, so the "
        "scorer traces Opik writes while finalising an experiment never inflate "
        "a count.\n\n"
        "*Gate failures* are cases that missed an assertion, not infrastructure "
        "faults.\n\n"
        "**Every cost here is what we actually paid**, metered off each case's "
        "LLM span rather than estimated — already net of the lane discount "
        "(*Paid cost by lane discount* splits it by that percentage). The "
        "undiscounted rack rate is on each trace as `metadata.list_cost_usd`; "
        "it is the number to quote for reproducing this suite elsewhere."
    )
    # (slug, title, metric, filters) — laid out six to a row under the header,
    # so a suite with two scorers and one with nine both stay on the grid.
    cards: list[tuple[str, str, str, list[dict[str, str]] | None]] = [
        ("cases", "Cases", "trace_count", None),
        ("passed", "Passed", "trace_count", _status_filter("passed")),
        ("failed", "Failed", "trace_count", _status_filter("failed")),
        ("gate-fails", "Gate failures", "error_count", None),
        ("cost", "Cost (paid)", "total_estimated_cost_sum", None),
        ("tokens", "Avg tokens/case", "usage.total_tokens", None),
        ("p50", "Duration p50", "duration.p50", None),
        ("p99", "Duration p99", "duration.p99", None),
        *(
            (f"avg-{name}", f"avg {name}", f"feedback_scores.{name}", None)
            for name in suite.trace_scorers
        ),
    ]
    header_height = 4
    widgets = [
        markdown(f"{suite.project}-about", content, x=0, y=0, w=GRID_COLUMNS, h=header_height)
    ]
    for index, (slug, title, metric, filters) in enumerate(cards):
        widgets.append(
            panels.stat(
                slug,
                title,
                metric,
                x=index % GRID_COLUMNS,
                y=header_height + (index // GRID_COLUMNS) * 2,
                filters=filters,
            )
        )
    return Section(f"{suite.project}-s1", "At a glance", widgets)


def _outcomes(suite: Suite, panels: Panels) -> Section:
    widgets = [
        panels.chart(
            "by-status",
            "Pass vs fail",
            "TRACE_COUNT",
            0,
            0,
            w=2,
            kind="bar",
            group_by="status",
            total=True,
        ),
        panels.chart(
            "by-provider",
            "Cases by provider",
            "TRACE_COUNT",
            2,
            0,
            w=2,
            kind="bar",
            group_by="provider",
            total=True,
        ),
        panels.chart(
            "by-model",
            "Cases by model",
            "TRACE_COUNT",
            4,
            0,
            w=2,
            kind="bar",
            group_by="model",
            total=True,
        ),
        panels.chart(
            "by-run",
            "Cases per run",
            "TRACE_COUNT",
            0,
            4,
            w=3,
            kind="bar",
            group_by="run",
            total=True,
        ),
        panels.chart(
            "errored",
            "Errored vs clean",
            "TRACE_COUNT",
            3,
            4,
            w=3,
            kind="bar",
            group_by="errored",
            total=True,
        ),
        panels.chart(
            "volume",
            "Case volume over time",
            "TRACE_COUNT",
            0,
            8,
            w=3,
            kind="bar",
            group_by="status",
        ),
        panels.chart("error-rate", "Failure rate over time", "TRACE_ERROR_RATE", 3, 8, w=3),
    ]
    return Section(f"{suite.project}-s2", "Outcomes — what passed, what failed, and where", widgets)


def _scores(suite: Suite, panels: Panels) -> Section:
    """Overall trend, then every scorer split by provider and by run."""
    widgets = [
        panels.chart(
            "score-trend",
            "Score trend (all scorers)",
            "FEEDBACK_SCORES",
            0,
            0,
            w=6,
            scores=suite.trace_scorers,
        ),
    ]
    for index, name in enumerate(suite.trace_scorers):
        row = 4 + index * 4
        widgets.append(
            panels.chart(
                f"{name}-provider",
                f"{name} by provider",
                "FEEDBACK_SCORES",
                0,
                row,
                w=3,
                kind="bar",
                scores=[name],
                group_by="provider",
                total=True,
            )
        )
        widgets.append(
            panels.chart(
                f"{name}-run",
                f"{name} per run",
                "FEEDBACK_SCORES",
                3,
                row,
                w=3,
                kind="bar",
                scores=[name],
                group_by="run",
                total=True,
            )
        )
    return Section(f"{suite.project}-s3", "Scores — how well, and for whom", widgets)


def _cost(suite: Suite, panels: Panels) -> Section:
    widgets = [
        panels.chart(
            "cost-provider",
            "Cost by provider",
            "COST",
            0,
            0,
            w=2,
            kind="bar",
            group_by="provider",
            total=True,
        ),
        panels.chart(
            "cost-model",
            "Cost by model",
            "COST",
            2,
            0,
            w=2,
            kind="bar",
            group_by="model",
            total=True,
        ),
        # Every cost panel is post-discount spend. Grouping by the discount the
        # lane gave us is the only chartable form of the paid-vs-list split:
        # list price is per-case metadata, which Opik cannot sum.
        panels.chart(
            "cost-discount",
            "Paid cost by lane discount (%)",
            "COST",
            4,
            0,
            w=2,
            kind="bar",
            group_by="discount_pct",
            total=True,
        ),
        panels.chart(
            "cost-run", "Cost per run", "COST", 0, 4, w=2, kind="bar", group_by="run", total=True
        ),
        panels.chart(
            "tokens-time",
            "Token usage over time",
            "TOKEN_USAGE",
            2,
            4,
            w=2,
            kind="bar",
            usage=["prompt_tokens", "completion_tokens"],
        ),
        panels.chart(
            "tokens-provider",
            "Total tokens by provider",
            "TOKEN_USAGE",
            4,
            4,
            w=2,
            kind="bar",
            usage=["total_tokens"],
            group_by="provider",
            total=True,
        ),
        panels.chart(
            "duration",
            "Duration percentiles",
            "DURATION",
            0,
            8,
            w=3,
            durations=["p50", "p90", "p99"],
        ),
        panels.chart(
            "slowest",
            "p99 duration by provider",
            "DURATION",
            3,
            8,
            w=3,
            kind="bar",
            durations=["p99"],
            group_by="provider",
            total=True,
        ),
    ]
    return Section(f"{suite.project}-s4", "Cost & speed — what the suite burns", widgets)


def _experiments(suite: Suite, panels: Panels) -> Section:
    return Section(
        f"{suite.project}-s5",
        "Experiments — run against run",
        [
            leaderboard(f"{suite.project}-lb", suite, x=0, y=0, w=6, h=4),
            panels.experiment_scores("radar", "Score profile", "radar", x=0, y=4, w=2),
            panels.experiment_scores("bars", "Scores per experiment", "bar", x=2, y=4, w=4),
        ],
    )


def suite_sections(suite: Suite) -> list[Section]:
    """The sections this suite can actually fill.

    A project with no case traces yet (nothing seeded, or only experiment
    traces) gets its header and its leaderboard rather than four sections of
    "No data" — an empty panel reads as a broken dashboard, not an empty suite.
    """
    panels = Panels(suite)
    sections = [_headline(suite, panels)]
    if suite.cases:
        sections.append(_outcomes(suite, panels))
        if suite.trace_scorers:
            sections.append(_scores(suite, panels))
        sections.append(_cost(suite, panels))
    if suite.experiment_scorers:
        sections.append(_experiments(suite, panels))
    return sections


def overview_sections(suites: list[Suite]) -> list[Section]:
    """Cross-suite comparison: the numbers every suite has, side by side."""
    lines = "\n".join(
        f"- **{s.project}** — {PROJECT_DESCRIPTIONS.get(s.project, 'no description registered')}"
        for s in suites
    )
    content = (
        "## GAIA eval suites\n\nEvery suite that has run, on the numbers they all "
        "share. Open a suite's own dashboard for its scorers, its per-run "
        f"breakdowns and its leaderboard.\n\n{lines}"
    )
    # The index grows a bullet per suite, so the header has to grow with it —
    # a fixed height clips the last suites out of view.
    header_height = min(MAX_WIDGET_HEIGHT, 4 + len(suites) // 2)
    cards = [markdown("overview-about", content, x=0, y=0, w=GRID_COLUMNS, h=header_height)]
    charts: list[Widget] = []
    for index, suite in enumerate(suites):
        panels = Panels(suite)
        row, col = header_height + (index // 2) * 2, (index % 2) * 3
        cards.append(panels.stat("ov-cases", f"{suite.project} · cases", "trace_count", col, row))
        cards.append(
            panels.stat("ov-fails", f"{suite.project} · gate fails", "error_count", col + 1, row)
        )
        cards.append(
            panels.stat(
                "ov-cost", f"{suite.project} · cost", "total_estimated_cost_sum", col + 2, row
            )
        )
        if suite.cases:
            charts.append(
                panels.chart(
                    "ov-status",
                    f"{suite.project} — pass vs fail",
                    "TRACE_COUNT",
                    x=(len(charts) % 3) * 2,
                    y=(len(charts) // 3) * 4,
                    w=2,
                    kind="bar",
                    group_by="status",
                    total=True,
                )
            )
    every_scorer = sorted({name for s in suites for name in s.experiment_scorers})
    # No id filter: the cross-suite leaderboard ranks every experiment there is.
    ranked = Suite("all", "", 0, [], every_scorer, [])
    return [
        Section("overview-s1", "Every suite at a glance", cards),
        Section("overview-s2", "Pass rate per suite", charts),
        Section(
            "overview-s3",
            "Every experiment, ranked",
            [
                leaderboard("ov-lb", ranked, x=0, y=0, w=6, h=8),
                Panels(ranked).experiment_scores(
                    "ov-bars", "Scores across all runs", "bar", x=0, y=8, w=6
                ),
            ],
        ),
    ]


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


def _suite_scorers(client: opik.Opik, project_id: str, cases: int, scorers: list[str]) -> list[str]:
    """The scorers worth a panel of their own.

    A suite may score each case against its own bespoke checks — the memory
    suite writes one score per probe — and charting fifty single-case scorers
    buries the handful that describe the suite. So a scorer earns a panel by
    grading most of the suite; the per-case ones stay on their traces, where
    they belong. If nothing clears the bar, the widest-covering few still get
    panels rather than leaving the dashboard scoreless.
    """
    if len(scorers) <= MAX_SCORER_PANELS:
        return scorers
    coverage = {name: _scorer_coverage(client, project_id, name) for name in scorers}
    ranked = sorted(scorers, key=lambda name: (-coverage[name], name))
    broad = [name for name in ranked if coverage[name] * 2 >= cases]
    return (broad or ranked)[:MAX_SCORER_PANELS]


def _read_suite(client: opik.Opik, project: str, project_id: str) -> Suite:
    """Read back what this project holds, using the same queries the widgets run."""
    rest = client.rest_client
    stats = rest.traces.get_trace_stats(project_id=project_id, filters=json.dumps(CASE_FILTER))
    counts = {s.name: s.value for s in stats.stats or []}
    trace_count = counts.get("trace_count")
    cases = int(trace_count) if isinstance(trace_count, int | float) else 0
    trace_scorers = _suite_scorers(
        client,
        project_id,
        cases,
        sorted(name for key in counts if (name := key.removeprefix("feedback_scores.")) != key),
    )
    # Ask which experiments belong to this project rather than deriving them
    # from the project's name: a suite can evaluate against another suite's
    # dataset (longmemeval uses gaia-memory-cases), and a suite can have run
    # cases without ever finalising an experiment.
    experiments = rest.projects.find_experiments_by_project(project_id, page=1, size=PAGE_SIZE)
    found = experiments.content or []
    experiment_scorers = sorted(
        {
            score.name
            for experiment in found
            for score in experiment.feedback_scores or []
            if score.name
        }
    )
    ids = [experiment.id for experiment in found if experiment.id]
    return Suite(project, project_id, cases, trace_scorers, experiment_scorers, ids)


def build(client: opik.Opik | None = None) -> None:
    """Create or refresh every dashboard. Safe to run repeatedly."""
    opik_client = client or opik.Opik()
    found = opik_client.rest_client.projects.find_projects(page=1, size=PAGE_SIZE)
    projects = {p.name: p.id for p in found.content or [] if p.name.startswith("gaia-")}
    if not projects:
        print("[dashboards] no gaia-* projects in Opik — run a suite first")
        return

    suites = [_read_suite(opik_client, name, projects[name]) for name in sorted(projects)]
    for suite in suites:
        sections = suite_sections(suite)
        dashboard = _upsert(
            opik_client,
            f"{suite.project} — suite",
            PROJECT_DESCRIPTIONS.get(suite.project, f"Eval results for {suite.project}."),
            sections,
        )
        panels = sum(len(s.widgets) for s in sections)
        print(
            f"[dashboards] {suite.project:<18} {panels:>2} panels · {suite.cases:>4} cases · "
            f"scorers={suite.trace_scorers or '-'} · {dashboard.id}"
        )

    overview = _upsert(
        opik_client,
        "GAIA evals — all suites",
        "Cross-suite overview: volume, failures and spend for every eval suite.",
        overview_sections(suites),
    )
    print(f"[dashboards] overview across {len(suites)} suites · {overview.id}")
    print("[dashboards] open http://localhost:5173 → Dashboards")
