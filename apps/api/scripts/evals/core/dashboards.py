"""The four Opik dashboards — an information design, not a chart dump.

One board per *thing being measured*: the two external benchmarks (LongMemEval,
GAIA) each get one, our memory suite gets one, and the six suites we wrote about
our own product share one. Re-running is idempotent — a board is matched by name
and updated in place — and any dashboard this file does not define is deleted,
so this module is the whole truth about what exists.

Three rules decide what gets built, and they are the reason the previous version
was unreadable:

**Nothing is drawn that was not measured first.** :func:`read_suite` runs the
exact query each candidate panel would run, and a panel is emitted only when its
own query came back with rows. There is no panel that *should* have data. This
is what removes "No data" from the boards: a sub-metric that does not exist in a
project (``overall`` is absent from LongMemEval), a breakdown with no groups, a
gate nothing scored — each one silently produced an empty card before, and now
simply is not created.

**A hard panel budget of** :data:`PANEL_BUDGET` **per board.** The old internal
board carried 125 widgets across 25 sections; the four boards together carried
211. Every one of them is a live query that the frontend also *re-polls every 30
seconds*, against a browser that will open six connections to the host — which
is why the boards appeared to hang with most panels stuck loading. The
individual queries were never slow (measured: 0.01–0.13s each); there were
simply two hundred of them. Anything a project's own trace list already shows —
a bar per case, cost per run, per-model latency — is not repeated here.

**Numbers that never move belong in prose, not in a panel.** The pass rate, the
cost, the latency and the category census are measured at build time and written
into the board's header text. Text cannot fail to load, cannot say "No data",
and costs no query. Panels are reserved for what the reader will want to slice
by date or click through into.

Five schema facts silently produce empty or unreadable panels when wrong. They
are read from the frontend the container actually serves (``App-*.js``), not
assumed:

* the grid is **6 columns wide**, not 12;
* the config must declare ``version = DASHBOARD_VERSION``. A lower version makes
  the frontend run its migrations, and the v3→v4 migration overwrites every
  widget's ``projectId`` with an empty string — the widget then renders "Project
  not configured";
* a widget resolves its project from its own ``projectId``, a project **UUID**;
  a workspace dashboard supplies no runtime project to fall back on;
* a chart shows **whole-period totals only when its breakdown carries a
  sub-metric and ``aggregateTotal``**. The frontend derives the sub-metric from
  a single selected score/percentile/usage key, so a breakdown next to two
  selected scores is dropped *and* the chart falls back to the dashboard's date
  interval — which is daily. That is why every breakdown chart here selects
  exactly one score;
* a stat card whose filter matches nothing gets an **empty stats array** back
  and renders "No data available" — not "0". A zero has to come from a metric
  that is always present (``error_count``), never from a filtered count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import math
import time
from typing import Literal

import opik
from opik.rest_api.types.breakdown_config_public import BreakdownConfigPublic
from opik.rest_api.types.dashboard_public import DashboardPublic
from opik.rest_api.types.percentage_values_public import PercentageValuesPublic
from opik.rest_api.types.project_metric_response_public import ProjectMetricResponsePublic
from opik.rest_api.types.trace_filter_public import TraceFilterPublic
from pydantic import BaseModel, ConfigDict, Field

from .seed import PROJECT_DESCRIPTIONS

# Mirrors DASHBOARD_VERSION in the served frontend bundle.
DASHBOARD_VERSION = 4
GRID_COLUMNS = 6
PAGE_SIZE = 200
# MAX_WIDGET_HEIGHT in the frontend's layout module; taller is clamped.
MAX_WIDGET_HEIGHT = 12
#: Live panels per board. Markdown carries no query and is not counted.
PANEL_BUDGET = 12
#: Roughly how many characters of prose fit on one line of one grid column —
#: used to size a text card to its own content.
CHARS_PER_COLUMN = 16
#: A panel slower than this is not worth its place on a board.
SLOW_PANEL_SECONDS = 5.0
#: The frontend's default range is "past 30 days", starting 29 days back, which
#: also fixes its interval at DAILY. Verification has to use the same window or
#: it proves something the reader will never see.
DEFAULT_RANGE_DAYS = 29

ChartKind = Literal["line", "bar"]

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

# The verdicts `runner._status_from_scores` writes. `failed` is the agent being
# wrong, `errored` is the machine falling over, `skipped` is the harness
# declining to attempt a case the benchmark asked for.
PASSED, FAILED, ERRORED, SKIPPED = "passed", "failed", "errored", "skipped"
STATUS_MEANINGS: dict[str, str] = {
    PASSED: "every gate the case declares scored ≥ 0.5",
    FAILED: "the agent answered and at least one gate scored below 0.5",
    ERRORED: "no answer was produced — a crash, timeout or dead backend",
    SKIPPED: "the harness declined to attempt the case; scored zero, still counted",
}

# What Opik names the group of traces carrying no error at all.
NO_FAULT = "No Error"
# The metrics endpoint returns at most ten groups and lumps the rest under this
# name. It is a remainder, not a category — printing it in a category listing
# invents one that does not exist, and counting it as a category understates how
# many there really are.
OTHERS_GROUP = "__others__"

# The scores that stand for a whole case rather than one aspect of it, most
# meaningful first. Anything else grades a single gate, which is a poor headline.
AGGREGATE_SCORERS: tuple[str, ...] = ("overall", "probes", "gaia_exact")

#: What every shared score actually checks, in the reader's words rather than
#: the scorer's name. A board that plots `bubble_boundary` without this is the
#: complaint that started this rewrite. Sourced one-for-one from the scorer that
#: implements each name (``core/scorers.py``, ``core/prompt_gates.py``, and the
#: per-suite gates) — a name absent here is deliberately not charted.
SCORE_MEANINGS: dict[str, str] = {
    "overall": (
        "the mean of the case's own gates — the share of its checks that passed. "
        "**Not the pass rate**: a case with 4 of 5 gates green scores 0.8 here and "
        "still counts as failed"
    ),
    "gaia_exact": "the benchmark's exact-match verdict on the final answer (1 = correct)",
    "probes": "the share of that scenario's recall probes the memory engine answered",
    "communicate": "every string the case requires was actually relayed to the user",
    "must_not_communicate": "none of the strings the case forbids was said to the user",
    "delegation": "the turn delegated to the executor exactly when it should have",
    "tool_call_correctness": "every expected tool call happened, with the arguments demanded",
    "no_forbidden_tools": "none of the tools the case names was called",
    "end_state": "the world changed as the ground truth demands (τ-bench end-state gate)",
    "bubble_boundary": "every assistant message is a distinct, non-empty, non-duplicated bubble",
    "tool_card": "every tool call produced a valid card entry (name present, args parse)",
    "openui": "OpenUI fences are present when expected and structurally balanced",
    "emoji_discipline": "the assistant used no emoji before the user had used one",
    "suggestion": "the reply carried a final follow-up-actions frame of 3–4 short items",
    "dash_discipline": "no em dash or en dash anywhere in the assistant's output",
    "banned_bot_phrases": "none of the phrases the prompt lists as 'they scream chatbot'",
    "internal_machinery": "internal machinery is never named to the user (the ONE ENTITY rule)",
    "internal_tags": "the internal channel tags never appear in a user-facing reply",
}

_HAS_CATEGORY: dict[str, str] = {
    "id": "has-category",
    "field": "metadata",
    "type": "dictionary",
    "operator": "is_not_empty",
    "key": "category",
    "value": "",
}


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


def _category_filter(status: str | None = None) -> list[dict[str, str]]:
    """Case traces that carry a category, optionally narrowed to one verdict.

    A trace whose run journal no longer exists on disk was never rewritten with
    a category, and Opik charts that empty group as a bar with a blank legend
    entry. An unlabelled bar is worse than a missing one, so the per-category
    panels ask for categorised traces and the header says how many were left out.
    """
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
    """Everything one project actually holds, read back from Opik.

    Every field here was produced by the same query a panel would run, which is
    what lets :func:`suite_sections` decide a panel's existence from evidence
    rather than from hope.
    """

    project: str
    project_id: str
    cases: int
    #: Verdict counts from ``metadata.status`` — the pass rate lives here, not
    #: in any feedback score.
    statuses: dict[str, int]
    #: Opik's own count of traces carrying an error envelope. The sink writes
    #: that envelope only for ``errored`` cases, so this is the honest count of
    #: machine faults and it is present (as 0) even when nothing broke.
    error_count: int
    #: Exception types on traces the harness journalled ``errored``.
    fault_types: dict[str, int]
    #: Every scorer with its whole-period mean.
    score_means: dict[str, float]
    #: Cases per category, exactly as the per-category panels will group them.
    categories: dict[str, int]
    #: The primary score's mean per category, per run and per model. Each is
    #: measured because the panel that plots it needs at least two groups to be
    #: a comparison at all — a one-bar "which is weakest" chart answers nothing.
    category_scores: dict[str, float]
    run_scores: dict[str, float]
    model_scores: dict[str, float]
    threads: int
    #: Span counts per span type, which is where tool spans will appear.
    span_types: dict[str, int]
    cost_usd: float
    tokens_per_case: float
    latency_p50_ms: float

    @property
    def label(self) -> str:
        """The suite's name without the `gaia-` prefix every project carries."""
        return self.project.removeprefix("gaia-")

    @property
    def primary_scorer(self) -> str:
        """The score that stands for a whole case here, or "" if none does."""
        return next((name for name in AGGREGATE_SCORERS if name in self.score_means), "")

    @property
    def gate_scores(self) -> dict[str, float]:
        """The shared gates this suite scored, without its case aggregate.

        Restricted to names :data:`SCORE_MEANINGS` can explain, which is what
        keeps the memory suite's 51 per-probe scores out of the legend — they
        are one score per probe of one scenario and explain nothing on their own.
        """
        return {
            name: value
            for name, value in self.score_means.items()
            if name in SCORE_MEANINGS and name != self.primary_scorer
        }

    @property
    def bespoke_scorers(self) -> int:
        """Scores private to single cases — counted in prose, never charted."""
        return sum(1 for name in self.score_means if name not in SCORE_MEANINGS)

    @property
    def pass_rate(self) -> float:
        return self.statuses.get(PASSED, 0) / self.cases if self.cases else 0.0

    @property
    def named_categories(self) -> dict[str, int]:
        """The categories Opik actually named, without the lumped remainder."""
        return {name: n for name, n in self.categories.items() if name != OTHERS_GROUP}

    @property
    def others(self) -> int:
        """Cases in categories beyond the ten the metrics endpoint will name."""
        return self.categories.get(OTHERS_GROUP, 0)

    @property
    def uncategorised(self) -> int:
        """Cases the per-category panels leave out."""
        return self.cases - sum(self.categories.values())


