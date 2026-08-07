"""Opik sink: dataset sync + experiment finalize by replaying the journal.

Runs log per-case traces with feedback scores; at finalize the same cases are
synced as a dataset and evaluated via ``opik.evaluation.evaluate`` with a
replay task (no agent re-run) so every run becomes a comparable experiment.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

import opik

from .journal import RunJournal
from .types import Case

_EVALS_DIR = Path(__file__).resolve().parent.parent
ENV_OPIK = _EVALS_DIR / ".env.opik"


def load_opik_env(path: Path = ENV_OPIK) -> None:
    """Load .env.opik into the process before any opik import."""
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def client(project_name: str) -> opik.Opik:
    return opik.Opik(project_name=project_name)


def sync_dataset(
    opik_client: opik.Opik,
    project: str,
    cases: list[Case],
) -> object:
    dataset = opik_client.get_or_create_dataset(
        name=f"{project}-cases", project_name=project
    )
    dataset.insert(
        [
            {
                "case_id": c.id,
                "input": c.prompt,
                "expected": c.expected,
                "ticket": c.ticket,
                "tags": c.tags,
            }
            for c in cases
        ]
    )
    return dataset


def finalize(
    project: str,
    cases: list[Case],
    journal: RunJournal,
    scoring_metrics: list[object],
    experiment_name: str,
    tags: list[str],
    replay: Callable[[dict[str, object]], dict[str, object]],
    nb_samples: int | None = None,
) -> object:
    """Evaluate the journal's stored outputs as an Opik experiment.

    ``replay(item)`` returns the stored run output for a case (never calls the
    agent again); metrics see dataset-item keys merged with those outputs.
    """
    from opik.evaluation import evaluate

    opik_client = opik.Opik(project_name=project)
    dataset = opik_client.get_or_create_dataset(
        name=f"{project}-cases", project_name=project
    )
    dataset.insert(
        [
            {
                "case_id": c.id,
                "input": c.prompt,
                "expected": c.expected,
                "ticket": c.ticket,
                "tags": c.tags,
            }
            for c in cases
        ]
    )
    result = evaluate(
        dataset=dataset,
        task=replay,
        scoring_metrics=scoring_metrics,
        experiment_name=experiment_name,
        experiment_tags=tags,
        nb_samples=nb_samples,
        task_threads=4,
        verbose=1,
    )
    journal.update_meta(experiment_name=experiment_name)
    return result


def log_case_trace(
    project: str,
    case_id: str,
    run_input: str,
    output: str,
    scores: dict[str, float],
    metadata: dict[str, Any],
) -> None:
    opik_client = opik.Opik(project_name=project)
    trace = opik_client.trace(
        name=f"case-{case_id}",
        input={"prompt": run_input},
        output={"text": output},
        metadata=metadata,
        tags=[project],
    )
    for name, value in scores.items():
        trace.log_feedback_score({"name": name, "value": value})
    opik_client.flush()


def experiment_name(run_dir: Path) -> str | None:
    meta_file = run_dir / "run.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text())
    return meta.get("experiment_name")
