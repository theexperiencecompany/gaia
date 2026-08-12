"""Plot the before/after prompt-cache comparison from two driver runs.

Takes the JSONL outputs of ``drive_big_conversation.py`` (baseline = pre-fix
layout, fixed = tail layout) and produces line charts:

1. per-turn cache hit % (the money chart)
2. per-turn uncached input tokens (what each layout pays full price for)
3. per-turn total input tokens (conversation growth — comparable across runs)
4. cumulative input cost over the conversation

Usage:
  uv run --with matplotlib python scripts/plot_cache_comparison.py \
      --baseline /tmp/cache_run_baseline.jsonl --fixed /tmp/cache_run_fixed.jsonl \
      --out docs/images/llm-cache
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt

IN_PRICE, CACHED_PRICE, OUT_PRICE = 0.00009, 0.000018, 0.00018


def load(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def cost(row: dict) -> float:
    return (
        (row["input"] - row["cached"]) / 1000 * IN_PRICE
        + row["cached"] / 1000 * CACHED_PRICE
        + row["output"] / 1000 * OUT_PRICE
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--fixed", required=True)
    parser.add_argument("--out", default="docs/images/llm-cache")
    args = parser.parse_args()

    base = load(args.baseline)
    fixed = load(args.fixed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    n = min(len(base), len(fixed))
    base, fixed = base[:n], fixed[:n]
    turns = list(range(n))

    def cumcost(rows: list[dict]) -> list[float]:
        acc, out = 0.0, []
        for r in rows:
            acc += cost(r)
            out.append(acc)
        return out

    base_cost = cumcost(base)
    fixed_cost = cumcost(fixed)

    # Savings from the tail layout on this exact conversation.
    base_total = sum(cost(r) for r in base)
    fixed_total = sum(cost(r) for r in fixed)
    savings = 100 * (1 - fixed_total / base_total) if base_total else 0.0
    base_hit = sum(r["cached"] for r in base) / max(sum(r["input"] for r in base), 1)
    fixed_hit = sum(r["cached"] for r in fixed) / max(sum(r["input"] for r in fixed), 1)

    style = {
        "baseline": dict(
            label="Before: volatile slots before conversation", color="#d97757", lw=2.2
        ),
        "fixed": dict(
            label="After: volatile slots after conversation (tail layout)", color="#4f9d69", lw=2.2
        ),
    }

    # 1. Hit rate per turn.
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for rows, key in ((base, "baseline"), (fixed, "fixed")):
        ax.plot(turns, [r["hit_pct"] for r in rows], marker="o", ms=3.5, **style[key])
    ax.set_xlabel("Turn (conversation grows left → right)")
    ax.set_ylabel("Cache hit rate (%)")
    ax.set_title(
        f"Prompt-cache hit rate per turn — real API, real provider\n"
        f"(DeepSeek V4 Flash via OpenRouter; total: {base_hit * 100:.1f}% → {fixed_hit * 100:.1f}%)"
    )
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "hit_rate_per_turn.png", dpi=140)

    # 2. Uncached input tokens per turn (what each layout pays full price for).
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for rows, key in ((base, "baseline"), (fixed, "fixed")):
        ax.plot(
            turns,
            [r["input"] - r["cached"] for r in rows],
            marker="o",
            ms=3.5,
            **style[key],
        )
    ax.set_xlabel("Turn")
    ax.set_ylabel("Uncached input tokens per turn")
    ax.set_title(
        "Uncached (full-price) input tokens per turn\n"
        "— the before layout re-sends the whole conversation; the tail layout pays only the delta"
    )
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "uncached_per_turn.png", dpi=140)

    # 3. Conversation size (sanity: both runs are comparable).
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for rows, key in ((base, "baseline"), (fixed, "fixed")):
        ax.plot(turns, [r["input"] for r in rows], marker="o", ms=3.5, **style[key])
    ax.set_xlabel("Turn")
    ax.set_ylabel("Total input tokens per turn")
    ax.set_title("Prompt size per turn (conversation growth)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "input_per_turn.png", dpi=140)

    # 4. Cumulative input cost.
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(turns, base_cost, marker="o", ms=3.5, **style["baseline"])
    ax.plot(turns, fixed_cost, marker="o", ms=3.5, **style["fixed"])
    ax.set_xlabel("Turn")
    ax.set_ylabel("Cumulative input cost (USD)")
    ax.set_title(
        f"Cumulative conversation cost — {savings:.1f}% cheaper with the tail layout "
        f"(${base_total:.4f} → ${fixed_total:.4f})"
    )
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "cumulative_cost.png", dpi=140)

    print(f"charts -> {out_dir}/")
    print(
        f"total hit rate: {base_hit * 100:.1f}% (before) → {fixed_hit * 100:.1f}% (after)\n"
        f"total input cost: ${base_total:.4f} → ${fixed_total:.4f} "
        f"({savings:.1f}% cheaper)\n"
        f"input tokens: {sum(r['input'] for r in base):,} vs {sum(r['input'] for r in fixed):,}"
    )


if __name__ == "__main__":
    main()