class Panels:
    """Widget factory bound to one project, so panel definitions stay readable."""

    def __init__(self, suite: Suite) -> None:
        self.suite = suite

    def _id(self, slug: str) -> str:
        return f"{self.suite.project}-{slug}"

    def stat(self, slug: str, title: str, metric: str, x: int, y: int, w: int = 2) -> Widget:
        """A single live number, unfiltered.

        Deliberately never filtered: a filtered stat that matches nothing comes
        back with an empty stats array and renders "No data available", which is
        precisely the dead panel this rebuild exists to remove. Counts that need
        a filter are drawn as a breakdown chart instead, where an absent group
        is simply an absent bar.
        """
        config: dict[str, object] = {
            "source": "traces",
            "projectId": self.suite.project_id,
            "metric": metric,
            "traceFilters": CASE_FILTER,
        }
        return Widget(self._id(slug), title, "project_stats_card", config, x, y, w, 2)

    def chart(
        self,
        slug: str,
        title: str,
        metric_type: str,
        x: int,
        y: int,
        *,
        w: int = 3,
        h: int = 5,
        kind: ChartKind = "bar",
        filters: list[dict[str, str]] | None = None,
        score: str | None = None,
        group_by: str | None = None,
        group_field: str = "metadata",
    ) -> Widget:
        """One grouped whole-period total per bar.

        ``group_by`` names a trace-metadata key; ``group_field`` swaps that for
        one of Opik's built-in breakdowns (``error_type``, ``name``, ``model``).
        ``aggregateTotal`` is always set, and a FEEDBACK_SCORES chart always
        selects exactly one score, because those two together are what make the
        frontend collapse the series to a single total instead of drawing one
        point per day.
        """
        breakdown: dict[str, object] = {"field": group_field, "aggregateTotal": True}
        if group_by is not None:
            breakdown["metadataKey"] = group_by
        config: dict[str, object] = {
            "projectId": self.suite.project_id,
            "metricType": metric_type,
            "chartType": kind,
            "traceFilters": CASE_FILTER if filters is None else filters,
            "breakdown": breakdown,
        }
        if score is not None:
            config["feedbackScores"] = [score]
        return Widget(self._id(slug), title, "project_metrics", config, x, y, w, h)


