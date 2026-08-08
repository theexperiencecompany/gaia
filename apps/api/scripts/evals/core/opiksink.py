"""Opik sink: per-case traces + experiment finalize by replaying the journal.

Runs log one trace per case with feedback scores; at finalize the same cases are
synced as a dataset and evaluated via ``opik.evaluation.evaluate`` with a
replay task (no agent re-run) so every run becomes a comparable experiment.

Every write is keyed by ``CaseTrace.key`` (case + run), which is what lets
``seed`` backfill past journals repeatedly without duplicating anything.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid

from dotenv import load_dotenv
import opik
from opik import id_helpers

from .journal import RunJournal
from .types import Case, CaseTrace

_EVALS_DIR = Path(__file__).resolve().parent.parent
ENV_OPIK = _EVALS_DIR / ".env.opik"

# search_traces has no cursor — one call has to cover a project's whole history.
_MAX_TRACES = 50_000
_DELETE_BATCH = 10
_MAX_PROJECTS = 200


def load_opik_env(path: Path = ENV_OPIK) -> None:
    """Load .env.opik into the process.

    ``override=False`` keeps an already-exported variable winning over the file,
    so pointing a run at a different Opik instance from the shell still works.
    """
    load_dotenv(path, override=False)


def trace_id_for(project: str, case: CaseTrace) -> str:
    """The trace id a case owns in a project — same identity, same id, always.

    Seeding used to be idempotent by *lookup*: read every existing trace, skip
    the ones already present. That loses a race it cannot see. Opik buffers
    writes on a background sender, so a trace written by the live run at 05:23
    is not queryable for some seconds after; a seed that snapshots existing keys
    before then finds nothing and writes a second copy. That is exactly what the
    duplicates look like on inspection — one complete trace with its llm span,
    and a span-less twin created ~3 minutes later.

    Deriving the id from the identity removes the race instead of narrowing it:
    re-writing the same case becomes an upsert (verified against this backend —
    two writes of one id leave one trace, last write wins), so a re-seed is
    idempotent whether or not the first write has landed yet.

    Opik requires a UUIDv7, whose leading 48 bits are a millisecond timestamp,
    so the case's own start time supplies those and the hash supplies the rest.
    """
    return _stable_uuid7(f"trace|{project}|{case.key}", case.started_at)


def span_id_for(project: str, case: CaseTrace) -> str:
    """The llm span's id, stable for the same reason its trace's id is.

    Without this a re-write upserts the trace but appends a second span, so the
    cost and tokens the span carries would be counted twice.
    """
    return _stable_uuid7(f"span|{project}|{case.key}", case.started_at)


def _stable_uuid7(key: str, when: datetime) -> str:
    digest = bytearray(hashlib.blake2b(key.encode(), digest_size=16).digest())
    digest[6] = 0x40 | (digest[6] & 0x0F)  # claim version 4 for uuid4_to_uuid7
    digest[8] = 0x80 | (digest[8] & 0x3F)  # RFC 4122 variant
    return str(id_helpers.uuid4_to_uuid7(when, str(uuid.UUID(bytes=bytes(digest)))))


_CLIENTS: dict[str, opik.Opik] = {}


def client(project_name: str) -> opik.Opik:
    """One client per project, reused.

    Building a client per trace (and flushing on each) is what turned seeding
    thousands of journal records into an hours-long job.
    """
    if project_name not in _CLIENTS:
        _CLIENTS[project_name] = opik.Opik(project_name=project_name)
    return _CLIENTS[project_name]


def flush(project_name: str) -> None:
    client(project_name).flush()


def close_clients() -> None:
    """Shut every cached client down.

    The SDK runs its batch sender on non-daemon threads, so a process that only
    flushes keeps running after its work is done — which is why seeding appeared
    to "die silently" over and over: it had finished and was hanging, not
    crashing. Ending the clients is what actually lets the process exit.
    """
    for name, opik_client in list(_CLIENTS.items()):
        try:
            opik_client.end()
        except Exception as e:
            print(f"[opik] client for {name} did not shut down cleanly: {type(e).__name__}: {e}")
    _CLIENTS.clear()


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

    opik_client = client(project)
    dataset = opik_client.get_or_create_dataset(name=f"{project}-cases", project_name=project)
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


def log_case_trace(project: str, case: CaseTrace) -> None:
    """Write one case execution as a trace. Buffered — call ``flush`` when done.

    The trace carries an ``llm`` child span holding usage, model, provider and
    cost. That span is not decoration: Opik derives a trace's
    ``total_estimated_cost``, its token totals, and the ``model``/``provider``
    breakdowns from spans, so metadata alone leaves the project list, the COST
    and TOKEN_USAGE metrics, and every cost widget reading zero.
    """
    trace = client(project).trace(
        id=trace_id_for(project, case),
        name=case.name,
        start_time=case.started_at,
        end_time=case.ended_at,
        input={"prompt": case.prompt},
        output={"text": case.output},
        metadata=case.metadata,
        tags=[project, case.status],
        error_info=case.error_info,
    )
    trace.span(
        id=span_id_for(project, case),
        name=f"{case.provider}:{case.model}",
        type="llm",
        start_time=case.started_at,
        end_time=case.ended_at,
        input={"prompt": case.prompt},
        output={"text": case.output},
        metadata=case.metadata,
        model=case.model,
        provider=case.provider,
        usage=case.usage,
        total_cost=case.cost_usd,
        error_info=case.error_info,
    )
    for name, value in case.scores.items():
        trace.log_feedback_score(name=name, value=value)


def purge_case_traces(project: str) -> int:
    """Delete every ``case-*`` trace in a project.

    Only needed to evict traces whose source journal is gone — a plain re-seed
    already refreshes everything in place, because the ids are derived from the
    case identity. To empty a project wholesale, delete the project instead
    (``ingest``): a single trace delete costs ~3.5s on this backend.
    """
    ids = [
        trace.id
        for trace in client(project).search_traces(project_name=project, max_results=_MAX_TRACES)
        # A trace's name is nullable, and an unnamed one used to abort the whole
        # backfill here — which is exactly how three projects ended up empty.
        if (trace.name or "").startswith("case-")
    ]
    return delete_traces(project, ids) if ids else 0


def delete_traces(project: str, trace_ids: list[str]) -> int:
    """Delete traces in small batches, returning how many actually went.

    The self-hosted backend 500s on larger batches (25 is already too many), and
    a batch that fails takes its whole slice with it — so a failed batch is
    retried one id at a time before giving up on the stragglers.
    """
    traces = client(project).rest_client.traces
    deleted = 0
    for start in range(0, len(trace_ids), _DELETE_BATCH):
        batch = trace_ids[start : start + _DELETE_BATCH]
        try:
            traces.delete_traces(ids=batch)
            deleted += len(batch)
            continue
        except Exception as e:
            print(
                f"[opik] batch delete of {len(batch)} failed ({type(e).__name__}) — retrying singly"
            )
        for trace_id in batch:
            try:
                traces.delete_traces(ids=[trace_id])
                deleted += 1
            except Exception as e:
                print(f"[opik] could not delete trace {trace_id}: {type(e).__name__}: {e}")
    return deleted


def set_description(project: str, description: str) -> None:
    opik_client = client(project)
    found = opik_client.rest_client.projects.find_projects(page=1, size=_MAX_PROJECTS, name=project)
    for existing in found.content:
        if existing.name == project:
            opik_client.rest_client.projects.update_project(id=existing.id, description=description)
            return
    raise LookupError(f"Opik project '{project}' does not exist — run the suite first")


def experiment_name(run_dir: Path) -> str | None:
    meta_file = run_dir / "run.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text())
    return meta.get("experiment_name")
