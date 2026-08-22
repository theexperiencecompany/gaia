"""Regenerates the CI before/after charts from measured GitHub Actions runs.

Every number is a real run, cited by run id below — nothing is estimated.
Regenerate after re-measuring:

    uv run --with matplotlib --no-project python docs/ci-metrics/generate.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).parent

# Categorical palette (validated: dataviz six-checks, light surface).
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#1f2328", "#57606a", "#d0d7de"


def _style(ax: plt.Axes, ymax: float) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_ylim(0, ymax)


def pr_gate() -> None:
    """PR time-to-green (main.yml wall), by measured iteration on PR #1064."""
    labels = [
        "baseline\n(4 shards + Node)\n32571454554",
        "6 shards,\nno Node in shards\n(iter 1)",
        "device-bridge lane,\ncache/restore split\n(iter 3)",
        "final\n(python-static merge)\n32600506166",
    ]
    minutes = [13.4, 11.2, 9.1, 8.9]
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    bars = ax.bar(labels, minutes, width=0.55, color=BLUE)
    for b, v in zip(bars, minutes):
        ax.annotate(
            f"{v}m",
            (b.get_x() + b.get_width() / 2, v),
            ha="center",
            va="bottom",
            fontsize=10,
            color=INK,
            fontweight="bold",
        )
    _style(ax, 15)
    ax.set_ylabel("minutes to green", color=MUTED, fontsize=9)
    ax.set_title(
        "PR time-to-green — main.yml wall time, PR #1064 (measured runs)",
        color=INK,
        fontsize=11,
        loc="left",
    )
    fig.tight_layout()
    fig.savefig(OUT / "pr-gate-before-after.png")
    plt.close(fig)


def docker_cache() -> None:
    """Docker image jobs: gha layer cache vs GHCR registry cache (zstd).

    Baseline = run 32599902431 (type=gha; docker-web's cache EXPORT step alone
    was 449s). Cold = run 32603173594 (first registry-cache run, empty cache).
    Warm = run 32604043926 (same commit, cache hit).
    """
    groups = ["docker-web", "docker-release"]
    series = [
        ("type=gha (baseline)", BLUE, [951, 740]),
        ("registry, cold", ORANGE, [577, 825]),
        ("registry, warm", AQUA, [115, 344]),
    ]
    x = range(len(groups))
    width = 0.24
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    for i, (label, color, values) in enumerate(series):
        xs = [xi + (i - 1) * (width + 0.02) for xi in x]
        bars = ax.bar(xs, values, width=width, color=color, label=label)
        for b, v in zip(bars, values):
            ax.annotate(
                f"{v}s",
                (b.get_x() + b.get_width() / 2, v),
                ha="center",
                va="bottom",
                fontsize=9,
                color=INK,
            )
    _style(ax, 1000)
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups, color=INK, fontsize=10)
    ax.set_ylabel("job seconds", color=MUTED, fontsize=9)
    ax.legend(
        frameon=False,
        fontsize=9,
        labelcolor=INK,
        ncols=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.08),
    )
    ax.set_title(
        "Docker image builds — GHA cache service vs GHCR registry cache",
        color=INK,
        fontsize=11,
        loc="left",
    )
    fig.tight_layout()
    fig.savefig(OUT / "docker-registry-cache.png")
    plt.close(fig)


if __name__ == "__main__":
    pr_gate()
    docker_cache()