def markdown(wid: str, content: str, x: int, y: int, w: int) -> Widget:
    """A text card tall enough for its own content and no taller.

    The frontend renders markdown in an ``overflow-auto`` box, so content past
    the widget's height scrolls rather than being lost — but a card that has to
    be scrolled is a card that gets skimmed. Height follows the text it holds,
    wrapping at roughly the column width, and is clamped to the frontend's own
    maximum; a body longer than that is a signal to split it into two cards.
    """
    columns = max(1, CHARS_PER_COLUMN * w)
    lines = sum(1 + len(line) // columns for line in content.splitlines())
    height = min(MAX_WIDGET_HEIGHT, max(3, math.ceil(lines / 2.4) + 1))
    return Widget(wid, "", "text_markdown", {"content": content}, x, y, w, height)


def _verdict_note(suite: Suite) -> str:
    """The pass rate, spelled out, with what each verdict means."""
    present = [s for s in (PASSED, FAILED, ERRORED, SKIPPED) if suite.statuses.get(s)]
    split = " · ".join(f"**{suite.statuses[s]}** {s}" for s in present)
    lines = [
        (
            f"### {suite.statuses.get(PASSED, 0)} of {suite.cases} cases passed "
            f"— **{suite.pass_rate:.1%}**"
        ),
        "",
        (
            f"{split}. A case **passes when every gate it declares scores ≥ 0.5**; one gate "
            "below that fails the whole case."
        ),
        "",
    ]
    lines += [f"- `{s}` — {STATUS_MEANINGS[s]}" for s in present]
    note = _error_note(suite)
    if note:
        lines += ["", note]
    return "\n".join(lines)


def _error_note(suite: Suite) -> str:
    """The machine-error line, which has to survive traces written before the fix.

    ``error_count`` counts traces carrying an error envelope; the sink now
    writes one only for a case journalled ``errored``. Traces seeded before that
    fix carry an envelope on *failed* cases too, so the two numbers disagree —
    and quoting the raw count as "machine errors" would blame the backend for
    wrong answers. Comparing them says which of the two situations this is, and
    the sentence corrects itself once the project is re-seeded.
    """
    errored = suite.statuses.get(ERRORED, 0)
    if not suite.error_count and not errored:
        return ""
    if suite.error_count <= errored:
        return (
            f"⚠️ **{errored} case(s) never produced an answer.** The expected number is zero — "
            "each is a harness or backend fault rather than a wrong answer. The exception "
            "breakdown below names them; re-run those cases rather than reading them as quality."
        )
    stale = suite.error_count - errored
    return (
        f"⚠️ **{suite.error_count} traces carry an error envelope, but only {errored} are "
        f"journalled `errored`.** The sink writes that envelope for errored cases only, so the "
        f"other **{stale}** were seeded before that fix and are wrong answers wearing an "
        "error — they inflate the *Errors* column of Opik's project list and nothing else. "
        "`python -m scripts.evals ingest` rewrites them; the panels here read the verdict, "
        "not the envelope, so they are already correct."
    )


def _score_note(suite: Suite) -> str:
    """What each feedback score on this project's traces actually means."""
    if not suite.score_means:
        return "_No feedback score is attached to any case in this project._"
    lines = [
        "### What the feedback scores mean",
        "",
        (
            "Every gate is scored **0 or 1** per case, so a gate's mean *is* its pass rate: "
            "`0.82` means 82% of the cases that were checked against it passed it. The scores "
            "on this project's traces:"
        ),
        "",
    ]
    ordered = sorted(
        suite.score_means, key=lambda n: (n not in AGGREGATE_SCORERS, n not in SCORE_MEANINGS, n)
    )
    for name in ordered:
        if name not in SCORE_MEANINGS:
            continue
        lines.append(f"- **`{name}`** — {SCORE_MEANINGS[name]}. Mean {suite.score_means[name]:.2f}")
    unscored = suite.statuses.get(ERRORED, 0) + suite.statuses.get(SKIPPED, 0)
    if unscored:
        lines += [
            "",
            (
                f"A score is averaged over the cases that carry it, and **{unscored} case(s) "
                "here were never scored** — they errored or were skipped, so they are in the "
                "pass rate's denominator but not in any mean. That is why the means above "
                "read higher than the pass rate; neither number is wrong, they answer "
                "different questions."
            ),
        ]
    if suite.bespoke_scorers:
        lines.append(
            f"- _plus **{suite.bespoke_scorers}** scores private to a single case — one per "
            "recall probe of one scenario. They are deliberately not charted; "
            "`probes` is their per-case mean._"
        )
    return "\n".join(lines)


def _navigation_note(suite: Suite) -> str:
    """Where the reader clicks to get from a bar to a case's actual verdict."""
    lines = [
        "### Where to see an individual case",
        "",
        (
            "**Click any bar** below: it opens this project's trace list already filtered to "
            "that group. A trace is one case execution (`case-<id>`) and carries the prompt, "
            "the agent's answer, every scorer's value and the run that produced it — the "
            "per-case detail deliberately lives there rather than being duplicated as a "
            "hundred one-bar charts here."
        ),
    ]
    if suite.threads:
        lines += [
            "",
            (
                f"**Threads** ({suite.threads} here): a case's attempts across every run are "
                "grouped under one `thread_id` of `suite:case_id`, so the project's *Threads* "
                "tab reads as the history of a single case — use it to tell a case that always "
                "fails from one that flickers."
            ),
        ]
    else:
        lines += [
            "",
            (
                "**Threads**: once the traces are re-seeded, each carries a `thread_id` of "
                "`suite:case_id`, which groups a case's attempts across runs into one thread in "
                "the project's *Threads* tab. Nothing in this project carries one yet, so no "
                "thread panel is drawn."
            ),
        ]
    tools = {name: n for name, n in suite.span_types.items() if name != "llm"}
    if tools:
        listing = ", ".join(f"`{name}` ×{n}" for name, n in sorted(tools.items()))
        lines += [
            "",
            (
                f"**Spans**: beside the llm span, these traces carry {listing}. Open a trace to "
                "see the calls in order."
            ),
        ]
    return "\n".join(lines)


def _census_note(suite: Suite) -> str:
    """Every category with its case count, so no percentage is read blind."""
    if not suite.categories:
        return "_No case carries a category, so there is no per-category breakdown._"
    ranked = sorted(suite.named_categories.items(), key=lambda kv: (-kv[1], kv[0]))
    listing = " · ".join(f"`{name}` {n}" for name, n in ranked)
    lines = [f"**Cases per category** ({len(ranked)} shown): {listing}."]
    if suite.others:
        lines.append(
            f"A further **{suite.others} cases sit in categories beyond the ten** Opik will "
            "name in one breakdown; they are pooled as *Others* in the charts below. Open the "
            "project and group by category to see them individually."
        )
    thin = sorted(name for name, n in suite.named_categories.items() if n < 5)
    if thin:
        lines.append(
            f"_Read {', '.join(f'`{t}`' for t in thin)} as raw counts, not percentages — "
            "fewer than 5 cases each._"
        )
    if suite.uncategorised:
        lines.append(
            f"⚠️ **{suite.uncategorised} of {suite.cases} cases carry no category** and are "
            "excluded from every per-category panel; the totals still count them. Their run "
            "journal is no longer on disk, so nothing can say where they belonged — "
            "`python -m scripts.evals ingest` rebuilds the projects from the journals and "
            "clears them."
        )
    return "\n\n".join(lines)


def _cost_note(suite: Suite) -> str:
    """Cost, tokens and latency as prose — numbers nobody needs to slice."""
    parts: list[str] = []
    if suite.cost_usd:
        parts.append(
            f"**${suite.cost_usd:.2f}** total, **${suite.cost_usd / suite.cases:.4f}** per case"
            if suite.cases
            else f"**${suite.cost_usd:.2f}** total"
        )
    if suite.tokens_per_case:
        parts.append(f"**{suite.tokens_per_case:,.0f}** tokens per case")
    if suite.latency_p50_ms:
        parts.append(f"median case **{suite.latency_p50_ms / 1000:.1f}s**")
    if not parts:
        return (
            "_Cost and tokens were never measured for this suite — the ingest withholds them "
            "for runs whose token counts could not be stood behind, rather than pricing a "
            "guess. A `$0.00` panel would read as free, which is a different claim._"
        )
    return "**Cost and speed:** " + " · ".join(parts) + "."


def _built_note() -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"_Every number in this text was measured from the traces when the board was built "
        f"({stamp}) and does not move; the panels below are live and follow the date range at "
        "the top of the page. Rebuild with `uv run python -m scripts.evals dashboards`._"
    )


