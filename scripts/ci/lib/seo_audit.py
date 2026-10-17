"""Crawl a deployed site's sitemap and report what a search engine's site audit would flag.

Every sitemap URL must answer 200 without a redirect, canonicalize to itself, be
indexable, carry one H1, a title and a description, and parse its JSON-LD. Every
internal link on those pages must reach a 200 directly, and every hreflang
alternate must be a page in the sitemap. Titles and descriptions shared by
different pages are reported per locale. Exit 1 on any error-class finding.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "gaia-seo-audit/1.0 (+https://heygaia.io)"
TIMEOUT_S = 30
RETRIES = 2
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
LOCALE_PREFIX = re.compile(r"^/(de|es|fr|ja|ko|pt-BR)(?=/|$)")
TITLE_MAX = 65
DESCRIPTION_RANGE = (70, 165)
EXAMPLES = 8


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface every 3xx as an HTTPError carrying its status, so a redirect is a finding."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: str


def fetch(url: str, method: str = "GET", host: str | None = None) -> Response:
    """One request without following redirects; retries only transport errors and 5xx."""
    headers = {"User-Agent": USER_AGENT} | ({"Host": host} if host else {})
    request = urllib.request.Request(url, method=method, headers=headers)  # noqa: S310 - http(s) URLs from the audited site's own sitemap and pages
    for attempt in range(RETRIES + 1):
        try:
            with _OPENER.open(request, timeout=TIMEOUT_S) as resp:
                body = resp.read().decode("utf-8", "replace") if method == "GET" else ""
                return Response(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == RETRIES:
                return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, "")
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == RETRIES:
                return Response(0, {}, f"transport error: {exc}")
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description: str | None = None
        self.canonical: str | None = None
        self.robots = ""
        self.hreflang: dict[str, str] = {}
        self.links: set[str] = set()
        self.h1_count = 0
        self.jsonld: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._svg_depth = 0
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "svg":
            self._svg_depth += 1
        if tag == "title" and not self.title and self._svg_depth == 0:
            self._in_title = True
        elif tag == "meta" and a.get("name") == "description":
            self.description = a.get("content", "")
        elif tag == "meta" and a.get("name") == "robots":
            self.robots = a.get("content", "").lower()
        elif tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        elif tag == "link" and a.get("rel") == "alternate" and a.get("hreflang"):
            self.hreflang[a["hreflang"]] = a.get("href", "")
        elif tag == "a" and a.get("href"):
            self.links.add(a["href"])
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_jsonld = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buffer))
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._in_jsonld:
            self._buffer.append(data)


@dataclass(frozen=True)
class Site:
    """The origin pages name (site_url) and the origin the audit fetches them from (base)."""

    site_url: str
    base: str

    def get(self, url: str) -> Response:
        """Fetch a site URL from base, presenting the site's host so host-aware middleware answers as there."""
        if self.site_url == self.base or not url.startswith(self.site_url):
            return fetch(url)
        host = urllib.parse.urlparse(self.site_url).netloc
        return fetch(self.base + url[len(self.site_url) :], host=host)


@dataclass
class Findings:
    errors: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    warnings: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def error(self, kind: str, detail: str) -> None:
        self.errors[kind].append(detail)

    def warn(self, kind: str, detail: str) -> None:
        self.warnings[kind].append(detail)


def sitemap_urls(site: Site, per_sitemap: int | None) -> list[str]:
    """Every page URL reachable from the sitemap index (the first per_sitemap of each), deduplicated."""
    seen: dict[str, None] = {}
    queue = [f"{site.site_url}/sitemap.xml"]
    while queue:
        resp = site.get(queue.pop(0))
        if resp.status != 200:
            raise SystemExit(f"seo-audit: sitemap answered {resp.status}")
        locs = LOC.findall(resp.body)
        if "<sitemapindex" in resp.body:
            queue.extend(locs)
        else:
            for url in locs[:per_sitemap]:
                seen.setdefault(url, None)
    return list(seen)


def audit_page(url: str, site: Site, live: set[str], findings: Findings) -> _PageParser | None:
    resp = site.get(url)
    if resp.status != 200:
        where = resp.headers.get("location", "")
        findings.error("sitemap URL not 200", f"{url} -> {resp.status} {where}".strip())
        return None
    page = _PageParser()
    page.feed(resp.body)
    if "noindex" in page.robots or "noindex" in resp.headers.get("x-robots-tag", "").lower():
        findings.error("sitemap URL is noindex", url)
    if page.canonical is None:
        findings.error("missing canonical", url)
    elif page.canonical.rstrip("/") != url.rstrip("/"):
        findings.error("canonical points elsewhere", f"{url} -> {page.canonical}")
    if not page.title.strip():
        findings.error("missing title", url)
    elif len(page.title) > TITLE_MAX:
        findings.warn(f"title over {TITLE_MAX} chars", f"{len(page.title)} {url}")
    if not page.description:
        findings.error("missing meta description", url)
    elif not DESCRIPTION_RANGE[0] <= len(page.description) <= DESCRIPTION_RANGE[1]:
        findings.warn("meta description length", f"{len(page.description)} {url}")
    if page.h1_count != 1:
        findings.warn("H1 count is not 1", f"{page.h1_count} {url}")
    for block in page.jsonld:
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            findings.error("invalid JSON-LD", f"{url}: {exc}")
    for lang, href in page.hreflang.items():
        if live and href not in live:
            findings.error("hreflang target not in sitemap", f"{url} [{lang}] -> {href}")
        page.links.add(href)
    return page


