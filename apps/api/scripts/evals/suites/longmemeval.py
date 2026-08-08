"""LongMemEval suite — wraps the existing memory_benchmark LongMemEval runner.

Reuses scripts.memory_benchmark.longmemeval (real extraction/reconciliation,
LLM judge) and records each question as a harness case so the run gets the
journal/report/Opik treatment. Needs an external dataset file
(longmemeval_*.json — oracle format); fails loudly without it.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
from typing import Any, ClassVar

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.gates import SELF_SCORED, ExtraGates, validate_gates
from scripts.evals.core.providers import EvalConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.types import Case, CaseRun, InfraError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "longmemeval"
DEFAULT_DATASET = DATA_DIR / "longmemeval_oracle.json"


@register_suite("longmemeval")
class LongMemEvalSuite(Suite):
    name = "longmemeval"
    project = "gaia-longmemeval"
    label = "LongMemEval"

    #: Scored inside this suite's own ``score()`` from the transport's end
    #: state, not through the shared dispatcher — a benchmark verdict, not a
    #: reusable check. Declared so load-time validation knows the name is real.
    EXTRA_GATES: ClassVar[ExtraGates] = {"gaia_exact": SELF_SCORED}

    def __init__(self, cfg: EvalConfig) -> None:
        self.cfg = cfg
        self._items: list[dict[str, Any]] | None = None
        self._backend_ready = False

    def _load_items(self) -> list[dict[str, Any]]:
        if self._items is not None:
            return self._items
        if not DEFAULT_DATASET.exists():
            raise SystemExit(
                f"LongMemEval dataset not found at {DEFAULT_DATASET}. "
                "Download the oracle JSONL (longmemeval_oracle.json) there and re-run."
            )
        with DEFAULT_DATASET.open() as f:
            data = json.load(f)
        self._items = data if isinstance(data, list) else []
        return self._items

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg

        items = [
            i for i in self._load_items() if not str(i.get("question_id", "")).endswith("_abs")
        ]
        by_type: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_type.setdefault(item.get("question_type", "?"), []).append(item)
        rng = random.Random(7)
        sampled: list[dict[str, Any]] = []
        for qtype, bucket in by_type.items():
            rng.shuffle(bucket)
            sampled.extend(bucket)
        cases: list[Case] = []
        for item in sampled:
            qtype = item.get("question_type", "?")
            cases.append(
                Case(
                    id=f"lme-{str(item.get('question_id', qtype))[:44]}",
                    ticket=item.get("question", "")[:160],
                    prompt=item.get("question", ""),
                    expected={
                        "category": qtype,
                        "gaia": {"ground_truth": item.get("answer")},
                        "score": {"gates": ["gaia_exact"]},
                    },
                    tags=["longmemeval", qtype],
                )
            )
        for case in cases:
            validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
        return cases

    def transport(self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider):
        del cfg
        return self._run_question(case, tracker, provider)

    async def _run_question(self, case: Case, tracker: EvalCostTracker, provider) -> CaseRun:
        import asyncio as _asyncio
        import os as _os

        deadline = float(_os.environ.get("EVALS_CASE_TIMEOUT_S", "420"))
        try:
            return await _asyncio.wait_for(
                self._run_question_inner(case, tracker, provider), timeout=deadline
            )
        except TimeoutError:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                error=f"question timed out after {deadline:.0f}s",
            )

    async def _ensure_backend(self, tracker: EvalCostTracker) -> None:
        """Register the memory backend once per run, then prove it is reachable.

        Registration must NOT repeat per case: ``providers.register`` replaces the
        LazyLoader, so re-registering discards the live engine (leaking its pool)
        and forces every case to rebuild one. Once Postgres goes away, that rebuild
        fails and the swallowed failure surfaces as a bare "engine not available"
        for every remaining case — which is how an outage got published as 0/64.
        """
        from app.db.postgresql import get_postgresql_engine

        if not self._backend_ready:
            from scripts.memory_benchmark import longmemeval as lme

            lme.init_postgresql_engine()
            lme.init_chroma()
            lme.register_llm_providers()

            import app.memory.extraction as extraction_mod

            extraction_mod._SILENT_CONFIG = {
                **extraction_mod._SILENT_CONFIG,
                "callbacks": [tracker],
            }
            self._backend_ready = True

        try:
            await get_postgresql_engine()
        except RuntimeError as e:
            raise InfraError("postgres", str(e)) from e

    async def _run_question_inner(self, case: Case, tracker: EvalCostTracker, provider) -> CaseRun:
        from scripts.memory_benchmark import longmemeval as lme

        await self._ensure_backend(tracker)

        question_id = case.id.removeprefix("lme-")
        items = self._load_items()
        matches = [i for i in items if str(i.get("question_id", "")) == question_id]
        if not matches:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                error="dataset item not found",
            )
        item = matches[0]
        tokens_in_before = tracker.total_input
        tokens_out_before = tracker.total_output
        qtype, correct, model_answer = await lme._run_question(item, 1, 1)
        return CaseRun(
            case_id=case.id,
            provider=provider.name,
            model=provider.model,
            messages=[
                {"role": "user", "content": case.prompt},
                {"role": "assistant", "content": model_answer or ""},
            ],
            tool_calls=[],
            end_state={"gaia_exact": 1.0 if correct else 0.0, "gold": item.get("answer")},
            text=model_answer or "",
            raw=[{"judge_verdict": bool(correct), "question_type": qtype}],
            tokens_in=tracker.total_input - tokens_in_before,
            tokens_out=tracker.total_output - tokens_out_before,
        )

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        del case
        if run.error:
            return {}
        exact = run.end_state or {}
        return {"gaia_exact": float(exact.get("gaia_exact", 0.0))}

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        from scripts.evals.core.scorers import ProviderQuality

        del cfg
        return [ProviderQuality()]
