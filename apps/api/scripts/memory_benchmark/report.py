"""Generate a benchmark report: stdout summary + markdown file."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import statistics


def _build_header(passed: int, total: int, overall_pct: float) -> list[str]:
    return [
        "# GAIA Memory Engine — Accuracy Benchmark Report",
        "",
        f"**Overall accuracy: {passed}/{total} probes passed ({overall_pct:.1f}%)**",
        "",
    ]


def _build_category_table(
    by_cat: dict[str, list[dict]],
) -> tuple[list[str], list[tuple[str, float, int, int]]]:
    lines = [
        "## Per-category accuracy",
        "",
        "| Category | Passed | Total | % |",
        "|---|---|---|---|",
    ]
    cat_accuracy: list[tuple[str, float, int, int]] = []
    for cat, cat_results in sorted(by_cat.items()):
        cat_passed = sum(1 for r in cat_results if r["passed"])
        cat_total = len(cat_results)
        pct = (cat_passed / cat_total * 100) if cat_total else 0.0
        lines.append(f"| {cat} | {cat_passed} | {cat_total} | {pct:.0f}% |")
        cat_accuracy.append((cat, pct, cat_passed, cat_total))
    lines.append("")
    return lines, cat_accuracy


def _build_latency_section(results: list[dict]) -> tuple[list[str], float, float]:
    latencies = [r["latency_s"] for r in results if r["latency_s"] > 0]
    if not latencies:
        return [], 0.0, 0.0
    latencies_sorted = sorted(latencies)
    p50 = statistics.median(latencies_sorted)
    p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
    p95 = latencies_sorted[p95_idx]
    lines = [
        "## Recall latency",
        "",
        f"- P50: **{p50 * 1000:.0f} ms**",
        f"- P95: **{p95 * 1000:.0f} ms**",
        f"- Min: {min(latencies) * 1000:.0f} ms  |  Max: {max(latencies) * 1000:.0f} ms",
        "",
    ]
    return lines, p50, p95


def _build_failure_entry(r: dict) -> list[str]:
    lines = [
        f"### `{r['scenario_id']}` — {r['category']}",
        f"- **Description:** {r['description']}",
        f"- **Probe:** {r['probe']}",
    ]
    if r["must_contain"]:
        lines.append(f"- **Expected to contain:** {r['must_contain']}")
    if r["must_not_contain"]:
        lines.append(f"- **Must NOT contain:** {r['must_not_contain']}")
    if r["missing_terms"]:
        lines.append(f"- **Missing terms:** {r['missing_terms']}")
    if r["forbidden_found"]:
        lines.append(f"- **Forbidden terms found:** {r['forbidden_found']}")
    recalled_preview = r["recalled_text"][:500].replace("\n", " ")
    lines.append(f"- **Actually recalled:** `{recalled_preview}`")
    lines.append("")
    return lines


def _build_failures_section(failures: list[dict], total: int) -> list[str]:
    lines = [f"## Failing probes ({len(failures)} of {total})", ""]
    if not failures:
        lines.append("_All probes passed._")
    else:
        for r in failures:
            lines.extend(_build_failure_entry(r))
    return lines


def _build_weaknesses_section(
    cat_accuracy: list[tuple[str, float, int, int]],
    by_cat: dict[str, list[dict]],
) -> list[str]:
    lines = ["## Ranked weaknesses (worst categories first)", ""]
    sorted_cats = sorted(cat_accuracy, key=lambda x: x[1])
    for rank, (cat, pct, cat_pass, cat_total) in enumerate(sorted_cats, 1):
        cat_failures = [r for r in by_cat[cat] if not r["passed"]]
        example = cat_failures[0] if cat_failures else None
        lines.append(f"### {rank}. {cat} — {pct:.0f}% ({cat_pass}/{cat_total})")
        if example:
            lines.append(f"- Example failure: **{example['description']}**")
            lines.append(f"  - Probe: `{example['probe']}`")
            recalled_preview = example["recalled_text"][:300].replace("\n", " ")
            lines.append(f"  - Recalled: `{recalled_preview}`")
        lines.append("")
    return lines


def _build_engine_seams_section() -> list[str]:
    return [
        "## Engine seams used for temporal injection",
        "",
        "- `ingestion.retain()` captures `datetime.now(UTC)` internally (line ~88 of ingestion.py).",
        (
            "- No `occurred_at` injection parameter exists on `retain()` — temporal simulation"
            " required monkeypatching `app.memory.ingestion.datetime` with a subclass whose"
            " `now()` classmethod returns the desired simulated date."
        ),
        (
            "- The patch is scoped per-`retain()` call (context manager) so it does not leak"
            " into retrieval, consolidation, or other concurrent tasks."
        ),
        (
            "- `recall()` also calls `datetime.now(UTC)` for recency boosting and `forget_after`"
            " enforcement — these were NOT patched so the recency decay scores reflect real wall"
            " time, which may suppress older simulated facts unfairly."
        ),
        "",
    ]


def generate_report(results: list[dict], output_path: Path | None = None) -> str:
    """Build the report string, print it, and optionally write a .md file."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    overall_pct = (passed / total * 100) if total else 0.0

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)

    cat_lines, cat_accuracy = _build_category_table(by_cat)
    latency_lines, _p50, _p95 = _build_latency_section(results)
    failures = [r for r in results if not r["passed"]]

    lines: list[str] = [
        *_build_header(passed, total, overall_pct),
        *cat_lines,
        *latency_lines,
        *_build_failures_section(failures, total),
        *_build_weaknesses_section(cat_accuracy, by_cat),
        *_build_engine_seams_section(),
    ]

    report = "\n".join(lines)
    print(report)

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"\nReport written to: {output_path}")

    return report


def print_summary(results: list[dict]) -> None:
    """Quick one-liner summary for CI / scripted runs."""
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    pct = (passed / total * 100) if total else 0.0
    print(f"\nSUMMARY: {passed}/{total} probes passed ({pct:.1f}%)")
