"""The SEO audit, run for real against a local site that has one of each defect."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys

from http_stub import Routes, serve
import pytest

AUDIT = Path(__file__).resolve().parents[1] / "lib" / "seo_audit.py"
SNIPPET = Path(__file__).resolve().parents[3] / "apps/web/src/config/seoSnippet.json"
NAMED = "https://heygaia.test"


@dataclass(frozen=True)
class Head:
    """The head tags a test page varies; the defaults make a clean page."""

    canonical: str | None = None
    robots: str = ""
    og_image: str = "/og.png"
    description: str = "A description long enough to sit inside the snippet window of a result."


CLEAN_HEAD = Head()


def _page(base: str, path: str, head: Head = CLEAN_HEAD, body: str = "") -> str:
    canonical = head.canonical if head.canonical is not None else base + path
    robots_tag = f'<meta name="robots" content="{head.robots}">' if head.robots else ""
    return (
        "<html><head><svg><title>Icon</title></svg>"
        f"<title>Page {path}</title>"
        f'<meta name="description" content="{head.description}">'
        f'<link rel="canonical" href="{canonical}">{robots_tag}'
        f'<meta property="og:image" content="{base}{head.og_image}">'
        f"</head><body><h1>{path}</h1>{body}</body></html>"
    )


def _site(base: str) -> Routes:
    pages = ["/", "/good", "/elsewhere", "/hidden", "/broken-jsonld"]
    sitemap = "".join(f"<url><loc>{base}{p}</loc></url>" for p in [*pages, "/gone"])
    return {
        "/sitemap.xml": (
            200,
            {},
            f"<sitemapindex><sitemap><loc>{base}/sitemap/0.xml</loc></sitemap></sitemapindex>",
        ),
        "/sitemap/0.xml": (200, {}, f"<urlset>{sitemap}</urlset>"),
        "/": (
            200,
            {},
            _page(
                base,
                "/",
                body='<a href="/good">ok</a><a href="/moved">old</a><a href="/missing">x</a><a href="/discord">d</a>',
            ),
        ),
        "/good": (200, {}, _page(base, "/good")),
        "/og.png": (200, {"Content-Type": "image/png"}, "png"),
        "/og-broken.png": (500, {"Content-Type": "text/plain"}, "Internal Server Error"),
        "/elsewhere": (200, {}, _page(base, "/elsewhere", Head(canonical=f"{base}/good"))),
        "/hidden": (
            200,
            {},
            _page(base, "/hidden", Head(robots="noindex", og_image="/og-broken.png")),
        ),
        "/broken-jsonld": (
            200,
            {},
            _page(base, "/broken-jsonld", body='<script type="application/ld+json">{nope</script>'),
        ),
        "/gone": (404, {}, ""),
        "/moved": (308, {"Location": "/good"}, ""),
        "/discord": (200, {}, "<html>soft redirect</html>"),
    }


@pytest.fixture
def site() -> Iterator[str]:
    routes: Routes = {}
    with serve(routes) as base:
        routes.update(_site(base))
        yield base


def _audit(base: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(AUDIT), "--base", base, "--workers", "2", *extra],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_every_defect_is_an_error_and_fails_the_run(site: str) -> None:
    result = _audit(site, "--vanity=/discord")

    assert result.returncode == 1, result.stdout
    for line in (
        "ERROR sitemap URL not 200: 1",
        "ERROR canonical points elsewhere: 1",
        "ERROR sitemap URL is noindex: 1",
        "ERROR invalid JSON-LD: 1",
        "ERROR internal link to a redirect: 1",
        "ERROR internal link answers 404: 1",
        "ERROR vanity path does not redirect: 1",
        "ERROR og:image is not an image: 1",
    ):
        assert line in result.stdout, result.stdout


def test_a_clean_page_set_passes(site: str) -> None:
    result = _audit(site, "--vanity=/moved")

    assert "ERROR internal link to a redirect" not in result.stdout
    assert "vanity path does not redirect" not in result.stdout
    # Each page's own title, not the icon <title> inside its <svg>.
    assert "duplicate title" not in result.stdout


@pytest.fixture
def renamed_site() -> Iterator[str]:
    named = "https://heygaia.test"
    sitemap = (
        f"<urlset><url><loc>{named}/good</loc></url><url><loc>{named}/also</loc></url></urlset>"
    )
    with serve(
        {
            "/sitemap.xml": (200, {}, sitemap),
            "/good": (200, {}, _page(named, "/good", body='<a href="/also">a</a>')),
            "/also": (200, {}, _page(named, "/also")),
            "/og.png": (200, {"Content-Type": "image/png"}, "png"),
        }
    ) as base:
        yield base


def test_audits_a_local_build_whose_pages_name_production(renamed_site: str) -> None:
    result = _audit(renamed_site, "--site-url=https://heygaia.test", "--per-sitemap=1")

    assert result.returncode == 0, result.stdout
    assert "seo-audit: 1 sitemap URLs" in result.stdout


def _description_range() -> tuple[int, int]:
    limits = json.loads(SNIPPET.read_text())["descriptionLength"]
    return limits["min"], limits["max"]


def _snippet_site(descriptions: dict[str, str]) -> Routes:
    sitemap = "".join(f"<url><loc>{NAMED}{p}</loc></url>" for p in descriptions)
    pages: Routes = {
        p: (200, {}, _page(NAMED, p, Head(description=d))) for p, d in descriptions.items()
    }
    return {
        "/sitemap.xml": (200, {}, f"<urlset>{sitemap}</urlset>"),
        "/og.png": (200, {"Content-Type": "image/png"}, "png"),
        **pages,
    }


def test_a_warning_alone_fails_the_run() -> None:
    low, _ = _description_range()
    with serve(_snippet_site({"/thin": "x" * (low - 1)})) as base:
        result = _audit(base, f"--site-url={NAMED}")

    assert "WARN meta description length: 1" in result.stdout, result.stdout
    assert result.returncode == 1, result.stdout


def test_description_bounds_are_the_web_apps_snippet_config() -> None:
    low, high = _description_range()
    pages = {"/at-min": "a" * low, "/at-max": "b" * high, "/under": "c" * (low - 1)}
    pages["/over"] = "d" * (high + 1)
    with serve(_snippet_site(pages)) as base:
        result = _audit(base, f"--site-url={NAMED}")

    assert "WARN meta description length: 2" in result.stdout, result.stdout
    assert f"{low - 1} {NAMED}/under" in result.stdout
    assert f"{high + 1} {NAMED}/over" in result.stdout
