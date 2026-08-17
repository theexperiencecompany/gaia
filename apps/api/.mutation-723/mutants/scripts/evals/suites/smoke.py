"""Smoke suite: 3 toy cases with a fake transport.

Verifies the loop end-to-end without touching the app: rotation on provider
error (case smoke-3 fails on `nous`), journaling, resume, scoring, and the
HTML report. The transport simulates token usage so cost tables populate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.gates import score_gates, validate_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    BubbleBoundary,
    CommunicateGate,
    EndStateEquality,
    ProviderQuality,
    ToolCallCorrectness,
)
from scripts.evals.core.types import Case, CaseRun, ProviderError


class SmokeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> CaseRun:
        del cfg, tracker
        self.calls.append((case.id, provider.name))
        await asyncio.sleep(0.05)
        if case.id == "smoke-3" and provider.name == "nous":
            raise ProviderError(provider.name, "simulated provider outage")
        text = {
            "smoke-1": "The capital of France is Paris.",
            "smoke-2": "Your todo 'Buy milk' is created.",
            "smoke-3": "Created the report.",
        }[case.id]
        messages = [
            {"role": "user", "content": case.prompt},
            {"role": "assistant", "content": text},
        ]
        return CaseRun(
            case_id=case.id,
            messages=messages,
            tool_calls=[{"name": "create_todo", "args": {"title": "Buy milk"}}]
            if case.id == "smoke-2"
            else [],
            end_state={"todos": [{"title": "Buy milk"}]} if case.id == "smoke-2" else None,
            text=text,
            tokens_in=120,
            tokens_out=40,
            duration_s=0.05,
        )


@register_suite("smoke")
class SmokeSuite(Suite):
    name = "smoke"
    project = "gaia-smoke"
    label = "Smoke"

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._transport = SmokeTransport()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        cases = self._cases()
        for case in cases:
            validate_gates(self.name, case.id, case.gates)
        return cases

    def _cases(self) -> list[Case]:
        return [
            Case(
                id="smoke-1",
                ticket="Trivial recall — agent must answer directly.",
                prompt="What is the capital of France?",
                expected={
                    "category": "SINGLE_HOP",
                    "communicate": ["Paris"],
                    "score": {"gates": ["communicate"]},
                },
            ),
            Case(
                id="smoke-2",
                ticket="Tool use — create a todo and confirm it.",
                prompt="Create a todo for buying milk.",
                expected={
                    "category": "TOOL_USE",
                    "tool_calls": [{"tool": "create_todo"}],
                    "end_state": {"todos": [{"title": "Buy milk"}]},
                    "communicate": ["milk"],
                    # tool_call_correctness was computed but not gated, so a run
                    # that produced the todo by some other route scored green on
                    # a case whose whole point is the tool.
                    "score": {"gates": ["end_state", "communicate", "tool_call_correctness"]},
                },
            ),
            Case(
                id="smoke-3",
                ticket="Provider failure — must rotate off nous and still pass.",
                prompt="Write a one-line status report.",
                expected={
                    "category": "ROTATION",
                    "communicate": ["report"],
                    "score": {"gates": ["communicate"]},
                },
            ),
        ]

    def transport(
        self,
        case: Case,
        cfg: EvalConfig,
        tracker: EvalCostTracker,
        provider: ProviderConfig,
    ) -> Awaitable[CaseRun]:
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        return score_gates(case, run)

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        del cfg
        return [
            BubbleBoundary(),
            CommunicateGate(),
            EndStateEquality(),
            ToolCallCorrectness(),
            ProviderQuality(),
        ]