def _header(suite: Suite) -> tuple[str, str]:
    """The board's read-me, as two columns rather than one long scroll.

    Left is what happened and how it was graded; right is how to get from a bar
    to a case, and what the run cost. Both are text, so neither can fail to load.
    """
    verdict = "\n\n".join(
        part
        for part in [
            f"# {suite.label}",
            PROJECT_DESCRIPTIONS.get(suite.project, ""),
            _verdict_note(suite),
            _score_note(suite),
        ]
        if part
    )
    guide = "\n\n".join(
        part
        for part in [
            _navigation_note(suite),
            _census_note(suite),
            _cost_note(suite),
            _built_note(),
        ]
        if part
    )
    return verdict, guide


def _headline_panels(suite: Suite, panels: Panels, row: int) -> list[Widget]:
    """Three always-rendering cards: how much ran, what broke, how well it scored."""
    widgets = [
        panels.stat("cases", "How many case executions are in view?", "trace_count", 0, row),
        panels.stat(
            "errors",
            "Traces carrying an error envelope (expected: 0 — read the note above)",
            "error_count",
            2,
            row,
        ),
    ]
    primary = suite.primary_scorer
    if primary:
        widgets.append(
            panels.stat(
                "primary",
                f"Mean `{primary}` across every case in view (0–1)",
                f"feedback_scores.{primary}",
                4,
                row,
            )
        )
    else:
        widgets.append(panels.stat("p50", "Median case duration", "duration.p50", 4, row))
    return widgets


