"""The SEO audit, run for real against a local site that has one of each defect."""

from __future__ import annotations

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading

import pytest

AUDIT = Path(__file__).resolve().parents[1] / "lib" / "seo_audit.py"


def _page(
    base: str, path: str, *, canonical: str | None = None, body: str = "", robots: str = ""
) -> str:
    canonical_tag = (
        f'<link rel="canonical" href="{canonical if canonical is not None else base + path}">'
    )
    robots_tag = f'<meta name="robots" content="{robots}">' if robots else ""
    return (
        f"<html><head><title>Page {path}</title>"
        '<meta name="description" content="A description long enough to sit inside the snippet window of a result.">'
        f"{canonical_tag}{robots_tag}</head><body><h1>{path}</h1>{body}</body></html>"
    )


def _site(base: str) -> dict[str, tuple[int, dict[str, str], str]]:
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
        "/elsewhere": (200, {}, _page(base, "/elsewhere", canonical=f"{base}/good")),
        "/hidden": (200, {}, _page(base, "/hidden", robots="noindex")),
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
    routes: dict[str, tuple[int, dict[str, str], str]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, headers, body = routes.get(self.path, (404, {}, ""))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    routes.update(_site(base))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield base
    server.shutdown()


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
    ):
        assert line in result.stdout, result.stdout


def test_a_clean_page_set_passes(site: str) -> None:
    result = _audit(site, "--vanity=/moved")

    assert "ERROR internal link to a redirect" not in result.stdout
    assert "vanity path does not redirect" not in result.stdout