def internal_targets(pages: dict[str, _PageParser], base: str) -> dict[str, set[str]]:
    """Map each internal link target (absolute, no fragment) to the pages that link it."""
    host = urllib.parse.urlparse(base).netloc
    targets: dict[str, set[str]] = defaultdict(set)
    for url, page in pages.items():
        for href in page.links:
            absolute = urllib.parse.urljoin(url, href).split("#", 1)[0]
            parsed = urllib.parse.urlparse(absolute)
            if parsed.netloc == host and parsed.scheme in {"http", "https"}:
                targets[absolute].add(url)
    return targets


def locale_of(url: str) -> str:
    match = LOCALE_PREFIX.match(urllib.parse.urlparse(url).path)
    return match.group(1) if match else "en"


def report_shared(pages: dict[str, _PageParser], findings: Findings) -> None:
    for attr, label in (("title", "title"), ("description", "meta description")):
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for url, page in pages.items():
            value = (getattr(page, attr) or "").strip()
            if value:
                groups[(locale_of(url), value)].append(url)
        for (locale, value), urls in groups.items():
            if len(urls) > 1:
                findings.warn(
                    f"duplicate {label} ({locale})", f"{len(urls)}x {value[:70]!r}: {urls[0]}"
                )


def run(
    site: Site, workers: int, out: Path | None, vanity: set[str], per_sitemap: int | None
) -> int:
    urls = sitemap_urls(site, per_sitemap)
    # A sample is not the live page set: membership checks give way to fetching every target.
    live = set() if per_sitemap else set(urls)
    findings = Findings()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        parsed = list(pool.map(lambda u: audit_page(u, site, live, findings), urls))
    pages = {u: p for u, p in zip(urls, parsed, strict=True) if p is not None}
    targets = internal_targets(pages, site.site_url)
    vanity_urls = {f"{site.site_url}{path}" for path in vanity}
    unchecked = sorted({t for t in targets if t not in live} | vanity_urls)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = dict(
            zip(unchecked, pool.map(lambda t: site.get(t).status, unchecked), strict=True)
        )
    for target, status in statuses.items():
        sources = targets.get(target, set())
        if target in vanity_urls:
            if not 300 <= status < 400:
                findings.error("vanity path does not redirect", f"{target} -> {status}")
        elif 300 <= status < 400:
            findings.error(
                "internal link to a redirect",
                f"{target} ({len(sources)} pages, e.g. {min(sources)})",
            )
        elif status != 200:
            findings.error(
                f"internal link answers {status}",
                f"{target} ({len(sources)} pages, e.g. {min(sources)})",
            )
    report_shared(pages, findings)

    print(
        f"seo-audit: {len(urls)} sitemap URLs, {len(targets)} internal link targets on {site.base}"
    )
    for title, bucket in (("ERROR", findings.errors), ("WARN", findings.warnings)):
        for kind, items in sorted(bucket.items(), key=lambda kv: -len(kv[1])):
            print(f"{title} {kind}: {len(items)}")
            for item in sorted(items)[:EXAMPLES]:
                print(f"    {item}")
    if out is not None:
        out.write_text(
            json.dumps({"errors": findings.errors, "warnings": findings.warnings}, indent=1)
        )
    errors = sum(len(v) for v in findings.errors.values())
    warnings = sum(len(v) for v in findings.warnings.values())
    print(f"seo-audit: {'FAIL' if errors else 'OK'} ({errors} errors, {warnings} warnings)")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://heygaia.io", help="origin to fetch from")
    parser.add_argument(
        "--site-url", default=None, help="origin pages and sitemaps name (default: --base)"
    )
    parser.add_argument(
        "--per-sitemap", type=int, default=None, help="audit only the first N URLs of each sitemap"
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path, default=None, help="write every finding as JSON")
    parser.add_argument(
        "--vanity", action="append", default=[], help="a short-link path that must redirect"
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")
    site = Site(site_url=(args.site_url or base).rstrip("/"), base=base)
    return run(site, args.workers, args.out, set(args.vanity), args.per_sitemap)


if __name__ == "__main__":
    sys.exit(main())