def suite_panels(suite: Suite, panels: Panels, row: int) -> list[Widget]:
    """Every chart this suite has the measured data to fill, in priority order.

    Each entry states the precondition that was measured in :func:`read_suite`.
    A panel with no evidence behind it is never appended, which is the whole
    mechanism preventing an empty card from reaching a board.
    """
    widgets: list[Widget] = []
    primary = suite.primary_scorer

    widgets.append(
        panels.chart(
            "verdicts",
            "How did the cases end? (count per verdict — click a bar for those traces)",
            "TRACE_COUNT",
            0,
            row,
            w=3,
            group_by="status",
        )
    )
    if len(suite.category_scores) >= 2:
        widgets.append(
            panels.chart(
                "score-by-category",
                f"Which category is weakest? (mean `{primary}`, 0–1, higher is better)",
                "FEEDBACK_SCORES",
                3,
                row,
                w=3,
                filters=_category_filter(),
                score=primary,
                group_by="category",
            )
        )
    row += 5

    if suite.statuses.get(FAILED) and len(suite.named_categories) >= 2:
        widgets.append(
            panels.chart(
                "failed-by-category",
                "Where are the wrong answers? (count of FAILED cases per category)",
                "TRACE_COUNT",
                0,
                row,
                w=3,
                filters=_category_filter(FAILED),
                group_by="category",
            )
        )
    if suite.fault_types:
        widgets.append(
            panels.chart(
                "faults",
                "What actually broke? (count of ERRORED cases per exception type)",
                "TRACE_COUNT",
                3,
                row,
                w=3,
                filters=_status_filter(ERRORED),
                group_field="error_type",
            )
        )
    row += 5

    if len(suite.run_scores) >= 2:
        widgets.append(
            panels.chart(
                "score-per-run",
                f"Did a run regress? (mean `{primary}` per run id, 0–1)",
                "FEEDBACK_SCORES",
                0,
                row,
                w=3,
                score=primary,
                group_by="run_id",
            )
        )
    if len(suite.model_scores) >= 2:
        widgets.append(
            panels.chart(
                "score-per-model",
                f"Is one model dragging? (mean `{primary}` per model, 0–1)",
                "FEEDBACK_SCORES",
                3,
                row,
                w=3,
                score=primary,
                group_by="model",
            )
        )
    return widgets


def suite_sections(suite: Suite) -> list[Section]:
    """A whole board for one suite: read-me, headline, then the questions."""
    panels = Panels(suite)
    verdict, guide = _header(suite)
    half = GRID_COLUMNS // 2
    cards = [
        markdown(f"{suite.project}-about", verdict, 0, 0, half),
        markdown(f"{suite.project}-guide", guide, half, 0, half),
    ]
    row = max(card.h for card in cards)
    widgets = [*cards, *_headline_panels(suite, panels, row)]
    intro = Section(f"{suite.project}-s1", f"{suite.label} — start here", widgets)
    if not suite.cases:
        return [intro]
    return [
        intro,
        Section(
            f"{suite.project}-s2",
            f"{suite.label} — what passed, what failed, and what broke",
            suite_panels(suite, panels, 0),
        ),
    ]


def _roll_up(suites: list[Suite], blurb: str) -> str:
    """Every suite on the shared board as one table, measured at build time."""
    rows = [
        "| suite | cases | passed | failed | errored | pass rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in suites:
        flag = " ⚠️" if s.error_count else ""
        rows.append(
            f"| **{s.label}** | {s.cases} | {s.statuses.get(PASSED, 0)} | "
            f"{s.statuses.get(FAILED, 0)} | {s.statuses.get(ERRORED, 0)}{flag} | "
            f"{s.pass_rate:.1%} |"
        )
    broken = [s for s in suites if s.statuses.get(ERRORED) or s.error_count]
    warning = (
        ""
        if not broken
        else "⚠️ **"
        + ", ".join(f"`{s.label}` ({s.statuses.get(ERRORED, 0)})" for s in broken)
        + "** hold cases that never produced an answer. The expected count is zero — those "
        "are harness or backend faults, not wrong answers, and need re-running. Each suite's "
        "own section says whether Opik's error column also counts stale envelopes."
    )
    return "\n\n".join(
        part
        for part in [
            blurb,
            "\n".join(rows),
            (
                "A case **passes when every gate it declares scores ≥ 0.5**. Each suite below "
                "opens with a written guide to its own scores, then two panels: how its cases "
                "ended, and which of its categories is weakest. Click any bar to open that "
                "group in the project's trace list, where a case's prompt, answer and every "
                "scorer's value live."
            ),
            warning,
            (
                "**Every gate is scored 0 or 1 per case, so a gate's mean is its pass rate.** "
                "`overall` is the mean of a case's own gates — the share of its checks that "
                "passed — and is therefore always at least the pass rate, never equal to it. "
                "Open a suite's project to see the gates it uses."
            ),
            _built_note(),
        ]
        if part
    )


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
            "External long-term-memory benchmark: pass rate per question type, "
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
            "The external GAIA benchmark: pass rate per difficulty level, with "
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
            "# Internal bench\n\nThe suites we wrote about our own product. Each is scored "
            "on its own terms — capability checks whether a tool did the right thing, "
            "quality grades how the answer reads, safety probes adversarial input, comms "
            "tests the front-door agent, hil the approval gate, and smoke only the harness "
            "plumbing. There is deliberately no combined pass rate: averaging a safety "
            "refusal against a todo creation produces a number that means nothing."
        ),
    ),
)


