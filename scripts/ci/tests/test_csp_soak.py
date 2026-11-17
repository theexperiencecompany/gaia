"""analytics.py csp-soak: the weekly Slack report that says when the report-only CSP is safe to enforce.

The site, Slack and GitHub are a real local HTTP server, so the header read, the
post through lib/webhook.sh's curl and the workflow disable all run for real;
only PostHog's transport is faked, and the HogQL rows it returns are in the shape
the live project answered QUERY with.
"""

from __future__ import annotations

from collections.abc import Sequence
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from http_stub import Routes, serve
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "analytics.py"
REPORT_ONLY = {
    "Content-Security-Policy-Report-Only": "default-src 'self'; script-src 'self' 'nonce-abc'; report-to posthog"
}
ENFORCED = {"Content-Security-Policy": "default-src 'self'; script-src 'self' 'nonce-abc'"}
DISABLE = "/repos/acme/gaia/actions/workflows/csp-soak.yml/disable"
WEEK = 7 * 86_400
RUNBOOK_LINE = "What this means and what to do: https://internal.lab.heygaia.io/production/csp-soak"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("analytics_csp_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analytics = _load()


def row(
    directive: str, blocked: str, page: str, last_24h: int, first: str, quiet: int
) -> list[Any]:
    return [directive, blocked, page, last_24h, first, "2026-11-15", quiet]


class Site:
    """The stubbed world one run sees, and what the run did to it."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], rows: Sequence[list[Any]]
    ) -> None:
        self.monkeypatch = monkeypatch
        self.headers = headers
        self.rows = rows
        self.slack_status = 200
        self.posts: list[tuple[str, bytes]] = []
        self.queries: list[dict[str, Any]] = []

    def _request(
        self, method: str, path: str, body: Any = None, *, idempotent: bool | None = None
    ) -> dict[str, Any]:
        self.queries.append(body["query"])
        return {"results": [list(r) for r in self.rows]}

    def _client(self, scopes: Sequence[str]) -> Any:
        client = analytics.PostHog("https://us.posthog.com", 201142, "phx_test")
        self.monkeypatch.setattr(client, "_request", self._request)
        return client

    def run(self) -> int:
        routes: Routes = {
            "/": (200, self.headers, "<html></html>"),
            "/slack": (self.slack_status, {}, "ok"),
            DISABLE: (204, {}, ""),
        }
        with serve(routes, self.posts) as base:
            self.monkeypatch.setenv("CSP_SITE_URL", f"{base}/")
            self.monkeypatch.setenv("SLACK_WEBHOOK", f"{base}/slack")
            self.monkeypatch.setenv("GITHUB_API_URL", base)
            self.monkeypatch.setenv("GITHUB_REPOSITORY", "acme/gaia")
            self.monkeypatch.setenv("GH_TOKEN", "ghs_test")
            self.monkeypatch.setattr(analytics, "client_from_env", self._client)
            return int(analytics.main(["csp-soak"]))

    def slack(self) -> list[str]:
        return [str(json.loads(body)["text"]) for path, body in self.posts if path == "/slack"]


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Site:
    return Site(monkeypatch, REPORT_ONLY, [])


def test_a_soak_with_violations_lists_its_top_sources_and_keeps_soaking(site: Site) -> None:
    site.rows = [
        row("script-src-elem", "https://static.cloudflareinsights.com", "/", 35, "2026-10-30", 800),
        row("script-src", "eval", "/c", 10, "2026-10-31", 6_000),
        row(
            "script-src-elem",
            "https://static.cloudflareinsights.com",
            "/pricing",
            11,
            "2026-11-02",
            1_100,
        ),
        row("font-src", "https://fonts.gstatic.com", "/cli", 0, "2026-11-01", 9 * WEEK),
    ]

    assert site.run() == 0

    [text] = site.slack()
    lines = text.splitlines()
    assert lines[0] == "*CSP soak, day 17: 56 violations in 7 days*"
    assert lines[1:4] == [
        "• `script-src-elem` https://static.cloudflareinsights.com on /: 35",
        "• `script-src` eval on /c: 10",
        "• `script-src-elem` https://static.cloudflareinsights.com on /pricing: 11",
    ]
    assert lines[4] == "Keep soaking: 2 source(s) to allow or fix"
    assert "Day 1 is 2026-10-30" in lines[5]
    assert lines[-1] == RUNBOOK_LINE
    [query] = site.queries
    assert query["values"] == {"host": "127.0.0.1"}
    assert "'$csp_violation'" in query["query"]


def test_four_quiet_weeks_say_ready_to_enforce(site: Site) -> None:
    site.rows = [row("script-src", "eval", "/c", 0, "2026-10-30", 4 * WEEK + 60)]

    assert site.run() == 0

    [text] = site.slack()
    assert text.splitlines()[0] == "*CSP soak, day 17: 0 violations in 7 days*"
    assert "Clean for 4 weeks, ready to enforce (#1765)" in text.splitlines()


def test_a_quiet_week_short_of_four_keeps_soaking(site: Site) -> None:
    site.rows = [row("script-src", "eval", "/c", 0, "2026-10-30", 3 * WEEK + 3_000)]

    assert site.run() == 0

    assert "Keep soaking: clean for 3 week(s), 4 needed" in site.slack()[0].splitlines()


def test_no_report_ever_received_says_the_sink_is_unproven(site: Site) -> None:
    assert site.run() == 0

    [text] = site.slack()
    assert text.splitlines()[0] == "*CSP soak, day ?: 0 violations in 7 days*"
    assert "the report sink is unproven" in text
    assert text.splitlines()[-1] == RUNBOOK_LINE


def test_an_enforced_policy_posts_soak_over_once_and_disables_the_workflow(site: Site) -> None:
    site.headers = ENFORCED

    assert site.run() == 0

    assert [text.split(":")[0] for text in site.slack()] == ["*CSP enforced, soak over*"]
    assert site.slack()[0].splitlines()[-1] == RUNBOOK_LINE
    assert [path for path, _ in site.posts] == ["/slack", DISABLE]
    assert site.queries == []
    assert site.slack()[0].splitlines()[-1] == RUNBOOK_LINE


def test_an_enforced_header_without_script_src_is_still_a_soak(site: Site) -> None:
    site.headers = {**REPORT_ONLY, "Content-Security-Policy": "frame-ancestors 'none'"}

    assert site.run() == 0

    assert site.slack()[0].startswith("*CSP soak, day ?")
    assert DISABLE not in [path for path, _ in site.posts]


def test_a_comma_joined_policy_with_script_src_is_enforced(site: Site) -> None:
    site.headers = {
        **REPORT_ONLY,
        "Content-Security-Policy": "frame-ancestors 'none', script-src 'self'",
    }

    assert site.run() == 0

    assert DISABLE in [path for path, _ in site.posts]


def test_report_derived_values_are_slack_escaped(site: Site) -> None:
    site.rows = [row("script-src", "<!channel>&x", "/", 1, "2026-11-01", 100)]

    assert site.run() == 0

    assert "• `script-src` &lt;!channel&gt;&amp;x on /: 1" in site.slack()[0]


def test_a_missing_header_posts_a_warning_and_fails(site: Site) -> None:
    site.headers = {}

    assert site.run() == 1

    assert [text.split(":")[0] for text in site.slack()] == ["*CSP soak broken*"]
    assert site.queries == []
    assert site.slack()[0].splitlines()[-1] == RUNBOOK_LINE


def test_a_failed_slack_delivery_fails_the_run(site: Site) -> None:
    site.slack_status = 500

    with pytest.raises(subprocess.CalledProcessError):
        site.run()


def test_a_result_at_the_row_cap_is_refused(site: Site, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics.csp_soak, "ROW_CAP", 2)
    site.rows = [
        row("script-src", "eval", "/a", 1, "2026-11-01", 5),
        row("script-src", "eval", "/b", 1, "2026-11-01", 5),
    ]

    with pytest.raises(ValueError, match="cap"):
        site.run()
    assert site.slack() == []
