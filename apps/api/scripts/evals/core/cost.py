"""Token and dollar accounting: per-provider meters, budgets, estimates."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import threading

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .providers import ProviderConfig

#: Which case the LLM call being metered belongs to.
#:
#: A context variable rather than an attribute because one tracker serves a whole
#: run, including runs that execute several cases at once. An asyncio task copies
#: the context when it is created, so each concurrent case sees only its own value
#: and callbacks fired deep inside the agent graph still land in the right bucket.
_CURRENT_CASE: ContextVar[str | None] = ContextVar("eval_current_case", default=None)


class EvalCostTracker(BaseCallbackHandler):
    """Accumulates token spend across agent runs and trips per-provider budgets.

    Attached to graph configs/callbacks of in-process runs (the same shape as
    the memory benchmark's CostMeter, generalized to per-provider pricing).

    Spend is metered per provider (for budgets) and per case (for the journal).
    Both come from the same credit, so they cannot disagree.
    """

    def __init__(self, providers: dict[str, ProviderConfig], max_usd: float) -> None:
        self.providers = providers
        self.max_usd = max_usd
        self.input_tokens: dict[str, int] = {}
        self.output_tokens: dict[str, int] = {}
        self.case_input: dict[str, int] = {}
        self.case_output: dict[str, int] = {}
        self.exceeded_budget: set[str] = set()
        self.total_exceeded = False
        self._provider: str | None = None
        # Metering runs on the event loop in a sequential run, but concurrent
        # runs fan cases out across tasks and some transports fire LLM
        # callbacks from worker threads — the read-modify-write on the meters
        # below must not lose updates between threads. Reentrant because
        # total_cost_usd sums per-provider cost_usd under the same lock.
        self._lock = threading.RLock()

    def set_provider(self, provider: str) -> None:
        self._provider = provider

    @contextmanager
    def case_scope(self, case_id: str) -> Iterator[None]:
        """Meter everything spent inside this block against ``case_id``."""
        token = _CURRENT_CASE.set(case_id)
        try:
            yield
        finally:
            _CURRENT_CASE.reset(token)

    def case_totals(self, case_id: str) -> tuple[int, int]:
        with self._lock:
            return self.case_input.get(case_id, 0), self.case_output.get(case_id, 0)

    def _credit(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        """The one place spend is recorded, so every meter sees the same event."""
        with self._lock:
            self.input_tokens[provider] = self.input_tokens.get(provider, 0) + input_tokens
            self.output_tokens[provider] = self.output_tokens.get(provider, 0) + output_tokens
            case_id = _CURRENT_CASE.get()
            if case_id is not None:
                self.case_input[case_id] = self.case_input.get(case_id, 0) + input_tokens
                self.case_output[case_id] = self.case_output.get(case_id, 0) + output_tokens

    @property
    def total_input(self) -> int:
        with self._lock:
            return sum(self.input_tokens.values())

    @property
    def total_output(self) -> int:
        with self._lock:
            return sum(self.output_tokens.values())

    def cost_usd(self, provider: str) -> float:
        with self._lock:
            p = self.providers.get(provider)
            if p is None:
                return 0.0
            return (
                self.input_tokens.get(provider, 0) / 1e6 * p.price_in_per_1m
                + self.output_tokens.get(provider, 0) / 1e6 * p.price_out_per_1m
            )

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return sum(self.cost_usd(p) for p in self.providers)

    def on_llm_end(self, response: LLMResult, **_kwargs: object) -> None:
        provider = self._provider or "opencode"
        usage = (response.llm_output or {}).get("usage_metadata") or (
            response.llm_output or {}
        ).get("token_usage")
        for generations in response.generations:
            for gen in generations:
                meta = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if meta:
                    self._credit(
                        provider,
                        int(meta.get("input_tokens", 0)),
                        int(meta.get("output_tokens", 0)),
                    )
                    usage = None
        if usage:
            self._credit(
                provider,
                int(usage.get("input_tokens", usage.get("prompt_tokens", 0))),
                int(usage.get("output_tokens", usage.get("completion_tokens", 0))),
            )
        self._check_budgets()

    def _check_budgets(self) -> None:
        for provider, p in self.providers.items():
            if p.budget_usd > 0 and self.cost_usd(provider) >= p.budget_usd:
                self.exceeded_budget.add(provider)
        if self.max_usd > 0 and self.total_cost_usd >= self.max_usd:
            self.total_exceeded = True

    def add_manual(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        """Record spend a transport measured itself — an HTTP suite reading the
        API's own usage frames, which no in-process callback can see."""
        self._credit(provider, input_tokens, output_tokens)
        self._check_budgets()


def estimate_tokens(text: str) -> int:
    """Rough tokens from characters (used where the transport reports no usage)."""
    return max(1, len(text) // 4)