def _shared_board_sections(board: Board, suites: list[Suite]) -> list[Section]:
    """Six suites: a written guide each, and two panels each.

    A per-suite deep dive is what turned this board into 125 widgets. What a
    reader needs from a shared board is which suite is in trouble and which of
    its categories is dragging; everything past that is one click into the
    suite's own project. The guides carry what would otherwise be panels — every
    gate with its meaning and its measured pass rate — for free.
    """
    header = markdown("internal-about", _roll_up(suites, board.blurb), 0, 0, GRID_COLUMNS)
    sections = [Section("internal-s0", "Every internal suite at a glance", [header])]
    for suite in suites:
        panels = Panels(suite)
        # The score guide is text, not a panel: it costs no query, so every suite
        # can carry one without touching the budget — and a list of gate names
        # with their meaning and their measured pass rate is more use than a bar
        # chart of the same names with neither.
        guide = markdown(
            f"{suite.project}-guide",
            "\n\n".join(
                part
                for part in [_verdict_note(suite), _score_note(suite), _census_note(suite)]
                if part
            ),
            0,
            0,
            GRID_COLUMNS,
        )
        widgets = [
            guide,
            panels.chart(
                "verdicts",
                f"{suite.label}: how did the cases end? (count per verdict)",
                "TRACE_COUNT",
                0,
                guide.h,
                w=3,
                group_by="status",
            ),
        ]
        if len(suite.category_scores) >= 2:
            widgets.append(
                panels.chart(
                    "score-by-category",
                    f"{suite.label}: which category is weakest? "
                    f"(mean `{suite.primary_scorer}`, 0–1)",
                    "FEEDBACK_SCORES",
                    3,
                    guide.h,
                    w=3,
                    filters=_category_filter(),
                    score=suite.primary_scorer,
                    group_by="category",
                )
            )
        # An error panel is the one thing allowed past the budget: a suite whose
        # backend fell over must never be discoverable only by reading prose.
        if suite.fault_types:
            widgets.append(
                panels.chart(
                    "faults",
                    f"{suite.label}: what actually broke? (ERRORED cases per exception type)",
                    "TRACE_COUNT",
                    0,
                    guide.h + 5,
                    w=6,
                    filters=_status_filter(ERRORED),
                    group_field="error_type",
                )
            )
        sections.append(
            Section(
                f"{suite.project}-s1",
                f"{suite.label} — {suite.statuses.get(PASSED, 0)}/{suite.cases} passed "
                f"({suite.pass_rate:.0%})",
                widgets,
            )
        )
    return sections


def board_sections(board: Board, suites: dict[str, Suite]) -> list[Section]:
    """The sections for one board, from the suites it could actually read."""
    present = [suites[name] for name in board.projects if name in suites]
    if not present:
        return []
    if len(present) == 1:
        return suite_sections(present[0])
    return _shared_board_sections(board, present)


def _window() -> tuple[datetime, datetime]:
    """The frontend's default date window, which every read here mirrors."""
    end = datetime.now(UTC)
    return end - timedelta(days=DEFAULT_RANGE_DAYS), end


def _metrics(
    client: opik.Opik,
    project_id: str,
    metric_type: str,
    *,
    filters: list[dict[str, str]] | None = None,
    breakdown: BreakdownConfigPublic | None = None,
    total: bool = True,
) -> ProjectMetricResponsePublic:
    """Run exactly the query a widget with this shape would run."""
    start, end = _window()
    return client.rest_client.projects.get_project_metrics(
        project_id,
        metric_type=metric_type,
        interval="TOTAL" if total else "DAILY",
        interval_start=start,
        interval_end=end,
        trace_filters=[
            TraceFilterPublic(
                field=f["field"], operator=f["operator"], key=f["key"], value=f["value"]
            )
            for f in (CASE_FILTER if filters is None else filters)
        ],
        breakdown=breakdown,
    )


def _series_totals(response: ProjectMetricResponsePublic) -> dict[str, float]:
    """Each group's whole-period value, dropping groups Opik returned empty."""
    totals: dict[str, float] = {}
    for series in response.results or []:
        values = [float(p.value) for p in series.data or [] if p.value is not None]
        if series.name and values:
            totals[series.name] = sum(values)
    return totals


def _grouped(
    client: opik.Opik,
    project_id: str,
    metric_type: str,
    breakdown: BreakdownConfigPublic,
    filters: list[dict[str, str]] | None = None,
) -> dict[str, float]:
    return _series_totals(
        _metrics(client, project_id, metric_type, filters=filters, breakdown=breakdown)
    )


