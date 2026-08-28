"""Opik sink: per-case traces + experiment finalize by replaying the journal.

Runs log one trace per case with feedback scores; at finalize the same cases are
synced as a dataset and evaluated via ``opik.evaluation.evaluate`` with a
replay task (no agent re-run) so every run becomes a comparable experiment.

Every write is keyed by ``CaseTrace.key`` (case + run), which is what lets
``seed`` backfill past journals repeatedly without duplicating anything.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
from http import HTTPStatus
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack
import uuid

from dotenv import load_dotenv

from .journal import RunJournal
from .types import Case, CaseTrace

# ``opik`` costs ~1.3s to import and is only needed to talk to the backend, so
# every SDK import is function-local: id derivation (``trace_id_for``, the
# child interpreter in test_trace_identity, seed dry-runs) never pays for it.
if TYPE_CHECKING:
    import opik

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
    return _stable_uuid7(f"trace|{project}|{case.key}", _identity_time(case))


def span_id_for(project: str, case: CaseTrace) -> str:
    """The llm span's id, stable for the same reason its trace's id is.

    Without this a re-write upserts the trace but appends a second span, so the
    cost and tokens the span carries would be counted twice.
    """
    return _stable_uuid7(f"span|{project}|{case.key}", _identity_time(case))


#: Run ids look like ``capability-20260808-063606-c9077b``.
_RUN_ID_TIMESTAMP = re.compile(r"(\d{8})-(\d{6})")


def _identity_time(case: CaseTrace) -> datetime:
    """The timestamp half of a derived id — stable for one (case, run).

    A UUIDv7's leading 48 bits are a millisecond clock, so whatever goes here is
    part of the id. Using the case's own ``started_at`` looked natural and was
    wrong: a resumed run journals the same case twice with timestamps tens of
    milliseconds apart, so the "deterministic" id differed between the two
    records and the second write inserted a duplicate instead of updating. Three
    such pairs survived a full rebuild and the check caught them — the ids were
    identical in their hash half and differed only in the clock half.

    The run id already carries the run's own start, so it gives every record of
    the same run the same value without needing anything from the record.
    """
    found = _RUN_ID_TIMESTAMP.search(case.run_id)
    if not found:
        return case.ended_at
    return datetime.strptime(f"{found.group(1)}{found.group(2)}", "%Y%m%d%H%M%S").replace(
        tzinfo=UTC
    )


def _stable_uuid7(key: str, when: datetime) -> str:
    digest = bytearray(hashlib.blake2b(key.encode(), digest_size=16).digest())
    digest[6] = 0x40 | (digest[6] & 0x0F)  # claim version 4 for uuid4_to_uuid7
    digest[8] = 0x80 | (digest[8] & 0x3F)  # RFC 4122 variant
    return str(_uuid4_to_uuid7(when, uuid.UUID(bytes=bytes(digest))))


def _uuid4_to_uuid7(when: datetime, uuid4: uuid.UUID) -> uuid.UUID:
    """``opik.id_helpers.uuid4_to_uuid7``, byte for byte.

    Copied rather than imported because importing it drags the whole SDK in.
    ``test_trace_identity`` pins it against the SDK's own function: any drift
    would re-key every seeded trace and duplicate the projects on the next seed.
    """
    if uuid4.version != 4:
        raise ValueError("Input UUID must be version 4")
    out = bytearray(16)
    out[0:6] = int(when.timestamp() * 1000).to_bytes(6, byteorder="big")
    out[6] = 0x70 | (uuid4.bytes[6] & 0x0F)
    out[7] = uuid4.bytes[7]
    out[8] = 0x80 | (uuid4.bytes[8] & 0x3F)
    out[9:16] = uuid4.bytes[9:16]
    return uuid.UUID(bytes=bytes(out))


_CLIENTS: dict[str, opik.Opik] = {}


def client(project_name: str) -> opik.Opik:
    """One client per project, reused.

    Building a client per trace (and flushing on each) is what turned seeding
    thousands of journal records into an hours-long job.
    """
    if project_name not in _CLIENTS:
        import opik

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


class ExperimentOptions(TypedDict):
    """What to call the Opik experiment and how to score it (see ``finalize``)."""

    scoring_metrics: list[object]
    experiment_name: str
    tags: list[str]
    nb_samples: NotRequired[int | None]


def finalize(
    project: str,
    cases: list[Case],
    journal: RunJournal,
    replay: Callable[[dict[str, object]], dict[str, object]],
    **experiment: Unpack[ExperimentOptions],
) -> object:
    """Evaluate the journal's stored outputs as an Opik experiment.

    ``replay(item)`` returns the stored run output for a case (never calls the
    agent again); metrics see dataset-item keys merged with those outputs.
    """
    from opik.evaluation import evaluate

    opik_client = client(project)
    dataset = _dataset_for(opik_client, f"{project}-cases", project)
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
        scoring_metrics=experiment["scoring_metrics"],
        experiment_name=experiment["experiment_name"],
        experiment_tags=experiment["tags"],
        nb_samples=experiment.get("nb_samples"),
        task_threads=4,
        verbose=1,
    )
    journal.update_meta(experiment_name=experiment["experiment_name"])
    return result


def _dataset_for(opik_client: opik.Opik, name: str, project: str) -> opik.Dataset:
    """Fetch or create the run's dataset, without the project-scoped deadlock.

    ``get_or_create_dataset`` looks the dataset up *within a project* but dataset
    names are unique per workspace. Deleting a project therefore orphans its
    dataset: the project-scoped get 404s, the create then 409s on the name that
    still exists, and every subsequent finalize fails forever. That is exactly
    what happened after the first purge.

    Looking it up by name — its real identity — resolves the orphan. The create
    is still guarded, because two runs finalizing at once would otherwise race.
    """
    from opik.rest_api.core.api_error import ApiError

    try:
        return opik_client.get_dataset(name)
    except ApiError as e:
        if e.status_code != HTTPStatus.NOT_FOUND:
            raise
    try:
        return opik_client.create_dataset(name, project_name=project)
    except ApiError as e:
        if e.status_code != HTTPStatus.CONFLICT:
            raise
        return opik_client.get_dataset(name)


def delete_datasets(names: list[str]) -> list[str]:
    """Remove datasets by name, ignoring the ones that are already gone.

    Teardown deletes projects; datasets live beside them in the workspace and
    would otherwise survive as orphans that no project-scoped lookup can find.
    """
    from opik.rest_api.core.api_error import ApiError

    opik_client = client("default")
    gone: list[str] = []
    for name in names:
        try:
            opik_client.delete_dataset(name)
            gone.append(name)
        except ApiError as e:
            if e.status_code != HTTPStatus.NOT_FOUND:
                raise
    return gone


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
        # Every attempt at one case shares a thread, so Opik's Threads view
        # shows a case's history across runs in one place instead of leaving
        # each attempt to be hunted down by name.
        thread_id=f"{case.suite}:{case.case_id}",
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
        # Usage rides the span only when the provider actually reported it.
        # Opik prices span usage against its own model table whenever
        # total_cost is absent — so attaching an estimated or legacy count
        # here resurrects exactly the phantom cost the pricing guard removed.
        # Untrusted counts stay in metadata, where nothing prices them.
        usage=case.usage if case.tokens_trusted else None,
        # None, not 0.0, when the tokens behind it were never metered: Opik sums
        # what it is given, and a zero would read as "this case was free" rather
        # than "nobody measured it".
        total_cost=case.cost_usd if case.tokens_trusted else None,
        error_info=case.error_info,
    )
    # The agent's actual actions, one `tool` span per call — without these a
    # reader inspecting a failed case sees only the final text and has to open
    # the journal to learn what the agent did. Ids derive from the trace key
    # and position, so a re-seed upserts rather than appending twins.
    for index, call in enumerate(case.tool_calls):
        trace.span(
            id=_stable_uuid7(f"tool|{project}|{case.key}|{index}", _identity_time(case)),
            name=str(call.get("name") or call.get("tool") or f"tool-{index}"),
            type="tool",
            start_time=case.started_at,
            end_time=case.ended_at,
            input={"arguments": call.get("args") or call.get("arguments") or {}},
            output={"result": call.get("result") or call.get("output") or ""},
        )
    for name, value in case.scores.items():
        trace.log_feedback_score(name=name, value=value)


def legacy_case_traces(project: str, expected_ids: set[str]) -> int:
    """Case traces in ``project`` that a re-seed would duplicate rather than update.

    Upsert-by-id only protects traces that were written WITH the derived id.
    Anything written before that — every trace currently in Opik — carries a
    random id, so seeding on top of it inserts a second copy rather than
    replacing it, silently doubling every count, cost and token total.

    This is why the rebuild tears the projects down first. Seeding without a
    teardown must say so loudly rather than quietly double the data.
    """
    from opik.rest_api.core.api_error import ApiError

    try:
        traces = client(project).search_traces(project_name=project, max_results=_MAX_TRACES)
    except ApiError as e:
        if e.status_code != HTTPStatus.NOT_FOUND:
            raise
        # A project that does not exist holds nothing to duplicate. This is the
        # normal state immediately after a teardown, and treating it as an error
        # made the rebuild unable to seed the projects it had just deleted.
        return 0
    return sum(
        1
        for trace in traces
        if (trace.name or "").startswith("case-") and trace.id not in expected_ids
    )


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
