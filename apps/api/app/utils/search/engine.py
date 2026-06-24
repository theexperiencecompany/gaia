"""The search waterfall: try providers in order until one returns results."""

import hashlib
import time
from typing import Any

from app.utils.search.budget import FreeTierBudget
from app.utils.search.models import SearchResponse
from app.utils.search.providers import SearchProvider, default_providers
from shared.py.wide_events import log


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


class SearchEngine:
    """Runs an ordered list of providers, returning the first non-empty response.

    A provider is *skipped* when it is unconfigured or out of free-tier budget,
    and *failed over* when it raises or returns no results. Budget recording and
    Redis reads are best-effort so external-state faults never break search. Every
    attempt is captured in a single ``search_engine`` wide-event field for
    per-provider observability (outcome, latency, result count, error type).
    """

    def __init__(
        self,
        providers: list[SearchProvider] | None = None,
        budget: FreeTierBudget | None = None,
    ) -> None:
        self._providers = providers or default_providers()
        self._budget = budget or FreeTierBudget(
            {p.name: p.monthly_free_limit for p in self._providers if p.monthly_free_limit}
        )

    async def search(self, query: str, count: int) -> SearchResponse:
        """Run the provider waterfall, returning the first non-empty response."""
        # A query hash (never the raw text) keeps the log high-cardinality but
        # leak-free; the hash still lets us correlate retries of the same query.
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        attempts: list[dict[str, Any]] = []
        result = SearchResponse()

        for provider in self._providers:
            if not provider.is_configured():
                attempts.append({"provider": provider.name, "outcome": "unconfigured"})
                continue
            if not await self._budget.has_headroom(provider.name):
                attempts.append({"provider": provider.name, "outcome": "budget_exhausted"})
                continue

            start = time.monotonic()
            try:
                response = await provider.search(query, count)
            except Exception as e:
                attempts.append(
                    {
                        "provider": provider.name,
                        "outcome": "error",
                        "error_type": type(e).__name__,
                        "latency_ms": _elapsed_ms(start),
                    }
                )
                log.warning(f"search provider {provider.name} failed: {e}")
                continue
            latency_ms = _elapsed_ms(start)

            try:
                await self._budget.record_call(provider.name)
            except Exception as e:
                log.error(f"failed to record search budget for {provider.name}: {e}")

            if response.is_empty:
                attempts.append(
                    {"provider": provider.name, "outcome": "empty", "latency_ms": latency_ms}
                )
                continue

            attempts.append(
                {
                    "provider": provider.name,
                    "outcome": "hit",
                    "result_count": len(response.results),
                    "latency_ms": latency_ms,
                }
            )
            result = response
            break

        log.set(
            search_engine={
                "query_hash": query_hash,
                "result_limit": count,
                "provider_used": result.provider,
                "result_count": len(result.results),
                "providers_attempted": len(attempts),
                "attempts": attempts,
            }
        )
        if result.is_empty:
            log.warning("all search providers exhausted")
        return result
