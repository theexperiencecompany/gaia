"""Render before/after charts from sidecar_benchmark results JSONs.

Usage (from ``apps/api``)::

    uv run --with matplotlib python -m scripts.sidecar_benchmark.charts \
        --tags baseline fixed --out .agents/plans/charts
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

# Container ceilings from infra/docker compose files, for reference lines.
DEV_LIMIT_MB = 2560
PROD_LIMIT_MB = 3072

INK = "#18181b"
MUTED = "#71717a"
ACCENT = "#2563eb"
ACCENT_2 = "#dc2626"


def load(tag: str, scenario: str) -> dict | None:
    path = RESULTS_DIR / tag / f"{scenario}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _style_axis(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=MUTED)
    ax.yaxis.label.set_color(INK)
    ax.xaxis.label.set_color(INK)
    ax.title.set_color(INK)
    ax.grid(True, axis="y", alpha=0.25)


def chart_rss_vs_batch(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, tag in enumerate(tags):
        data = load(tag, "batch_sweep")
        if not data:
            continue
        rows = [r for r in data["rows"] if r["chars_each"] == 1600]
        color = ACCENT if i == 0 else ACCENT_2
        ax.plot(
            [r["texts"] for r in rows],
            [r["peak_rss_mb"] for r in rows],
            marker="o",
            label=f"{tag} peak RSS",
            color=color,
        )
        floor = rows[0]["rss_floor_mb"]
        ax.axhline(floor, color=color, linestyle=":", alpha=0.5)
    ax.axhline(DEV_LIMIT_MB, color=MUTED, linestyle="--")
    ax.axhline(PROD_LIMIT_MB, color=INK, linestyle="--")
    ax.text(
        ax.get_xlim()[1],
        DEV_LIMIT_MB + 20,
        " dev compose limit",
        ha="right",
        color=MUTED,
        fontsize=8,
    )
    ax.text(
        ax.get_xlim()[1], PROD_LIMIT_MB + 20, " prod swarm limit", ha="right", color=INK, fontsize=8
    )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("texts per /embed request (each ~1,600 chars)")
    ax.set_ylabel("sidecar peak RSS (MB)")
    ax.set_title("Embedding sidecar memory vs request batch size")
    ax.legend(frameon=False)
    _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "rss_vs_batch.png", dpi=150)
    plt.close(fig)


def chart_latency_vs_batch(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, tag in enumerate(tags):
        data = load(tag, "batch_sweep")
        if not data:
            continue
        rows = [r for r in data["rows"] if r["chars_each"] == 1600]
        ax.plot(
            [r["texts"] for r in rows],
            [r["latency_ms_p50"] for r in rows],
            marker="o",
            label=f"{tag} p50 latency",
            color=ACCENT if i == 0 else ACCENT_2,
        )
    ax.set_xscale("log", base=2)
    ax.set_xlabel("texts per /embed request (each ~1,600 chars)")
    ax.set_ylabel("request latency p50 (ms)")
    ax.set_title("Sidecar latency vs batch size")
    ax.legend(frameon=False)
    _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "latency_vs_batch.png", dpi=150)
    plt.close(fig)


def chart_concurrency(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for i, tag in enumerate(tags):
        data = load(tag, "concurrency_sweep")
        if not data:
            continue
        color = ACCENT if i == 0 else ACCENT_2
        by_threads: dict[int, list[dict]] = {}
        for row in data["rows"]:
            by_threads.setdefault(row["threads"], []).append(row)
        styles = {2: "--", 4: "-"}
        for threads, rows in sorted(by_threads.items()):
            rows.sort(key=lambda r: r["concurrency"])
            concs = [r["concurrency"] for r in rows]
            axes[0].plot(
                concs,
                [r["texts_per_s"] for r in rows],
                marker="o",
                linestyle=styles.get(threads, "-"),
                color=color,
                label=f"{tag}: {threads} ORT threads",
            )
            axes[1].plot(
                concs,
                [r["latency_ms_p95"] for r in rows],
                marker="o",
                linestyle=styles.get(threads, "-"),
                color=color,
                label=f"{tag}: {threads} ORT threads",
            )
    axes[0].set_xlabel("client concurrency (parallel HTTP callers)")
    axes[0].set_ylabel("throughput (texts embedded / s)")
    axes[0].set_title("Throughput vs concurrency")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].set_xlabel("client concurrency (parallel HTTP callers)")
    axes[1].set_ylabel("request latency p95 (ms)")
    axes[1].set_title("Tail latency vs concurrency")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "concurrency.png", dpi=150)
    plt.close(fig)


def chart_soak(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    for i, tag in enumerate(tags):
        data = load(tag, "soak")
        if not data:
            continue
        series = data["rss_series_mb"]
        ax.plot(
            [t for t, _ in series],
            [rss for _, rss in series],
            label=f"{tag} (peak {data['peak_rss_mb']:.0f} MB)",
            color=ACCENT if i == 0 else ACCENT_2,
            linewidth=1.2,
        )
    ax.axhline(DEV_LIMIT_MB, color=MUTED, linestyle="--")
    ax.axhline(PROD_LIMIT_MB, color=INK, linestyle="--")
    ax.text(
        ax.get_xlim()[1], PROD_LIMIT_MB + 15, " prod swarm limit", ha="right", color=INK, fontsize=8
    )
    ax.set_xlabel("soak time (s)")
    ax.set_ylabel("sidecar RSS (MB)")
    ax.set_title("RSS stability under sustained mixed load")
    ax.legend(frameon=False)
    _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "soak.png", dpi=150)
    plt.close(fig)


def equivalence_text(tags: list[str]) -> str:
    lines = []
    for tag in tags:
        data = load(tag, "equivalence")
        if data:
            lines.append(
                f"- {tag}: max |Δ|={data['max_abs_diff']:.3g}, min cosine="
                f"{data['min_cosine']:.9f} over {data['n']} texts → "
                f"{'PASS' if data['pass'] else 'FAIL'}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", default="baseline,fixed")
    parser.add_argument("--out", default=str(RESULTS_DIR.parent / "charts"))
    args = parser.parse_args()
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chart_rss_vs_batch(tags, out)
    chart_latency_vs_batch(tags, out)
    chart_concurrency(tags, out)
    chart_soak(tags, out)
    print(f"charts written to {out}")
    print("equivalence:")
    print(equivalence_text(tags))


if __name__ == "__main__":
    main()
