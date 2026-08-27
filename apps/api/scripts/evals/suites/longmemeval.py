"""LongMemEval suite — wraps the existing memory_benchmark LongMemEval runner.

Reuses scripts.memory_benchmark.longmemeval (real extraction/reconciliation,
LLM judge) and records each question as a harness case so the run gets the
journal/report/Opik treatment. Needs an external dataset file
(longmemeval_*.json — oracle format); fails loudly without it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import json
import os
from pathlib import Path
import random
from typing import Any, ClassVar

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.gates import SELF_SCORED, ExtraGates, validate_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import ProviderQuality
from scripts.evals.core.types import Case, CaseRun, InfraError

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "longmemeval"
DEFAULT_DATASET = DATA_DIR / "longmemeval_oracle.json"
DEFAULT_CASE_TIMEOUT_S = 420.0


def _case_timeout_s() -> float:
    """Per-question wall clock, overridable via ``EVALS_CASE_TIMEOUT_S``.

    A non-numeric value fails here, by name, rather than as a bare ``ValueError``
    from ``float()`` half a run into a suite.
    """
    raw = os.environ.get("EVALS_CASE_TIMEOUT_S")
    if raw is None:
        return DEFAULT_CASE_TIMEOUT_S
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(
            f"EVALS_CASE_TIMEOUT_S must be a number of seconds, got {raw!r}."
        ) from None


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
        #: question_id -> byte offset into the JSONL sidecar. The whole parsed
        #: dataset used to sit on this attribute for the entire run so each case
        #: could linear-scan it; now only the offsets stay resident and each
        #: case reads exactly its own line on demand.
        self._offsets: dict[str, int] | None = None
        self._backend_ready = False

    def _jsonl_path(self) -> Path:
        return DEFAULT_DATASET.with_suffix(".jsonl")

    def _ensure_jsonl(self) -> Path:
        """Convert the oracle array to a JSONL sidecar once, so items can be
        read one line at a time instead of holding the parsed array all run."""
        if not DEFAULT_DATASET.exists():
            raise SystemExit(
                f"LongMemEval dataset not found at {DEFAULT_DATASET}. "
                "Download the oracle dataset (longmemeval_oracle.json — a single "
                "JSON array, not JSONL) there and re-run."
            )
        sidecar = self._jsonl_path()
        if sidecar.exists() and sidecar.stat().st_mtime >= DEFAULT_DATASET.stat().st_mtime:
            return sidecar
        with DEFAULT_DATASET.open() as f:
            data = json.load(f)
        # A non-list here used to become `[]`, and the suite then reported zero
        # cases as a successful run — the exact silent-empty outcome the module
        # docstring promises never to produce.
        if not isinstance(data, list):
            raise SystemExit(
                f"LongMemEval dataset at {DEFAULT_DATASET} is a {type(data).__name__}, "
                "not the JSON array the oracle format defines."
            )
        with sidecar.open("w") as out:
            for item in data:
                out.write(json.dumps(item, separators=(",", ":")) + "\n")
        return sidecar

    def _load_offsets(self) -> dict[str, int]:
        if self._offsets is not None:
            return self._offsets
        sidecar = self._ensure_jsonl()
        offsets: dict[str, int] = {}
        with sidecar.open("rb") as f:
            position = f.tell()
            for raw in iter(f.readline, b""):
                if raw.strip():
                    item = json.loads(raw)
                    offsets[str(item.get("question_id", ""))] = position
                position = f.tell()
        self._offsets = offsets
        return offsets

    def _read_item(self, question_id: str) -> dict[str, Any] | None:
        offset = self._load_offsets().get(question_id)
        if offset is None:
            return None
        with self._jsonl_path().open("rb") as f:
            f.seek(offset)
            item = json.loads(f.readline())
        return item if isinstance(item, dict) else None

    def _iter_items(self) -> list[dict[str, Any]]:
        """Transient full read for case listing; nothing retains the result."""
        sidecar = self._ensure_jsonl()
        with sidecar.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg

        items = [
            i for i in self._iter_items() if not str(i.get("question_id", "")).endswith("_abs")
        ]
        by_type: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            by_type.setdefault(item.get("question_type", "?"), []).append(item)
        rng = random.Random(7)
        sampled: list[dict[str, Any]] = []
        for bucket in by_type.values():
            rng.shuffle(bucket)
            sampled.extend(bucket)
        cases: list[Case] = []
        seen_ids: set[str] = set()
        for item in sampled:
            qtype = item.get("question_type", "?")
            question_id = str(item.get("question_id", qtype))
            # The id is trimmed for readability in the journal and the report;
            # the transport looks the item up by the FULL question_id carried in
            # setup, so a long id can no longer miss the dataset entirely.
            case_id = f"lme-{question_id[:44]}"
            if case_id in seen_ids:
                raise SystemExit(
                    f"LongMemEval case id {case_id!r} is not unique — two question_ids "
                    f"share its first 44 characters, so their runs would overwrite "
                    f"each other in the journal."
                )
            seen_ids.add(case_id)
            cases.append(
                Case(
                    id=case_id,
                    ticket=item.get("question", "")[:160],
                    prompt=item.get("question", ""),
                    expected={
                        "category": qtype,
                        "gaia": {"ground_truth": item.get("answer")},
                        "score": {"gates": ["gaia_exact"]},
                    },
                    setup={"question_id": question_id},
                    tags=["longmemeval", qtype],
                )
            )
        for case in cases:
            validate_gates(self.name, case.id, case.gates, self.EXTRA_GATES)
        return cases

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        del cfg
        return self._run_question(case, tracker, provider)

    async def _run_question(
        self, case: Case, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> CaseRun:
        deadline = _case_timeout_s()
        try:
            return await asyncio.wait_for(
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

    async def _run_question_inner(
        self, case: Case, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> CaseRun:
        from scripts.memory_benchmark import longmemeval as lme

        await self._ensure_backend(tracker)

        item = self._read_item(str(case.setup.get("question_id", "")))
        if item is None:
            return CaseRun(
                case_id=case.id,
                provider=provider.name,
                model=provider.model,
                error="dataset item not found",
            )
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
        del cfg
        return [ProviderQuality()]
