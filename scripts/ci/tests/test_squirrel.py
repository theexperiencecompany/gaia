"""lib/squirrel.py: the ratchet fails on a new rule or a higher count, and only on those."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "lib" / "squirrel.py"
SNIPPET = Path(__file__).resolve().parents[3] / "apps/web/src/config/seoSnippet.json"
SITE = "https://heygaia.io"


def _check(*paths: str, status: str = "warn") -> dict[str, object]:
    return {
        "status": status,
        "affectedPages": [SITE + p for p in paths],
        "affectedPagesCount": len(paths),
        "affectedPagesHasMore": False,
    }


def _issue(rule: str, *checks: dict[str, object]) -> dict[str, object]:
    return {"ruleId": rule, "checks": list(checks)}


def _ratchet(
    tmp_path: Path,
    issues: list[dict[str, object]],
    baseline: str,
    *extra: str,
    scores: dict[str, int] | None = None,
) -> subprocess.CompletedProcess[str]:
    report = tmp_path / "report.json"
    categories = [{"name": name, "score": score} for name, score in (scores or {}).items()]
    report.write_text(json.dumps({"issues": issues, "score": {"categories": categories}}))
    base = tmp_path / "baseline.txt"
    base.write_text(baseline)
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "ratchet",
            "--report",
            str(report),
            "--baseline",
            str(base),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_count_at_the_baseline_passes(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [_issue("core/h1", _check("/a", "/b"))], "# header\ncore/h1=2\n")
    assert proc.returncode == 0, proc.stdout
    assert "tighten" not in proc.stdout


def test_a_count_above_the_baseline_fails(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [_issue("core/h1", _check("/a", "/b", "/c"))], "core/h1=2\n")
    assert proc.returncode == 1
    assert "core/h1: 3 finding(s), baseline 2" in proc.stdout


def test_a_rule_the_baseline_does_not_list_fails(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [_issue("links/broken-links", _check("/a"))], "core/h1=2\n")
    assert proc.returncode == 1
    assert "links/broken-links: 1 finding(s), baseline 0" in proc.stdout


def test_a_fixed_rule_is_removable_not_a_failure(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [_issue("core/h1", _check("/a"))], "core/h1=2\nperf/ttfb=4\n")
    assert proc.returncode == 0, proc.stdout
    assert "improved past the baseline, tighten it: core/h1: baseline 2, now 1" in proc.stdout
    assert "perf/ttfb: baseline 4, now 0" in proc.stdout


def test_passing_checks_and_hidden_pages_count_as_squirrel_reports_them(tmp_path: Path) -> None:
    hidden = {**_check("/a"), "affectedPagesCount": 40, "affectedPagesHasMore": True}
    issues = [_issue("perf/js-file-size", hidden, _check("/b", status="pass"))]
    assert _ratchet(tmp_path, issues, "perf/js-file-size=40\n").returncode == 0
    assert _ratchet(tmp_path, issues, "perf/js-file-size=39\n").returncode == 1


def test_a_site_wide_check_counts_its_items(tmp_path: Path) -> None:
    check: dict[str, object] = {"status": "warn", "items": [{"id": "x"}, {"id": "y"}]}
    assert _ratchet(tmp_path, [_issue("security/hsts", check)], "security/hsts=1\n").returncode == 1


@pytest.mark.parametrize(
    ("rule", "path"),
    [
        ("url/lowercase", "/pt-br/compare"),
        ("url/lowercase", "/pt-br"),
    ],
)
def test_the_two_known_false_positives_are_not_counted(
    tmp_path: Path, rule: str, path: str
) -> None:
    proc = _ratchet(tmp_path, [_issue(rule, _check(path))], "")
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize(
    ("rule", "path"),
    [
        ("crawl/sitemap-valid", "/sitemap/0.xml"),
        ("url/lowercase", "/pt-br/Compare"),
        ("url/lowercase", "/About"),
    ],
)
def test_the_same_rules_still_count_a_real_finding(tmp_path: Path, rule: str, path: str) -> None:
    assert _ratchet(tmp_path, [_issue(rule, _check(path))], "").returncode == 1


def test_update_rewrites_the_baseline_from_the_report(tmp_path: Path) -> None:
    issues = [_issue("core/h1", _check("/a")), _issue("a11y/skip-link", _check("/a", "/b"))]
    proc = _ratchet(tmp_path, issues, "core/h1=9\n", "--update")
    assert proc.returncode == 0, proc.stderr
    lines = [
        ln for ln in (tmp_path / "baseline.txt").read_text().splitlines() if not ln.startswith("#")
    ]
    assert [ln for ln in lines if ln] == ["a11y/skip-link=2", "core/h1=1"]
    assert _ratchet(tmp_path, issues, (tmp_path / "baseline.txt").read_text()).returncode == 0


def test_a_malformed_baseline_line_fails_loud(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "core/h1 two\n")
    assert proc.returncode != 0
    assert "expected `<rule id>=<count>`" in proc.stderr


def test_config_takes_the_snippet_windows_from_the_web_app(tmp_path: Path) -> None:
    out = tmp_path / "squirrel.toml"
    subprocess.run([sys.executable, "-I", str(SCRIPT), "config", "--out", str(out)], check=True)
    snippet = json.loads(SNIPPET.read_text())
    text = out.read_text()
    title = f'[rule_options."core/meta-title"]\nmin_length = {snippet["titleLength"]["min"]}\nmax_length = {snippet["titleLength"]["max"]}\n'
    description = f'[rule_options."core/meta-description"]\nmin_length = {snippet["descriptionLength"]["min"]}\nmax_length = {snippet["descriptionLength"]["max"]}\n'
    assert title in text
    assert description in text
    assert text.startswith((SCRIPT.parents[3] / "config/squirrel.toml").read_text())


def test_a_category_score_below_its_baseline_fails(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "score:Core SEO=93\n", scores={"Core SEO": 92})
    assert proc.returncode == 1
    assert "score:Core SEO: 92, baseline 93" in proc.stdout


def test_a_category_the_baseline_does_not_list_must_score_100(tmp_path: Path) -> None:
    assert _ratchet(tmp_path, [], "", scores={"Video": 100}).returncode == 0
    assert _ratchet(tmp_path, [], "", scores={"Video": 99}).returncode == 1


def test_a_raised_score_is_slack_to_tighten(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "score:Images=51\n", scores={"Images": 60})
    assert proc.returncode == 0, proc.stdout
    assert "score:Images: baseline 51, now 60" in proc.stdout


def test_strict_fails_on_slack_so_the_fix_tightens_the_baseline(tmp_path: Path) -> None:
    issues = [_issue("core/h1", _check("/a"))]
    proc = _ratchet(tmp_path, issues, "core/h1=2\n", "--strict")
    assert proc.returncode == 1
    assert "SMOKE_SQUIRREL_UPDATE=1" in proc.stdout
    proc = _ratchet(tmp_path, [], "score:Images=51\n", "--strict", scores={"Images": 60})
    assert proc.returncode == 1


def test_update_records_the_category_scores(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "", "--update", scores={"Images": 51, "Video": 100})
    assert proc.returncode == 0, proc.stderr
    assert "score:Images=51" in (tmp_path / "baseline.txt").read_text()
    assert "score:Video=" not in (tmp_path / "baseline.txt").read_text()
