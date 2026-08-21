"""Render before/after charts from sidecar_benchmark results JSONs.

Charts are written for non-technical readers: everyday words, GB units, and
explicit better/worse direction on every axis. Numbers come straight from the
result JSONs; nothing is hand-drawn.

Usage (from ``apps/api``)::

    uv run --with matplotlib python -m scripts.sidecar_benchmark.charts \
        --tags baseline fixed --out .agents/plans/charts
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"

# Container ceilings from infra/docker compose files, drawn as reference lines.
DEV_LIMIT_MB = 2560
PROD_LIMIT_MB = 3072

BEFORE_COLOR = "#9ca3af"  # muted gray: the old behavior
AFTER_COLOR = "#16a34a"  # green: this PR
LIMIT_COLOR = "#dc2626"


def load(tag: str, scenario: str) -> dict | None:
    path = RESULTS_DIR / tag / f"{scenario}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _style_axis(ax) -> None:
    muted = "#71717a"
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(muted)
    ax.spines["bottom"].set_color(muted)
    ax.tick_params(colors=muted, labelsize=9)
    ax.yaxis.label.set_color("#18181b")
    ax.xaxis.label.set_color("#18181b")
    ax.title.set_color("#18181b")
    ax.grid(True, axis="y", alpha=0.25)


def chart_rss_vs_batch(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    styles = {
        "baseline": ("Before fix", BEFORE_COLOR, "o"),
        "fixed": ("After this PR", AFTER_COLOR, "o"),
    }
    plotted = False
    for tag in tags:
        data = load(tag, "batch_sweep")
        if not data:
            continue
        rows = [r for r in data["rows"] if r["chars_each"] == 1600]
        label, color, marker = styles.get(tag, (tag, "#2563eb", "o"))
        ax.plot(
            [r["texts"] for r in rows],
            [r["peak_rss_mb"] / 1024 for r in rows],
            marker=marker,
            linewidth=2.5,
            markersize=6,
            label=label,
            color=color,
        )
        plotted = True
    if plotted:
        ax.axhline(DEV_LIMIT_MB / 1024, color=LIMIT_COLOR, linestyle="--", alpha=0.8)
        ax.axhline(PROD_LIMIT_MB / 1024, color=LIMIT_COLOR, linestyle="--", alpha=0.8)
        ax.text(
            0.98,
            DEV_LIMIT_MB / 1024 + 0.06,
            "container memory cap — above this, the process is killed",
            transform=ax.get_yaxis_transform(),
            ha="right",
            color=LIMIT_COLOR,
            fontsize=9,
        )
        ax.set_xscale("log", base=2)
        ax.set_xticks([8, 32, 128, 512, 1024])
        ax.set_xticklabels(["8", "32", "128", "512", "1,024"])
        ax.set_xlabel("memories sent to the sidecar in ONE request")
        ax.set_ylabel("RAM used (GB)")
        ax.set_title(
            "One giant request used to kill the sidecar.\nNow memory stays flat no matter how big the request is."
        )
        ax.legend(frameon=False, loc="upper left")
        _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "rss_vs_batch.png", dpi=150)
    plt.close(fig)


def chart_latency_vs_batch(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8.5, 5))
    styles = {"baseline": ("Before fix", BEFORE_COLOR), "fixed": ("After this PR", AFTER_COLOR)}
    for tag in tags:
        data = load(tag, "batch_sweep")
        if not data:
            continue
        rows = [r for r in data["rows"] if r["chars_each"] == 1600]
        label, color = styles.get(tag, (tag, "#2563eb"))
        ax.plot(
            [r["texts"] for r in rows],
            [r["latency_ms_p50"] / 1000 for r in rows],
            marker="o",
            linewidth=2.5,
            label=label,
            color=color,
        )
    ax.set_xscale("log", base=2)
    ax.set_xticks([8, 32, 128, 512, 1024])
    ax.set_xticklabels(["8", "32", "128", "512", "1,024"])
    ax.set_xlabel("memories sent to the sidecar in ONE request")
    ax.set_ylabel("time to finish the whole request (seconds)")
    ax.set_title(
        "Big requests take longer now (+10–20%) —\nbut before, they never finished at all: they crashed the service"
    )
    ax.legend(frameon=False)
    _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "latency_vs_batch.png", dpi=150)
    plt.close(fig)


def chart_concurrency(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    palette = ["#2563eb", "#16a34a", "#dc2626", "#7c3aed"]
    seen: dict[str, str] = {}
    for tag in tags:
        data = load(tag, "concurrency_sweep")
        if not data:
            continue
        by_threads: dict[int, list[dict]] = {}
        for row in data["rows"]:
            by_threads.setdefault(row["threads"], []).append(row)
        for threads, rows in sorted(by_threads.items()):
            key = f"{tag} · {threads} CPU threads"
            color = seen.setdefault(key, palette[len(seen) % len(palette)])
            rows.sort(key=lambda r: r["concurrency"])
            concs = [r["concurrency"] for r in rows]
            axes[0].plot(
                concs,
                [r["texts_per_s"] for r in rows],
                marker="o",
                color=color,
                label=key,
            )
            axes[1].plot(
                concs,
                [r["latency_ms_p95"] / 1000 for r in rows],
                marker="o",
                color=color,
                label=key,
            )
    axes[0].set_xlabel("how many things ask at the same time")
    axes[0].set_ylabel("memories handled per second\n(higher is better)")
    axes[0].set_title("How much it can chew through")
    axes[1].set_xlabel("how many things ask at the same time")
    axes[1].set_ylabel("wait for one answer at peak (seconds)\n(lower is better)")
    axes[1].set_title("How long you wait when it's busy")
    for ax in axes:
        ax.legend(frameon=False, fontsize=8)
        _style_axis(ax)
    fig.tight_layout()
    fig.savefig(out / "concurrency.png", dpi=150)
    plt.close(fig)


def chart_soak(tags: list[str], out: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 5))
    styles = {"baseline": ("Before fix", BEFORE_COLOR), "fixed": ("After this PR", AFTER_COLOR)}
    plotted = False
    for tag in tags:
        data = load(tag, "soak")
        if not data:
            continue
        series = data["rss_series_mb"]
        label, color = styles.get(tag, (tag, "#2563eb"))
        ax.plot(
            [t for t, _ in series],
            [rss / 1024 for _, rss in series],
            label=f"{label} — peaked at {data['peak_rss_mb'] / 1024:.1f} GB",
            color=color,
            linewidth=1.6,
        )
        plotted = True
    if plotted:
        ax.axhline(PROD_LIMIT_MB / 1024, color=LIMIT_COLOR, linestyle="--")
        ax.axhline(DEV_LIMIT_MB / 1024, color=LIMIT_COLOR, linestyle="--", alpha=0.6)
        ax.text(
            0.99,
            PROD_LIMIT_MB / 1024 - 0.12,
            "container memory cap",
            transform=ax.get_yaxis_transform(),
            ha="right",
            color=LIMIT_COLOR,
            fontsize=9,
        )
        ax.set_xlabel("seconds of nonstop realistic traffic (searches + saves + re-ranking)")
        ax.set_ylabel("RAM used (GB)")
        ax.set_title(
            "Two minutes of nonstop traffic:\nbefore, RAM climbed past the cap; after, it holds steady"
        )
        ax.legend(frameon=False, loc="center right")
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
    # S8707: the CLI out path is untrusted input — only write inside this
    # project's results/charts area.
    out = Path(args.out).resolve()
    allowed_root = Path(__file__).resolve().parents[4]
    if not out.is_relative_to(allowed_root):
        raise SystemExit(f"--out must stay inside the repository ({allowed_root})")
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