def _by_metadata(client: opik.Opik, project_id: str, key: str) -> dict[str, int]:
    grouped = _grouped(
        client,
        project_id,
        "TRACE_COUNT",
        BreakdownConfigPublic(field="metadata", metadata_key=key),
    )
    return {name: int(value) for name, value in grouped.items()}


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def read_suite(client: opik.Opik, project: str, project_id: str) -> Suite:
    """Measure everything a panel might need, using the panels' own queries.

    Nine queries per project, each measured at 0.01–0.13s against this backend.
    They are not an audit bolted onto the build — they *are* the build: the
    result decides which panels exist.
    """
    rest = client.rest_client
    start, end = _window()
    stats = rest.traces.get_trace_stats(
        project_id=project_id,
        filters=json.dumps(CASE_FILTER),
        from_time=start,
        to_time=end,
    )
    values = {s.name: s.value for s in stats.stats or []}
    cases = int(_number(values.get("trace_count")))
    # The percentiles arrive as one `duration` stat holding p50/p90/p99, which is
    # also how the stat card reads `duration.p50`.
    duration = values.get("duration")
    latency_p50 = _number(duration.p50) if isinstance(duration, PercentageValuesPublic) else 0.0
    if not cases:
        return Suite(
            project=project,
            project_id=project_id,
            cases=0,
            statuses={},
            error_count=0,
            fault_types={},
            score_means={},
            categories={},
            category_scores={},
            run_scores={},
            model_scores={},
            threads=0,
            span_types={},
            cost_usd=0.0,
            tokens_per_case=0.0,
            latency_p50_ms=0.0,
        )

    score_means = {
        name: _number(value)
        for key, value in values.items()
        if (name := key.removeprefix("feedback_scores.")) != key
    }
    primary = next((name for name in AGGREGATE_SCORERS if name in score_means), "")

    def primary_by(key: str, filters: list[dict[str, str]] | None = None) -> dict[str, float]:
        """The primary score grouped one way — the query its panel would run."""
        if not primary:
            return {}
        return _grouped(
            client,
            project_id,
            "FEEDBACK_SCORES",
            BreakdownConfigPublic(field="metadata", metadata_key=key, sub_metric=primary),
            filters=filters,
        )

    faults = _grouped(
        client,
        project_id,
        "TRACE_COUNT",
        BreakdownConfigPublic(field="error_type"),
        filters=_status_filter(ERRORED),
    )
    spans = _series_totals(
        rest.projects.get_project_metrics(
            project_id,
            metric_type="SPAN_COUNT",
            interval="TOTAL",
            interval_start=start,
            interval_end=end,
            breakdown=BreakdownConfigPublic(field="type"),
        )
    )
    return Suite(
        project=project,
        project_id=project_id,
        cases=cases,
        statuses=_by_metadata(client, project_id, "status"),
        error_count=int(_number(values.get("error_count"))),
        fault_types={name: int(n) for name, n in faults.items() if name != NO_FAULT},
        score_means=score_means,
        categories=_by_metadata(client, project_id, "category"),
        category_scores=primary_by("category", _category_filter()),
        run_scores=primary_by("run_id"),
        model_scores=primary_by("model"),
        threads=int(_number(values.get("thread_count"))),
        span_types={name: int(n) for name, n in spans.items()},
        cost_usd=_number(values.get("total_estimated_cost_sum")),
        tokens_per_case=_number(values.get("usage.total_tokens")),
        latency_p50_ms=latency_p50,
    )


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


@dataclass(frozen=True)
class PanelCheck:
    """One panel replayed as the reader's browser would issue it."""

    board: str
    title: str
    seconds: float
    rows: int

    @property
    def ok(self) -> bool:
        return self.rows > 0 and self.seconds < SLOW_PANEL_SECONDS


