"""DuckDuckGo Lite scrape — keyless, always-available last resort."""

from bs4 import BeautifulSoup
import httpx

from app.utils.search.models import SearchResponse, SearchResultItem
from app.utils.search.providers.base import SearchProvider
from shared.py.wide_events import log

_ENDPOINT = "https://lite.duckduckgo.com/lite/"
_TIMEOUT = 10.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"
    monthly_free_limit = None

    def is_configured(self) -> bool:
        return True

    async def search(self, query: str, count: int) -> SearchResponse:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS
        ) as client:
            response = await client.post(_ENDPOINT, data={"q": query})
            response.raise_for_status()

        # DDG Lite serves an anti-bot page (often HTTP 202) that still parses as
        # HTML; treat it as "no results" rather than scraping a challenge page.
        if response.status_code == 202 or "bots use duckduckgo" in response.text[:2000].lower():
            log.warning(f"DuckDuckGo served a bot-challenge page for query: {query[:60]}")
            return SearchResponse(provider=self.name)

        soup = BeautifulSoup(response.text, "lxml")
        results: list[SearchResultItem] = []
        for row in soup.select("tr.result-sponsored, tr:has(a.result-link)")[:count]:
            link = row.select_one("a.result-link") or row.select_one("a[href]")
            if not link:
                continue
            href = str(link.get("href", ""))
            if not href.startswith("http"):
                continue
            snippet_cell = row.find_next_sibling("tr")
            results.append(
                SearchResultItem(
                    url=href,
                    title=link.get_text(strip=True),
                    content=snippet_cell.get_text(strip=True) if snippet_cell else "",
                )
            )
        return SearchResponse(results=results, provider=self.name)
