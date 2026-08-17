"""What a case's tokens are, and who decides.

Every suite used to decide for itself, and they disagreed: a delta on a shared
meter (correct only when one case runs at a time), a per-provider running total
(never correct), a character estimate of the prompt (low by orders of
magnitude). Concurrency then made the first kind credit each case with whatever
every other in-flight case was spending — a capability run journaled a median of
390,716 input tokens per case against a run total that could not support it.

The harness answers it once now, from a per-case meter. These pin that, and pin
that an estimate can never quietly pass for a measurement.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult
import pytest
from scripts.evals.core import runner
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.journal import RunJournal
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.types import Case, CaseRun


def _llm_result(input_tokens: int, output_tokens: int) -> LLMResult:
    message = AIMessage(
        content="answer",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


SPEND = {"a": (10_000, 500), "b": (20_000, 900), "c": (30_000, 100)}


class _ConcurrentSuite(runner.Suite):
    """Three cases that overlap, each spending a different, known amount.

    The self-reported figure is deliberately the whole-run total — exactly what
    a before/after delta on the shared meter produces under concurrency.
    """

    name = "demo"
    label = "Demo"

    def __init__(self) -> None:
        self.entered = asyncio.Barrier(len(SPEND))

    async def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        tokens_in, tokens_out = SPEND[case.id]
        await self.entered.wait()  # every case is in flight before any spends
        tracker.on_llm_end(_llm_result(tokens_in // 2, tokens_out // 2))
        await asyncio.sleep(0)
        tracker.on_llm_end(_llm_result(tokens_in // 2, tokens_out // 2))
        contaminated_in = sum(v[0] for v in SPEND.values())
        return CaseRun(case_id=case.id, text="answer", tokens_in=contaminated_in, tokens_out=0)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        return {}


async def _run_concurrently(tmp_path: Path) -> dict[str, dict[str, Any]]:
    journal = RunJournal(tmp_path, "run-1")
    tracker = EvalCostTracker({}, 0.0)
    suite = _ConcurrentSuite()
    cases = [Case(id=cid, ticket="t", prompt="p") for cid in SPEND]
    opts = runner.RunOptions(suite="demo", concurrency=len(SPEND))

    def record_case(
        case: Case, run: CaseRun, scores: dict[str, float], status: str, error: str | None
    ) -> None:
        source = runner._attribute_tokens(run, tracker, case.id)
        journal.append(runner._record(case, run, scores, status, error, source))

    class _Provider:
        name = "opencode"
        model = "m"

    aborted = await runner._run_cases_concurrently(
        cases, suite, None, opts, tracker, _Provider(), "opencode", record_case
    )
    assert aborted is None
    return journal.latest_per_case()


async def test_a_case_is_charged_only_for_what_it_spent(tmp_path: Path) -> None:
    records = await _run_concurrently(tmp_path)
    for case_id, (tokens_in, tokens_out) in SPEND.items():
        assert records[case_id]["tokens"]["input"] == tokens_in, case_id
        assert records[case_id]["tokens"]["output"] == tokens_out, case_id


async def test_the_per_case_figures_sum_to_the_run_total(tmp_path: Path) -> None:
    """The cross-check the publish gate makes. Under the old delta this summed
    to roughly concurrency times the truth."""
    records = await _run_concurrently(tmp_path)
    journalled = sum(int(r["tokens"]["input"]) for r in records.values())
    assert journalled == sum(v[0] for v in SPEND.values())


async def test_a_metered_case_is_labelled_as_measured(tmp_path: Path) -> None:
    records = await _run_concurrently(tmp_path)
    assert {r["tokens"]["source"] for r in records.values()} == {runner.TOKENS_METERED}


def test_a_transport_that_measures_nothing_is_labelled_an_estimate() -> None:
    """gaia_bench and hil: their endpoints report no usage, so their figure is a
    character estimate. It stays, but it can no longer pass for a measurement."""
    tracker = EvalCostTracker({}, 0.0)
    run = CaseRun(case_id="g", text="x", tokens_in=56, tokens_out=12)
    assert runner._attribute_tokens(run, tracker, "g") == runner.TOKENS_ESTIMATED
    assert run.tokens_in == 56


def test_the_meter_overrides_a_transports_own_figure() -> None:
    """A suite computing its own number cannot outvote the meter — that is what
    made five suites disagree."""
    tracker = EvalCostTracker({}, 0.0)
    tracker.set_provider("opencode")
    with tracker.case_scope("k"):
        tracker.on_llm_end(_llm_result(4_000, 200))
    run = CaseRun(case_id="k", text="x", tokens_in=999_999, tokens_out=999_999)
    assert runner._attribute_tokens(run, tracker, "k") == runner.TOKENS_METERED
    assert (run.tokens_in, run.tokens_out) == (4_000, 200)


def test_nothing_measured_and_nothing_claimed_is_neither(tmp_path: Path) -> None:
    tracker = EvalCostTracker({}, 0.0)
    run = CaseRun(case_id="e", error="boom")
    assert runner._attribute_tokens(run, tracker, "e") == runner.TOKENS_NONE


def test_manual_usage_lands_on_the_case_that_reported_it() -> None:
    """The HTTP suites read usage off the API's own frames and hand it over."""
    tracker = EvalCostTracker({}, 0.0)
    with tracker.case_scope("q1"):
        tracker.add_manual("opencode", 22_713, 1_004)
    with tracker.case_scope("q2"):
        tracker.add_manual("opencode", 159_306, 2_881)
    assert tracker.case_totals("q1") == (22_713, 1_004)
    assert tracker.case_totals("q2") == (159_306, 2_881)
    assert tracker.total_input == 182_019


@pytest.mark.parametrize("case_id", ["a", "b", "c"])
async def test_no_case_is_credited_with_the_whole_run(tmp_path: Path, case_id: str) -> None:
    """The delta's worst symptom: the last case to finish carried nearly the
    entire run's spend, and the first carried most of it too."""
    records = await _run_concurrently(tmp_path)
    run_total = sum(v[0] for v in SPEND.values())
    assert int(records[case_id]["tokens"]["input"]) < run_total