class StoredPanel(BaseModel):
    """A widget as Opik gave it back, parsed once at the boundary.

    The dashboard config crosses the API as untyped JSON, so it is validated
    here rather than read with ``.get()`` at every use — a renamed config key
    then fails loudly instead of quietly checking a panel that does not exist.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str = ""
    type: str
    project_id: str = Field(validation_alias="projectId", default="")
    metric: str = ""
    metric_type: str = Field(validation_alias="metricType", default="")
    trace_filters: list[dict[str, str]] = Field(
        validation_alias="traceFilters", default_factory=list
    )
    feedback_scores: list[str] = Field(validation_alias="feedbackScores", default_factory=list)
    breakdown_field: str = ""
    breakdown_key: str | None = None

    @classmethod
    def parse(cls, widget: dict[str, object]) -> StoredPanel:
        config = widget.get("config")
        flat: dict[str, object] = {
            "title": widget.get("title") or "",
            "type": widget.get("type"),
        }
        if isinstance(config, dict):
            flat.update(config)
            breakdown = config.get("breakdown")
            if isinstance(breakdown, dict):
                flat["breakdown_field"] = breakdown.get("field") or ""
                flat["breakdown_key"] = breakdown.get("metadataKey")
        return cls.model_validate(flat)

    @property
    def breakdown(self) -> BreakdownConfigPublic | None:
        """The breakdown as the frontend rebuilds it before querying.

        The sub-metric is not stored; the frontend derives it from the single
        selected score, and *drops the whole breakdown* when more than one is
        selected. Reproducing that here is what makes a timing honest.
        """
        if not self.breakdown_field:
            return None
        if self.metric_type == "FEEDBACK_SCORES" and len(self.feedback_scores) != 1:
            return None
        return BreakdownConfigPublic(
            field=self.breakdown_field,
            metadata_key=self.breakdown_key,
            sub_metric=self.feedback_scores[0] if self.feedback_scores else None,
        )


def _check_stat(client: opik.Opik, board: str, panel: StoredPanel) -> PanelCheck:
    start, end = _window()
    began = time.perf_counter()
    stats = client.rest_client.traces.get_trace_stats(
        project_id=panel.project_id,
        filters=json.dumps(panel.trace_filters),
        from_time=start,
        to_time=end,
    )
    elapsed = time.perf_counter() - began
    found = {s.name for s in stats.stats or []}
    # `duration.p50` is served inside a single `duration` stat, which is how the
    # card reads it too. `feedback_scores.<name>` is a stat key in its own right.
    wanted = "duration" if panel.metric.startswith("duration.") else panel.metric
    return PanelCheck(board, panel.title, elapsed, int(wanted in found))


def _check_chart(client: opik.Opik, board: str, panel: StoredPanel) -> PanelCheck:
    breakdown = panel.breakdown
    began = time.perf_counter()
    response = _metrics(
        client,
        panel.project_id,
        panel.metric_type,
        filters=panel.trace_filters,
        breakdown=breakdown,
        # A chart collapses to a whole-period total only behind a breakdown;
        # anything else is drawn on the dashboard's daily interval.
        total=breakdown is not None,
    )
    elapsed = time.perf_counter() - began
    totals = _series_totals(response)
    # Without a breakdown the frontend keeps only the selected scores, so the
    # backend returning every scorer must not be mistaken for a full panel.
    if breakdown is None and panel.feedback_scores:
        totals = {name: v for name, v in totals.items() if name in panel.feedback_scores}
    return PanelCheck(board, panel.title, elapsed, len(totals))


def verify(client: opik.Opik, names: set[str]) -> list[PanelCheck]:
    """Replay every panel of every built board against the live backend.

    Reads the definitions back out of Opik rather than trusting the in-memory
    ones, so a widget the API rejected or rewrote is checked as it was stored.
    """
    checks: list[PanelCheck] = []
    dashboards = client.rest_client.dashboards
    for summary in dashboards.find_dashboards(page=1, size=PAGE_SIZE).content or []:
        if summary.name not in names:
            continue
        board = dashboards.get_dashboard_by_id(summary.id)
        config = board.config if isinstance(board.config, dict) else {}
        for section in config.get("sections") or []:
            for widget in section.get("widgets") or []:
                panel = StoredPanel.parse(widget)
                if panel.type == "project_stats_card":
                    checks.append(_check_stat(client, str(summary.name), panel))
                elif panel.type == "project_metrics":
                    checks.append(_check_chart(client, str(summary.name), panel))
    return checks


def _report(checks: list[PanelCheck]) -> bool:
    """Print panel | query time | rows, and say whether anything failed."""
    print(f"\n{'board':<16} {'time':>7} {'rows':>5}  panel")
    for check in checks:
        mark = " " if check.ok else "✗"
        print(f"{mark}{check.board:<15} {check.seconds:>6.2f}s {check.rows:>5}  {check.title[:96]}")
    broken = [c for c in checks if not c.ok]
    if broken:
        print(
            f"\n[dashboards] {len(broken)} panel(s) would render empty or slow — "
            "they must be cut or fixed, not shipped:"
        )
        for check in broken:
            print(f"  {check.board}: {check.title}")
        return False
    slowest = max(checks, key=lambda c: c.seconds, default=None)
    print(
        f"\n[dashboards] {len(checks)} panels, every one returning rows in under "
        f"{SLOW_PANEL_SECONDS:.0f}s" + (f" (slowest {slowest.seconds:.2f}s)" if slowest else "")
    )
    return True


def build(client: opik.Opik | None = None) -> None:
    """Create or refresh the four dashboards, delete the rest, then prove them.

    Raises once the boards are written if any panel would render empty or slow:
    a board that quietly ships a dead panel is the failure this rewrite exists
    to stop, and a printed warning is one nobody reads.
    """
    opik_client = client or opik.Opik()
    found = opik_client.rest_client.projects.find_projects(page=1, size=PAGE_SIZE)
    projects = {p.name: p.id for p in found.content or [] if p.name.startswith("gaia-")}
    if not projects:
        raise RuntimeError("no gaia-* projects in Opik — run a suite first")

    suites = {name: read_suite(opik_client, name, pid) for name, pid in sorted(projects.items())}
    for suite in suites.values():
        print(
            f"[dashboards] read {suite.project:<18} {suite.cases:>4} cases · "
            f"{suite.pass_rate:>5.1%} passed · {len(suite.categories):>2} categories · "
            f"{len(suite.gate_scores):>2} gates · scorer={suite.primary_scorer or '-'} · "
            f"errors={suite.error_count}"
        )

    built: set[str] = set()
    for board in BOARDS:
        sections = board_sections(board, suites)
        if not sections:
            print(f"[dashboards] {board.name}: none of {board.projects} exist in Opik — skipped")
            continue
        panels = sum(1 for s in sections for w in s.widgets if w.type != "text_markdown")
        # An exception-type panel is the one thing allowed past the budget, and
        # only for a suite that actually has errors — a broken backend must never
        # be discoverable only by reading prose.
        allowance = sum(1 for name in board.projects if name in suites and suites[name].fault_types)
        if panels > PANEL_BUDGET + allowance:
            raise ValueError(
                f"{board.name} would carry {panels} live panels, over the budget of "
                f"{PANEL_BUDGET} (+{allowance} error panels). Cut a panel rather than raising "
                "the budget — the budget is why the boards load."
            )
        dashboard = _upsert(opik_client, board.name, board.description, sections)
        built.add(board.name)
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

    healthy = _report(verify(opik_client, built))
    print("[dashboards] open http://localhost:5173 → Dashboards")
    if not healthy:
        raise RuntimeError(
            "a panel on a built board returns no rows or is slower than "
            f"{SLOW_PANEL_SECONDS:.0f}s — see the table above"
        )
