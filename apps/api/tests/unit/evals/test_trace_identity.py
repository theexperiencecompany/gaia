"""A trace must be attributable, and writing it twice must not make two.

Both properties failed in production and neither was caught, because both were
checked by reading the writer rather than the result:

* every case trace carried its run under the key ``run``, so an audit looking
  for ``run_id`` concluded nothing was attributable and that the corrupt runs
  could not be excluded from a total;
* seeding deduplicated by querying Opik for what already existed, which loses to
  the SDK's write buffering and left 61 duplicate traces.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.evals.core.ingest_check import REQUIRED_METADATA
from scripts.evals.core.opiksink import span_id_for, trace_id_for
from scripts.evals.core.types import CaseTrace, ProviderPrice

PRICES = {"nous": ProviderPrice(price_in_per_1m=1.0, price_out_per_1m=2.0)}
RUN_ID = "capability-20260808-093921-98a7ac"
APP_VERSION = "api-v0.17.0-299-gc32f2f973"

RECORD = {
    "case_id": "cap-todo-create",
    "ticket": "can it create a todo",
    "prompt": "add milk to my list",
    "text": "added",
    "status": "passed",
    "provider": "nous",
    "model": "deepseek-v4",
    "category": "todos",
    "scores": {"end_state": 1.0},
    "tokens": {"input": 1200, "output": 340},
    "duration_s": 4.2,
    "ts": "2026-08-08T09:39:20+00:00",
}


def _trace(**overrides: object) -> CaseTrace:
    record = {**RECORD, **overrides}
    return CaseTrace.from_record(
        RUN_ID, record, PRICES, suite="capability", app_version=APP_VERSION
    )


@pytest.mark.parametrize("key", REQUIRED_METADATA)
def test_metadata_carries_every_key_the_check_requires(key: str) -> None:
    """The writer and the verifier must not be able to drift apart.

    Parametrising over ``REQUIRED_METADATA`` means adding a key to the check
    without emitting it fails here, rather than silently failing every future
    ingest.
    """
    assert _trace().metadata.get(key), f"trace metadata is missing {key!r}"


def test_run_id_is_not_published_under_the_old_name() -> None:
    """`run` was the name that made the data look absent. It must not come back."""
    metadata = _trace().metadata
    assert metadata["run_id"] == "capability-20260808-093921-98a7ac"
    assert "run" not in metadata


def test_the_same_case_and_run_always_get_the_same_ids() -> None:
    trace = _trace()
    assert trace_id_for("gaia-capability", trace) == trace_id_for("gaia-capability", _trace())
    assert span_id_for("gaia-capability", trace) == span_id_for("gaia-capability", _trace())


def test_ids_are_uuid_v7_because_opik_rejects_anything_else() -> None:
    from uuid import UUID

    trace = _trace()
    assert UUID(trace_id_for("gaia-capability", trace)).version == 7
    assert UUID(span_id_for("gaia-capability", trace)).version == 7


def test_a_trace_and_its_span_do_not_share_an_id() -> None:
    trace = _trace()
    assert trace_id_for("gaia-capability", trace) != span_id_for("gaia-capability", trace)


def test_different_cases_runs_and_projects_get_different_ids() -> None:
    """The mutation check: if the id ignored any part of the identity, a re-seed
    would collapse distinct executions onto one trace instead of duplicating
    them — silent data loss, which is worse than the duplicates it replaced."""
    base = trace_id_for("gaia-capability", _trace())
    other_case = trace_id_for("gaia-capability", _trace(case_id="cap-todo-delete"))
    other_project = trace_id_for("gaia-quality", _trace())
    other_run = trace_id_for(
        "gaia-capability",
        CaseTrace.from_record(
            "capability-20260101-000000-aaaaaa",
            dict(RECORD),
            PRICES,
            suite="capability",
            app_version="api-v0.17.0-299-gc32f2f973",
        ),
    )
    assert len({base, other_case, other_project, other_run}) == 4


def test_a_later_run_of_the_same_case_is_a_distinct_trace() -> None:
    """Re-running a case is a new execution, not a duplicate of the old one."""
    first = trace_id_for("gaia-capability", _trace())
    second = trace_id_for(
        "gaia-capability",
        CaseTrace.from_record(
            "capability-20260809-111111-bbbbbb",
            dict(RECORD),
            PRICES,
            suite="capability",
            app_version="api-v0.17.0-299-gc32f2f973",
        ),
    )
    assert first != second


def test_ids_are_stable_across_processes() -> None:
    """Derived from a content hash, not from anything process-local.

    Comparing two calls inside one process would pass even if the id were
    memoised from a random seed drawn at import. Seeding runs in a fresh process
    every time, so the id has to survive one — this computes it in a subprocess
    and compares. If it did not hold, every re-seed would duplicate everything.
    """
    # The child builds the trace from the same literals rather than importing
    # this module: importing it would pull pytest, ingest_check and litellm into
    # a process whose only job is one hash, and the SDK-free ``trace_id_for``
    # is exactly what seeding relies on.
    source = (
        "import json;"
        "from scripts.evals.core.opiksink import trace_id_for;"
        "from scripts.evals.core.types import CaseTrace, ProviderPrice;"
        f"record = json.loads({json.dumps(json.dumps(RECORD))});"
        "prices = {'nous': ProviderPrice(price_in_per_1m=1.0, price_out_per_1m=2.0)};"
        f"trace = CaseTrace.from_record({RUN_ID!r}, record, prices, suite='capability', "
        f"app_version={APP_VERSION!r});"
        "print(trace_id_for('gaia-capability', trace))"
    )
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[3],
        check=True,
    )
    assert result.stdout.strip() == trace_id_for("gaia-capability", _trace())


def test_uuid7_derivation_matches_the_sdk() -> None:
    """``_uuid4_to_uuid7`` is a copy of the SDK's; a drift would re-key every trace."""
    from datetime import UTC, datetime
    import uuid

    from opik import id_helpers
    from scripts.evals.core.opiksink import _uuid4_to_uuid7

    when = datetime(2026, 8, 8, 9, 39, 21, tzinfo=UTC)
    for _ in range(20):
        seed = uuid.uuid4()
        assert _uuid4_to_uuid7(when, seed) == id_helpers.uuid4_to_uuid7(when, str(seed))
