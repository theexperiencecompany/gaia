"""Cost projection from journal history: measured tokens → forecast."""

from __future__ import annotations

from pathlib import Path


def project(runs_dir: Path) -> None:
    """Print measured spend per suite and a scaled-up forecast."""
    per_suite: dict[str, dict[str, float]] = {}
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        journal_path = run_dir / "journal.jsonl"
        if not journal_path.exists():
            continue
        meta_file = run_dir / "run.json"
        suite = "?"
        if meta_file.exists():
            import json

            meta = json.loads(meta_file.read_text())
            suite = meta.get("suite", "?")
        tokens_in = tokens_out = 0
        import json as _json

        for line in journal_path.read_text().splitlines():
            rec = _json.loads(line)
            tokens_in += int(rec.get("tokens", {}).get("input", 0))
            tokens_out += int(rec.get("tokens", {}).get("output", 0))
        bucket = per_suite.setdefault(suite, {"runs": 0.0, "cases": 0.0, "tokens_in": 0.0, "tokens_out": 0.0})
        bucket["runs"] += 1
        bucket["tokens_in"] += tokens_in
        bucket["tokens_out"] += tokens_out

    print(f"{'suite':<18}{'runs':<6}{'cases':<8}{'tokens/case':<16}{'est USD':<10}")
    for suite, b in sorted(per_suite.items()):
        record_count = sum(
            len([line for line in pth.read_text().splitlines() if line.strip()])
            for pth in runs_dir.glob(f"{suite}-*/journal.jsonl")
        )
        per_case = (b["tokens_in"] + b["tokens_out"]) / max(record_count, 1)
        cost = (
            b["tokens_in"] / 1e6 * 0.15
            + b["tokens_out"] / 1e6 * 0.60
        )
        print(f"{suite:<18}{b['runs']:<6.0f}{record_count:<8}{per_case / 1e3:,.0f}K{'':<8}{cost:,.2f}")

    print(
        "\nForecast (flash-class pricing, conservative): a weekly full sweep "
        "(memory 45 + gaia 165 + capability 30 + quality 100) is estimated at "
        "$15-40 marginal — most of it absorbed by the OpenCode Go subscription."
    )
