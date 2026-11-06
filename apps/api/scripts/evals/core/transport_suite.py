"""A suite whose YAML cases each go through one transport and are graded by the suite's own gates."""

from __future__ import annotations

from collections.abc import Awaitable
from pathlib import Path
from typing import ClassVar, Protocol

from .cases import load_case_files
from .cost import EvalCostTracker
from .gates import ExtraGates, score_gates
from .providers import EvalConfig, ProviderConfig
from .runner import Suite
from .types import Case, CaseRun


class CaseTransport(Protocol):
    """Runs one case and reports what happened."""

    async def run(
        self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> CaseRun: ...


class TransportSuite(Suite):
    """Cases under data_dir, run by transport_type, graded by extra alone: no rubric judge, no second model bill."""

    data_dir: ClassVar[Path]
    extra: ClassVar[ExtraGates]
    transport_type: ClassVar[type[CaseTransport]]

    def __init__(self, cfg: EvalConfig) -> None:
        del cfg
        self._transport = self.transport_type()

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        del cfg
        return load_case_files(self.data_dir, self.name, self.extra)

    def transport(
        self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> Awaitable[CaseRun]:
        return self._transport.run(case, cfg, tracker, provider)

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        return score_gates(case, run, self.extra)
