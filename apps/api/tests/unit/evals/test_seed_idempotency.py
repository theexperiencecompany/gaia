"""Seeding the same case twice must update one trace, never write two.

The duplicates in Opik came from idempotency being enforced by a *lookup*: the
seeder asked Opik which traces existed and skipped those. Two things defeat that,
both silently:

* opik buffers writes, so a trace written seconds earlier is not yet queryable
  and the seeder writes it again;
* the lookup keyed on trace metadata, so renaming a metadata field made every
  key miss and every case duplicate.

Identity now comes from the journal (``CaseTrace.key``) and the trace id is
derived from it, so a second write targets the same row. These tests pin that,
and pin the loud failure for the one case it cannot cover — rows written before
derived ids existed, which a seed would still duplicate.
"""

from __future__ import annotations

from typing import Any
import uuid

import pytest
from scripts.evals.core import opiksink, seed as seed_module
from scripts.evals.core.types import CaseTrace, ProviderPrice

PRICES = {"nous": ProviderPrice(price_in_per_1m=1.0, price_out_per_1m=2.0)}
PROJECT = "gaia-capability"

RECORD: dict[str, Any] = {
    "case_id": "cap-todo-create",
    "ticket": "can it create a todo",
    "prompt": "add milk",
    "text": "added",
    "status": "passed",
    "provider": "nous",
    "model": "deepseek-v4",
    "tokens": {"input": 1200, "output": 340, "source": "metered"},
    "duration_s": 4.2,
    "ts": "2026-08-08T09:39:20+00:00",
}


def _trace(**overrides: Any) -> CaseTrace:
    return CaseTrace.from_record(
        "capability-20260808-093921-98a7ac",
        {**RECORD, **overrides},
        PRICES,
        suite="capability",
        app_version="api-v0.17.0",
    )


class _FakeTrace:
    def __init__(self, sink: dict[str, Any], trace_id: str) -> None:
        self._sink = sink
        self.id = trace_id

    def span(self, **kwargs: Any) -> None:
        self._sink.setdefault("spans", []).append(kwargs.get("id") or str(uuid.uuid4()))

    def log_feedback_score(self, **kwargs: Any) -> None:
        return None


class _FakeClient:
    """Records what a seed would send, keyed the way the backend keys it: by id."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.writes = 0
        self.sink: dict[str, Any] = {}

    def trace(self, **kwargs: Any) -> _FakeTrace:
        self.writes += 1
        # Faithful to the real backend on both branches: it upserts on a supplied
        # id (verified against the live Opik before this design was chosen), and
        # mints a fresh one when the caller omits it — which is exactly how the
        # duplicates were created. Minting here rather than raising KeyError is
        # what makes a regression fail as "two rows", the real symptom, instead
        # of as a crash that could be mistaken for a broken test.
        trace_id = kwargs.get("id") or str(uuid.uuid4())
        self.rows[trace_id] = kwargs
        return _FakeTrace(self.sink, trace_id)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()
    monkeypatch.setattr(opiksink, "client", lambda _project: client)
    return client


def test_seeding_the_same_case_twice_leaves_one_trace(fake_client: _FakeClient) -> None:
    """The test the duplicates should have failed. Two writes, one row."""
    opiksink.log_case_trace(PROJECT, _trace())
    opiksink.log_case_trace(PROJECT, _trace())

    assert fake_client.writes == 2, "sanity: both writes were attempted"
    assert len(fake_client.rows) == 1, (
        f"seeding one case twice produced {len(fake_client.rows)} traces — every count, "
        f"cost and token total in this project is doubled"
    )


def test_the_span_is_not_duplicated_either(fake_client: _FakeClient) -> None:
    """A duplicated span double-counts the cost and tokens it carries."""
    opiksink.log_case_trace(PROJECT, _trace())
    opiksink.log_case_trace(PROJECT, _trace())
    assert len(set(fake_client.sink["spans"])) == 1


def test_re_seeding_refreshes_rather_than_skips(fake_client: _FakeClient) -> None:
    """The second write must win, or a fixed journal could never reach Opik."""
    opiksink.log_case_trace(PROJECT, _trace(status="failed"))
    opiksink.log_case_trace(PROJECT, _trace(status="passed"))
    (row,) = fake_client.rows.values()
    assert row["metadata"]["status"] == "passed"


def test_a_metadata_rename_cannot_defeat_idempotency(fake_client: _FakeClient) -> None:
    """The root cause, pinned.

    Identity is derived from the journal, so changing what we *publish* as
    metadata must not change which row a case writes to. If this ever fails,
    idempotency has been coupled back to metadata and the next rename will
    silently duplicate everything again.
    """
    before = opiksink.trace_id_for(PROJECT, _trace())
    renamed = _trace()
    object.__setattr__(renamed, "category", "totally-different-metadata")
    assert opiksink.trace_id_for(PROJECT, renamed) == before


def test_a_resumed_run_journalling_a_case_twice_still_writes_one_trace(
    fake_client: _FakeClient,
) -> None:
    """The bug a full rebuild found, after the first idempotency fix looked done.

    A resumed run writes the same case twice with slightly different timestamps
    and durations. The derived id embedded the case's own start time (a UUIDv7
    carries a millisecond clock in its first 48 bits), so the two records
    produced ids that matched in their hash half and differed in their clock
    half — and the second inserted a duplicate. Three of these survived a full
    rebuild of nine projects.
    """
    first = _trace(ts="2026-08-08T06:36:12.100000+00:00", duration_s=4.20)
    second = _trace(ts="2026-08-08T06:36:12.140000+00:00", duration_s=4.19)
    # Deliberately not a 40ms shift in both: started_at is ts minus duration, so
    # shifting each by the same amount cancels and the sanity check below would
    # pass while comparing two identical values.
    assert first.started_at != second.started_at, "sanity: the records really do differ"

    opiksink.log_case_trace(PROJECT, first)
    opiksink.log_case_trace(PROJECT, second)
    assert len(fake_client.rows) == 1, (
        "a case journalled twice within one run produced two traces — this is the "
        "resume path, and it inflates every count in the project"
    )


def test_two_different_cases_are_not_collapsed(fake_client: _FakeClient) -> None:
    """The opposite failure: silently losing a case is worse than duplicating it."""
    opiksink.log_case_trace(PROJECT, _trace())
    opiksink.log_case_trace(PROJECT, _trace(case_id="cap-todo-delete"))
    assert len(fake_client.rows) == 2


def test_seeding_over_legacy_traces_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows written before derived ids exist would still be duplicated.

    Upsert cannot help there — the old row has a random id. That case has to
    abort with an instruction, not quietly double the project.
    """
    monkeypatch.setattr(opiksink, "legacy_case_traces", lambda _project, _expected: 387)
    with pytest.raises(seed_module.LegacyTracesPresentError) as caught:
        seed_module._refuse_to_double(PROJECT, [_trace()])
    assert "387" in str(caught.value)
    assert "ingest" in str(caught.value), "the error must name the way out"


def test_the_legacy_guard_passes_when_every_row_is_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A guard that always fires is as useless as one that never does."""
    monkeypatch.setattr(opiksink, "legacy_case_traces", lambda _project, _expected: 0)
    seed_module._refuse_to_double(PROJECT, [_trace()])
