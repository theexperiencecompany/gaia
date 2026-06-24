"""The search waterfall: try providers in order until one returns results."""

from app.utils.search.budget import FreeTierBudget
from app.utils.search.models import SearchResponse
from app.utils.search.providers import SearchProvider, default_providers
from shared.py.wide_events import log


class SearchEngine:
    """Runs an ordered list of providers, returning the first non-empty response.

    A provider is *skipped* when it is unconfigured or out of free-tier budget,
    and *failed over* when it raises or returns no results. Budget is recorded on
    every successful upstream call so free allowances are never exceeded.
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
        for provider in self._providers:
            if not provider.is_configured():
                continue
            if not await self._budget.has_headroom(provider.name):
                log.info(f"Search provider {provider.name} out of monthly free budget; skipping")
                continue
            try:
                response = await provider.search(query, count)
            except Exception as e:
                log.warning(f"Search provider {provider.name} failed: {e}")
                continue
            await self._budget.record_call(provider.name)
            if not response.is_empty:
                log.info(
                    f"Search provider {provider.name} returned "
                    f"{len(response.results)} results for: {query[:60]}"
                )
                return response
            log.info(f"Search provider {provider.name} returned no results for: {query[:60]}")
        log.warning(f"All search providers exhausted for: {query[:60]}")
        return SearchResponse()
