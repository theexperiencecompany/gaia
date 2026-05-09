"""oEmbed provider registry and fetcher.

Many sites either block raw HTML scraping (Twitter/X) or render content client-side
(SPA shells with no useful <title> or OG tags). For those, we hit the provider's
official oEmbed endpoint instead — it returns title, thumbnail, and author as JSON.

This module is consulted first by `scrape_url_metadata`; it falls back to HTML
scraping when the host isn't in `PROVIDERS` or the oEmbed call fails.
"""

from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class OEmbedProvider:
    """An oEmbed endpoint template. `{url}` is replaced with the URL-encoded target."""

    endpoint: str


# Hostname (without leading "www.") -> provider config.
# Only includes providers verified to return JSON with a usable title field.
PROVIDERS: dict[str, OEmbedProvider] = {
    "youtube.com": OEmbedProvider(
        "https://www.youtube.com/oembed?format=json&url={url}"
    ),
    "youtu.be": OEmbedProvider("https://www.youtube.com/oembed?format=json&url={url}"),
    # publish.twitter.com only resolves twitter.com URLs — x.com gets rewritten below.
    "twitter.com": OEmbedProvider(
        "https://publish.twitter.com/oembed?format=json&url={url}"
    ),
    "x.com": OEmbedProvider("https://publish.twitter.com/oembed?format=json&url={url}"),
    "open.spotify.com": OEmbedProvider("https://open.spotify.com/oembed?url={url}"),
    "soundcloud.com": OEmbedProvider(
        "https://soundcloud.com/oembed?format=json&url={url}"
    ),
    "reddit.com": OEmbedProvider("https://www.reddit.com/oembed?url={url}"),
    "flickr.com": OEmbedProvider(
        "https://www.flickr.com/services/oembed?format=json&url={url}"
    ),
    "pinterest.com": OEmbedProvider("https://www.pinterest.com/oembed.json?url={url}"),
    "ted.com": OEmbedProvider("https://www.ted.com/services/v1/oembed.json?url={url}"),
    "scribd.com": OEmbedProvider("https://www.scribd.com/services/oembed?url={url}"),
}


def _resolve_provider_host(url: str) -> str | None:
    """Return the canonical PROVIDERS key for `url`, matching subdomains like
    `old.reddit.com` to `reddit.com`. Returns None if no provider matches.
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.lower().removeprefix("www.")
    if host in PROVIDERS:
        return host
    return next(
        (known for known in PROVIDERS if host.endswith(f".{known}")),
        None,
    )


def _rewrite_for_provider(url: str, provider_host: str) -> str:
    """Apply provider-specific URL fixups before calling the endpoint."""
    if provider_host == "x.com":
        # publish.twitter.com 404s on x.com URLs; rewrite the host.
        return url.replace("://x.com/", "://twitter.com/", 1).replace(
            "://www.x.com/", "://twitter.com/", 1
        )
    return url


def _title_from_html(html: str | None) -> str | None:
    """Strip tags from an oEmbed `html` payload and return plain text.

    Twitter's oEmbed has no `title` field — the tweet text lives inside the
    embeddable `<blockquote>`, so we parse it out as the title.
    """
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return text or None


def _google_favicon(host: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={host}&sz=64"


async def fetch_oembed_metadata(url: str, client: httpx.AsyncClient) -> dict | None:
    """Fetch metadata via the provider's oEmbed endpoint.

    Returns the same shape as `scrape_url_metadata`'s success path, or None if
    the host isn't a known provider, the request fails, or the response doesn't
    contain a usable title.
    """
    provider_host = _resolve_provider_host(url)
    if provider_host is None:
        return None

    target_url = _rewrite_for_provider(url, provider_host)
    endpoint = PROVIDERS[provider_host].endpoint.format(url=quote(target_url, safe=""))

    try:
        response = await client.get(endpoint)
    except httpx.RequestError:
        return None

    if response.status_code >= 400:
        return None
    if "json" not in response.headers.get("content-type", "").lower():
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    title = data.get("title") or _title_from_html(data.get("html"))
    if not title:
        return None

    return {
        "title": title,
        "description": data.get("description"),
        "favicon": _google_favicon(provider_host),
        "website_name": data.get("provider_name"),
        "website_image": data.get("thumbnail_url"),
        "url": url,
    }
