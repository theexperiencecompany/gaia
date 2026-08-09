"""Comms suite — the user-facing agent's own judgement, not the executor's work.

The comms agent holds NO work tools (``build_comms_*`` in
``app/agents/core/graph_builder/build_graph.py``); its only lever on the world is
``call_executor``. That makes its job a routing and honesty problem, and every
case here is one of the four ways it goes wrong:

* **under-delegation** — answering a question it cannot possibly know the answer
  to, because the data lives behind a tool it does not have. Gated by
  ``delegation: required``.
* **over-delegation** — handing "hey" or "thanks" to the executor, which spends a
  detached run, a model call and seconds of latency on small talk. Gated by
  ``delegation: forbidden``.
* **guessing** — filling an underspecified request with an invented default
  instead of asking one short question. Gated by ``communicate`` on the thing it
  has to ask about, plus ``must_not_communicate`` on the invented answer.
* **fabricating** — claiming an action happened, or inventing a capability or a
  fact. Gated by ``must_not_communicate`` plus rubric criteria.

Transport is the live ``chat-stream`` SSE wire via
:class:`~scripts.evals.suites.livechat.SuiteChatTransport` — the same frames the
web client renders — under this suite's own dev user, so its memories never mix
with the quality or safety suites'.

What these cases do NOT exercise: the executor's answer. On a delegated turn the
SSE text is the comms ack and the final answer arrives out of band (WebSocket +
Mongo), so ``communicate`` strings are always matched against the ack, never
against work output. That is a deliberate boundary — the executor's answers are
the capability suite's job.
"""

from __future__ import annotations

from collections.abc import Awaitable
import os
from pathlib import Path

from scripts.evals.core.cases import load_case_files
from scripts.evals.core.cost import EvalCostTracker
from scripts.evals.core.gates import score_gates
from scripts.evals.core.providers import EvalConfig, ProviderConfig, judge_model
from scripts.evals.core.runner import Suite, register_suite
from scripts.evals.core.scorers import (
    CommunicateGate,
    DelegationGate,
    MustNotCommunicate,
    RubricJudge,
)
from scripts.evals.core.types import Case, CaseRun
from scripts.evals.suites.livechat import SuiteChatTransport

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "comms"


@register_suite("comms")
class CommsSuite(Suite):
    name = "comms"
    project = "gaia-comms"
    label = "Comms"

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._cases: list[Case] | None = None
        self._transport = SuiteChatTransport("comms")

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        if self._cases is None:
            self._cases = load_case_files(DATA_DIR, self.name)
        return self._cases

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
        return [
            DelegationGate(),
            CommunicateGate(),
            MustNotCommunicate(),
            RubricJudge(
                base_url=os.environ.get("DEV_LLM_BASE_URL", ""),
                api_key=os.environ.get("DEV_LLM_API_KEY", ""),
                model=judge_model(cfg),
            ),
        ]
