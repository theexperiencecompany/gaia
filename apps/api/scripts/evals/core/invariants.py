"""Cross-checks run against a journal before its numbers are published.

Each check compares a quantity against a second, independently-derived one — a
per-case token sum against the cost tracker's own total, a score against whether
the case produced anything. A violation aborts the report rather than degrading
it, because the failures these catch look like ordinary numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import faults

# There is deliberately no upper bound on per-case tokens.
#
# There used to be one, at 400k, on the theory that a number that large had to
# be a running total. The app's own per-LLM-call accounting says otherwise: a
# real capability case has a median of 131k input tokens and the largest
# legitimate one measured is 9.6M, because context grows step over step inside a
# case (18k -> 97k over 14 calls in one observed thread) and compaction is
# silently skipped whenever JuiceFS is absent. A cap set below that flags a true
# measurement of a genuinely expensive run, on every native run, forever — and a
# gate that cries wolf is a gate someone switches off.
#
# Size is a product finding, not a data defect. What actually distinguishes a
# corrupt figure from an expensive one is provenance and reconciliation, both of
# which are checked below: `tokens.source` must say the provider measured it,
# and the journal's per-case sum must agree with the cost tracker's independent
# total. The contamination that motivated the cap — a per-case delta on a shared
# meter, inflating every figure by the concurrency — fails that reconciliation
# by construction, whatever the magnitude.

# Below this a count is not a measurement. Every case sends a system
# prompt before it sends anything else, and GAIA's is thousands of tokens on its
# own, so a case that produced a real transcript cannot have consumed a few
# dozen. Two suites recorded a median of 56 and 16 input tokens for months:
# their transports estimate from the question's character count, which sees
# neither the system prompt, the tool schemas, nor the agent's own turns.
IMPLAUSIBLE_MINIMUM_CASE_TOKENS = 500

# Only a case that actually waited on a model is held to that floor: a fake
# transport that answers instantly has nothing to under-count.
MIN_MODEL_CALL_SECONDS = 2.0

# ...and only a case that reached a verdict. An `errored` case died partway, so
# a partial or zero reading is what you would expect rather than evidence of a
# broken meter — flagging it is a false positive, and one that fires on exactly
# the runs an outage already ruined. Verified against comms-20260808-092206:
# all 5 records the floor caught there were `errored`, while every record it
# catches in gaia_bench, hil and regression is `passed` or `failed`.
GRADED_FOR_TOKEN_FLOOR = ("passed", "failed", "skipped")


@dataclass
class Violation:
    """One reconciliation failure, named so it can be acted on."""

    check: str
    detail: str


@dataclass
class InvariantReport:
    violations: list[Violation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def render(self) -> str:
        lines = ["", "=" * 74, "PUBLISH BLOCKED — the run's own numbers do not reconcile", "=" * 74]
        lines += [f"  {v.check}: {v.detail}" for v in self.violations]
        lines.append("")
        lines.append("No report was written. The journal is intact; fix the cause and re-report.")
        return "\n".join(lines)


def check_records(
    records: list[dict[str, Any]],
    metered_by_case: dict[str, tuple[int, int]] | None = None,
    sim: bool = False,
) -> InvariantReport:
    """Cross-check a run's journal against itself, and against the cost tracker.

    ``metered_by_case`` is the tracker's own per-case (input, output) readings —
    derived by a completely different path from the journal's figures, which is
    exactly what makes the comparison worth anything. The comparison covers only
    cases present on BOTH sides: a resumed run's journal carries earlier passes
    the tracker never saw, and an aborted run's tracker carries in-flight spend
    the journal never recorded. Whole-run totals disagree by construction in
    both directions; the intersection cannot.

    ``sim`` marks a scripted-stub run: the stub reports no usage, so zero tokens
    is the true measurement there, and the token floor would reject every sim
    run forever — a gate that is always red gets switched off.
    """
    report = InvariantReport()
    if not records:
        return report

    # A declined case is silent for a reason it declared up front, and its zero
    # is the honest score for a question we could not attempt. That is not the
    # defect this check exists for — which is a case that WAS asked, returned
    # nothing, and still came back with a number attached.
    scored_but_silent = [
        str(r.get("case_id"))
        for r in records
        if r.get("scores")
        and not r.get("skip_reason")
        and not (r.get("text") or r.get("messages"))
        and not int((r.get("tokens") or {}).get("input", 0))
    ]
    if scored_but_silent:
        report.violations.append(
            Violation(
                "scored a case that produced nothing",
                f"{len(scored_but_silent)} case(s) carry a score with no output and no tokens "
                f"— e.g. {scored_but_silent[:3]}. A case that produced nothing cannot have "
                f"earned a score; this is how an outage became a 0%.",
            )
        )

    undercounted = (
        []
        if sim
        else [
            (str(r.get("case_id")), int((r.get("tokens") or {}).get("input", 0)))
            for r in records
            if (r.get("text") or r.get("messages"))
            and r.get("status") in GRADED_FOR_TOKEN_FLOOR
            and float(r.get("duration_s") or 0.0) >= MIN_MODEL_CALL_SECONDS
            and int((r.get("tokens") or {}).get("input", 0)) < IMPLAUSIBLE_MINIMUM_CASE_TOKENS
            # A LABELLED estimate is exempt — it is already excluded from cost
            # and flagged by ingest-check; failing it here would just teach
            # suites to launder estimates into the metered channel (the exact
            # bug this caught in hil). Everything else — metered or unlabelled —
            # stays subject to the floor: an unlabelled undercount is precisely
            # the defect this check exists for.
            and (r.get("tokens") or {}).get("source") != "estimated"
        ]
    )
    if undercounted:
        report.violations.append(
            Violation(
                "implausibly small per-case token count",
                f"{len(undercounted)} case(s) below {IMPLAUSIBLE_MINIMUM_CASE_TOKENS:,} input "
                f"tokens after seconds of work — e.g. {undercounted[:3]}. A figure this small "
                f"cannot include the system prompt, so it is an estimate of the question's length "
                f"or a meter that never fired, not a measurement. Cost derived from it is fiction.",
            )
        )

    graded_faults = [
        str(r.get("case_id"))
        for r in records
        if r.get("status") == "failed" and faults.never_conducted(r)
    ]
    if graded_faults:
        report.violations.append(
            Violation(
                "an outage was graded as a wrong answer",
                f"{len(graded_faults)} case(s) are journaled `failed` with a fault, no transcript "
                f"and no scores — e.g. {graded_faults[:3]}. They never ran, so they cannot be "
                f"wrong; averaging them publishes a backend outage as a quality score.",
            )
        )

    inputs = [int((r.get("tokens") or {}).get("input", 0)) for r in records if r.get("tokens")]
    # A long, almost-never-decreasing series is a running total. The bar is
    # deliberately high: a suite whose cases genuinely grow (ordered by context
    # size) can rise for a while, and a check that fires on that is noise
    # someone will switch off. The real defect ran 99-100% over 393 comparisons;
    # chance alone cannot reach 95% across 20.
    if len(inputs) >= 21:
        rising = sum(1 for i in range(1, len(inputs)) if inputs[i] > inputs[i - 1])
        if rising / (len(inputs) - 1) > 0.95:
            report.violations.append(
                Violation(
                    "token counts are cumulative",
                    f"{rising}/{len(inputs) - 1} consecutive cases strictly increased. Token "
                    f"counts are non-negative, so a genuine per-case series decreases "
                    f"regularly; a near-monotonic one is a running total.",
                )
            )

    if metered_by_case is not None:
        latest: dict[str, dict[str, Any]] = {str(r.get("case_id")): r for r in records}
        both_sides = [cid for cid in latest if cid in metered_by_case]
        summed = (
            sum(int((latest[c].get("tokens") or {}).get("input", 0)) for c in both_sides),
            sum(int((latest[c].get("tokens") or {}).get("output", 0)) for c in both_sides),
        )
        tracker_side = (
            sum(metered_by_case[c][0] for c in both_sides),
            sum(metered_by_case[c][1] for c in both_sides),
        )
        for label, journal_value, tracker_value in (
            ("input", summed[0], tracker_side[0]),
            ("output", summed[1], tracker_side[1]),
        ):
            if tracker_value and abs(journal_value - tracker_value) > max(
                1000, tracker_value * 0.05
            ):
                report.violations.append(
                    Violation(
                        f"{label} tokens disagree with the tracker",
                        f"journal sums to {journal_value:,}, the cost tracker metered "
                        f"{tracker_value:,}. Two independent paths must agree.",
                    )
                )

    statuses = {r.get("status") for r in records}
    unknown = statuses - {"passed", "failed", "errored", "skipped"}
    if unknown:
        report.violations.append(
            Violation("unknown case status", f"{sorted(str(s) for s in unknown)}")
        )
    # A retry legitimately appends a second record — the journal is append-only
    # and latest_per_case() supersedes, so errored-then-graded is the sweep
    # mechanism working, not a defect. What can never be legitimate is one case
    # GRADED twice within a run: that double-counts in any aggregation.
    graded_counts: dict[str, int] = {}
    for r in records:
        if r.get("status") in ("passed", "failed"):
            cid = str(r.get("case_id"))
            graded_counts[cid] = graded_counts.get(cid, 0) + 1
    double_graded = sorted(cid for cid, n in graded_counts.items() if n > 1)
    if double_graded:
        report.violations.append(
            Violation(
                "case graded more than once",
                f"{len(double_graded)} case(s) carry two graded records — e.g. "
                f"{double_graded[:3]}. A retry may supersede an error, but a second "
                f"grade double-counts in every aggregation that iterates records().",
            )
        )
    return report
