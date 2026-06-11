"""Generate a benchmark report: stdout summary + markdown file."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import statistics


def generate_report(results: list[dict], output_path: Path | None = None) -> str:
    """Build the report string, print it, and optionally write a .md file."""
    lines: list[str] = []

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    overall_pct = (passed / total * 100) if total else 0.0

    lines.append("# GAIA Memory Engine — Accuracy Benchmark Report")
    lines.append("")
    lines.append(f"**Overall accuracy: {passed}/{total} probes passed ({overall_pct:.1f}%)**")
    lines.append("")

    # ── Per-category table ───────────────────────────────────────────────────
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)

    lines.append("## Per-category accuracy")
    lines.append("")
    lines.append("| Category | Passed | Total | % |")
    lines.append("|---|---|---|---|")

    cat_accuracy: list[tuple[str, float, int, int]] = []
    for cat, cat_results in sorted(by_cat.items()):
        cat_passed = sum(1 for r in cat_results if r["passed"])
        cat_total = len(cat_results)
        pct = (cat_passed / cat_total * 100) if cat_total else 0.0
        lines.append(f"| {cat} | {cat_passed} | {cat_total} | {pct:.0f}% |")
        cat_accuracy.append((cat, pct, cat_passed, cat_total))

    lines.append("")

    # ── Latency stats ────────────────────────────────────────────────────────
    latencies = [r["latency_s"] for r in results if r["latency_s"] > 0]
    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = statistics.median(latencies_sorted)
        p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
        p95 = latencies_sorted[p95_idx]
        lines.append("## Recall latency")
        lines.append("")
        lines.append(f"- P50: **{p50 * 1000:.0f} ms**")
        lines.append(f"- P95: **{p95 * 1000:.0f} ms**")
        lines.append(
            f"- Min: {min(latencies) * 1000:.0f} ms  |  Max: {max(latencies) * 1000:.0f} ms"
        )
        lines.append("")
    else:
        p50 = p95 = 0.0

    # ── Failing scenarios ────────────────────────────────────────────────────
    failures = [r for r in results if not r["passed"]]
    lines.append(f"## Failing probes ({len(failures)} of {total})")
    lines.append("")

    if not failures:
        lines.append("_All probes passed._")
    else:
        for r in failures:
            lines.append(f"### `{r['scenario_id']}` — {r['category']}")
            lines.append(f"- **Description:** {r['description']}")
            lines.append(f"- **Probe:** {r['probe']}")
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

    # ── Ranked weaknesses ────────────────────────────────────────────────────
    lines.append("## Ranked weaknesses (worst categories first)")
    lines.append("")

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

    # ── Engine seams / monkeypatching notes ─────────────────────────────────
    lines.append("## Engine seams used for temporal injection")
    lines.append("")
    lines.append(
        "- `ingestion.retain()` captures `datetime.now(UTC)` internally (line ~88 of ingestion.py)."
    )
    lines.append(
        "- No `occurred_at` injection parameter exists on `retain()` — temporal simulation"
        " required monkeypatching `app.memory.ingestion.datetime` with a subclass whose"
        " `now()` classmethod returns the desired simulated date."
    )
    lines.append(
        "- The patch is scoped per-`retain()` call (context manager) so it does not leak"
        " into retrieval, consolidation, or other concurrent tasks."
    )
    lines.append(
        "- `recall()` also calls `datetime.now(UTC)` for recency boosting and `forget_after`"
        " enforcement — these were NOT patched so the recency decay scores reflect real wall"
        " time, which may suppress older simulated facts unfairly."
    )
    lines.append("")

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
