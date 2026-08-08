"""Create Opik dashboards for every GAIA eval project.

Uses the opik SDK's REST client (no hand-rolled curl). Widget config shapes
mirror the opik-frontend templates (v1/pages-shared/dashboards).
Run: uv run --group backend python scripts/evals/opik_dashboards.py
"""

from __future__ import annotations

import time

from scripts.evals.core.opiksink import load_opik_env

load_opik_env()

import opik  # noqa: E402


def _client() -> opik.Opik:
    return opik.Opik()


def _config(widgets: list[dict]) -> dict:
    layout = [
        {"i": w["id"], "x": w.get("x", 0), "y": w.get("y", 0), "w": w.get("w", 4), "h": w.get("h", 4)}
        for w in widgets
    ]
    return {
        "version": 1,
        "sections": [
            {
                "id": "eval-section-1",
                "title": "Eval results",
                "widgets": [{"id": w["id"], "title": w["title"], "type": w["type"], "config": w["config"]} for w in widgets],
                "layout": layout,
            }
        ],
        "lastModified": int(time.time() * 1000),
    }


def _feedback_scores_widget(wid: str, title: str, scores: list[str], x: int, w: int = 4) -> dict:
    return {
        "id": wid,
        "title": title,
        "type": "experiments_feedback_scores",
        "x": x,
        "w": w,
        "config": {
            "chartType": "bar",
            "filters": [],
            "groups": [],
            "feedbackScores": scores,
        },
    }


def _leaderboard_widget(wid: str, title: str, scores: list[str], x: int, w: int = 6) -> dict:
    return {
        "id": wid,
        "title": title,
        "type": "experiment_leaderboard",
        "x": x,
        "w": w,
        "config": {
            "filters": [],
            "selectedColumns": [],
            "enableRanking": True,
            "rankingMetric": scores[0] if scores else "gaia_exact",
            "rankingDirection": False,
            "scoresColumnsOrder": scores,
            "metadataColumnsOrder": [],
            "columnsWidth": {},
            "maxRows": 20,
            "sorting": [],
        },
    }


def _create(name: str, description: str, config: dict, project_name: str | None = None) -> None:
    client = _client()
    resp = client.rest_client.dashboards.create_dashboard(  # type: ignore[attr-defined]
        name=name,
        description=description,
        config=config,
        type="multi_project" if project_name is None else "experiments",
        project_name=project_name,
    )
    print(f"  ✓ dashboard '{name}' (id={resp.id if hasattr(resp, 'id') else '?'})")


def main() -> None:
    memory_scores = ["probes", "provider"]
    capability_scores = ["communicate", "end_state", "tool_call_correctness", "provider"]
    quality_scores = ["bubble_boundary", "tool_card", "communicate", "rubric_judge", "provider"]
    gaia_scores = ["gaia_exact", "provider"]

    print("Creating dashboards...")
    _create(
        "GAIA Evals — All Projects",
        "Cross-project overview: every suite's experiments compared at a glance.",
        _config(
            [
                _leaderboard_widget("all-leaderboard", "All experiments", ["gaia_exact", "probes", "communicate", "rubric_judge", "provider"], 0, w=8),
            ]
        ),
    )
    _create(
        "Memory benchmark",
        "45-scenario memory suite: probe accuracy per run, plus the LongMemEval judge results.",
        _config(
            [
                _leaderboard_widget("mem-lb", "Runs vs probe accuracy", memory_scores, 0, w=6),
                _feedback_scores_widget("mem-fs", "Probe score distribution", ["probes"], 6, w=4),
            ]
        ),
        project_name="gaia-memory",
    )
    _create(
        "LongMemEval",
        "500-question LongMemEval oracle: exact-match accuracy per type, per provider.",
        _config(
            [
                _leaderboard_widget("lme-lb", "Runs vs accuracy", ["gaia_exact", "provider"], 0, w=6),
                _feedback_scores_widget("lme-fs", "Accuracy distribution", ["gaia_exact"], 6, w=4),
            ]
        ),
        project_name="gaia-longmemeval",
    )
    _create(
        "Capability",
        "41-case tool-call suite (incl. hard tier): gates + provider split.",
        _config(
            [
                _leaderboard_widget("cap-lb", "Runs vs gate scores", capability_scores, 0, w=6),
                _feedback_scores_widget("cap-fs", "Gate score distribution", capability_scores[:3], 6, w=4),
            ]
        ),
        project_name="gaia-capability",
    )
    _create(
        "Quality",
        "18-transcript suite: structural checks + rubric judge.",
        _config(
            [
                _leaderboard_widget("qual-lb", "Runs vs quality scores", quality_scores, 0, w=6),
                _feedback_scores_widget("qual-fs", "Quality score distribution", ["rubric_judge", "bubble_boundary"], 6, w=4),
            ]
        ),
        project_name="gaia-quality",
    )
    _create(
        "GAIA Benchmark",
        "Official GAIA validation (165, gated): exact-match per level.",
        _config(
            [
                _leaderboard_widget("gaia-lb", "Runs vs exact match", gaia_scores, 0, w=6),
                _feedback_scores_widget("gaia-fs", "Exact-match distribution", ["gaia_exact"], 6, w=4),
            ]
        ),
        project_name="gaia-bench",
    )
    print("Done — open http://localhost:5173 → Dashboards")


if __name__ == "__main__":
    main()
