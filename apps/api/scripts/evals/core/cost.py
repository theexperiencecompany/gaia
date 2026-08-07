"""Token and dollar accounting: per-provider meters, budgets, estimates."""

from __future__ import annotations

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from .providers import ProviderConfig


class EvalCostTracker(BaseCallbackHandler):
    """Accumulates token spend across agent runs and trips per-provider budgets.

    Attached to graph configs/callbacks of in-process runs (the same shape as
    the memory benchmark's CostMeter, generalized to per-provider pricing).
    """

    def __init__(self, providers: dict[str, ProviderConfig], max_usd: float) -> None:
        self.providers = providers
        self.max_usd = max_usd
        self.input_tokens: dict[str, int] = {}
        self.output_tokens: dict[str, int] = {}
        self.exceeded_budget: set[str] = set()
        self.total_exceeded = False
        self._provider: str | None = None

    def set_provider(self, provider: str) -> None:
        self._provider = provider

    @property
    def total_input(self) -> int:
        return sum(self.input_tokens.values())

    @property
    def total_output(self) -> int:
        return sum(self.output_tokens.values())

    def cost_usd(self, provider: str) -> float:
        p = self.providers.get(provider)
        if p is None:
            return 0.0
        return (
            self.input_tokens.get(provider, 0) / 1e6 * p.price_in_per_1m
            + self.output_tokens.get(provider, 0) / 1e6 * p.price_out_per_1m
        )

    @property
    def total_cost_usd(self) -> float:
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
                    self.input_tokens[provider] = self.input_tokens.get(provider, 0) + int(
                        meta.get("input_tokens", 0)
                    )
                    self.output_tokens[provider] = self.output_tokens.get(provider, 0) + int(
                        meta.get("output_tokens", 0)
                    )
                    usage = None
        if usage:
            self.input_tokens[provider] = self.input_tokens.get(provider, 0) + int(
                usage.get("input_tokens", usage.get("prompt_tokens", 0))
            )
            self.output_tokens[provider] = self.output_tokens.get(provider, 0) + int(
                usage.get("output_tokens", usage.get("completion_tokens", 0))
            )
        self._check_budgets()

    def _check_budgets(self) -> None:
        for provider, p in self.providers.items():
            if p.budget_usd > 0 and self.cost_usd(provider) >= p.budget_usd:
                self.exceeded_budget.add(provider)
        if self.max_usd > 0 and self.total_cost_usd >= self.max_usd:
            self.total_exceeded = True

    def add_manual(self, provider: str, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens[provider] = self.input_tokens.get(provider, 0) + input_tokens
        self.output_tokens[provider] = self.output_tokens.get(provider, 0) + output_tokens
        self._check_budgets()


def estimate_tokens(text: str) -> int:
    """Rough tokens from characters (used where the transport reports no usage)."""
    return max(1, len(text) // 4)
