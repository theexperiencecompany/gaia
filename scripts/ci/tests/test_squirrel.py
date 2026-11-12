"""lib/squirrel.py: a finding the baseline does not list fails, on exactly the pages a crawl audited."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from http_stub import Routes, serve
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "lib" / "squirrel.py"
SITE = "https://heygaia.io"
# The slice of squirrel 0.0.133's project.db schema the ratchet reads.
SCHEMA = """
CREATE TABLE crawls (id TEXT PRIMARY KEY);
CREATE TABLE pages (crawl_id TEXT NOT NULL, url TEXT NOT NULL);
CREATE TABLE rule_results (
  crawl_id TEXT NOT NULL, page_url TEXT NOT NULL, rule_id TEXT NOT NULL,
  check_name TEXT NOT NULL, status TEXT NOT NULL, items TEXT, pages TEXT
);
"""

Row = tuple[str, str, str, str, list[dict[str, str]] | None]


def _row(
    path: str,
    rule: str,
    check: str,
    items: list[dict[str, str]] | None = None,
    status: str = "warn",
) -> Row:
    return (SITE + path if path else "", rule, check, status, items)


def _crawl(tmp_path: Path, pages: list[str], rows: list[Row], scores: dict[str, int]) -> Path:
    """Write a finished crawl as squirrel leaves it: HOME's project.db, the report and the page list."""
    db = tmp_path / "home/.squirrel/projects/gaia/project.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO crawls VALUES ('c1')")
    con.executemany("INSERT INTO pages VALUES ('c1', ?)", [(SITE + p,) for p in pages])
    con.executemany(
        "INSERT INTO rule_results VALUES ('c1', ?, ?, ?, ?, ?, NULL)",
        [
            (url, rule, check, status, json.dumps(items) if items else None)
            for url, rule, check, status, items in rows
        ],
    )
    con.commit()
    con.close()
    categories = [{"name": name, "score": score} for name, score in scores.items()]
    (tmp_path / "report.json").write_text(json.dumps({"score": {"categories": categories}}))
    (tmp_path / "pages.txt").write_text("".join(f"{SITE}{p}\n" for p in pages))
    return tmp_path / "home"


def _ratchet(
    tmp_path: Path,
    rows: list[Row],
    baseline: str,
    *extra: str,
    pages: list[str] | None = None,
    scores: dict[str, int] | None = None,
    listed: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    crawled = pages if pages is not None else ["/", "/a", "/b"]
    home = _crawl(tmp_path, crawled, rows, scores or {})
    if listed is not None:
        (tmp_path / "pages.txt").write_text("".join(f"{SITE}{p}\n" for p in listed))
    (tmp_path / "baseline.txt").write_text(baseline)
    return subprocess.run(
        [
            sys.executable, "-I", str(SCRIPT), "ratchet", "--site", SITE, "--home", str(home),
            "--report", str(tmp_path / "report.json"), "--pages", str(tmp_path / "pages.txt"),
            "--baseline", str(tmp_path / "baseline.txt"), *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip


def _lines(tmp_path: Path) -> list[str]:
    text = (tmp_path / "baseline.txt").read_text()
    return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]


H1 = _row("/a", "core/h1", "missing-h1")


def test_a_finding_the_baseline_lists_passes(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [H1], "/a\tcore/h1/missing-h1\n")
    assert proc.returncode == 0, proc.stdout


def test_the_same_check_on_another_page_fails(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [H1, _row("/b", "core/h1", "missing-h1")], "/a\tcore/h1/missing-h1\n")
    assert proc.returncode == 1
    assert "new finding /b core/h1/missing-h1" in proc.stdout


def test_another_item_of_a_listed_check_on_the_same_page_fails(tmp_path: Path) -> None:
    rows = [
        _row(
            "/a", "content/keyword-stuffing", "keyword-stuffing", [{"id": "gaia"}, {"id": "agent"}]
        )
    ]
    proc = _ratchet(tmp_path, rows, "/a\tcontent/keyword-stuffing/keyword-stuffing\tgaia\n")
    assert proc.returncode == 1
    assert "new finding /a content/keyword-stuffing/keyword-stuffing [agent]" in proc.stdout


def test_passing_and_informational_results_are_not_findings(tmp_path: Path) -> None:
    rows = [_row("/a", "core/h1", "missing-h1", status=s) for s in ("pass", "info", "skipped")]
    assert _ratchet(tmp_path, rows, "").returncode == 0


def test_a_build_asset_is_one_site_wide_finding_the_next_build_still_matches(
    tmp_path: Path,
) -> None:
    rows = [_row("/a", "perf/critical-request-chains", "critical-request-chains", [{"id": "CSS: /_next/static/chunks/0s_ds18rk7fe1.css"}])]  # fmt: skip
    baseline = (
        "*\tperf/critical-request-chains/critical-request-chains\tCSS: /_next/static/chunks/*.css\n"
    )
    assert _ratchet(tmp_path, rows, baseline).returncode == 0


def test_a_site_wide_finding_is_keyed_by_its_item_and_a_page_item_by_its_page(
    tmp_path: Path,
) -> None:
    rows = [
        _row("", "security/csp", "csp-missing"),
        _row("", "perf/asset-compression", "asset-compression", [{"id": f"{SITE}/big.js"}]),
        _row("", "links/orphan-pages", "orphan-pages", [{"id": f"{SITE}/b"}]),
    ]
    proc = _ratchet(tmp_path, rows, "", "--update")
    assert proc.returncode == 0, proc.stderr
    assert _lines(tmp_path) == [
        "*\tperf/asset-compression/asset-compression\t/big.js",
        "*\tsecurity/csp/csp-missing",
        "/b\tlinks/orphan-pages/orphan-pages",
    ]


def test_a_fixed_finding_passes_and_tighten_drops_its_line(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "/a\tcore/h1/missing-h1\n", "--tighten")
    assert proc.returncode == 0, proc.stdout
    assert "fixed, drop it from the baseline: /a core/h1/missing-h1" in proc.stdout
    assert _lines(tmp_path) == []


def test_tighten_never_records_a_new_finding(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [H1], "/b\tcore/h1/missing-h1\n", "--tighten")
    assert proc.returncode == 1
    assert _lines(tmp_path) == []


def test_strict_fails_on_a_fix_the_baseline_still_lists(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "/a\tcore/h1/missing-h1\n", "--strict", "--sample")
    assert proc.returncode == 1
    assert "squirrel.py drop --log" in proc.stdout


def test_a_sample_judges_only_the_pages_it_audited(tmp_path: Path) -> None:
    baseline = "/c\tcore/h1/missing-h1\n*\tsecurity/hsts/hsts\n"
    proc = _ratchet(tmp_path, [], baseline, "--strict", "--sample", scores={"Links": 50})
    assert proc.returncode == 0, proc.stdout


def test_a_sample_update_rewrites_only_its_own_pages(tmp_path: Path) -> None:
    baseline = "score:Links=80\n/a\tcore/h1/missing-h1\n/c\tcore/h1/missing-h1\n"
    proc = _ratchet(
        tmp_path, [_row("/b", "core/h1", "missing-h1")], baseline, "--sample", "--update"
    )
    assert proc.returncode == 0, proc.stderr
    assert _lines(tmp_path) == [
        "score:Links=80",
        "/b\tcore/h1/missing-h1",
        "/c\tcore/h1/missing-h1",
    ]


def test_a_category_below_its_baseline_fails(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "score:Core SEO=93\n", scores={"Core SEO": 92})
    assert proc.returncode == 1
    assert "Core SEO scored 92, baseline 93" in proc.stdout


def test_a_category_the_baseline_does_not_list_must_score_100(tmp_path: Path) -> None:
    assert _ratchet(tmp_path, [], "", scores={"Video": 100}).returncode == 0
    assert _ratchet(tmp_path, [], "", scores={"Video": 99}).returncode == 1


def test_tighten_raises_a_score_and_update_records_only_those_below_100(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "score:Images=51\n", "--tighten", scores={"Images": 60})
    assert proc.returncode == 0, proc.stdout
    assert _lines(tmp_path) == ["score:Images=60"]
    _ratchet(tmp_path, [], "", "--update", scores={"Images": 51, "Video": 100})
    assert _lines(tmp_path) == ["score:Images=51"]


def test_a_crawl_that_audited_other_pages_than_listed_fails_loud(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "", pages=["/", "/about"], listed=["/", "/compare/x"])
    assert proc.returncode != 0
    assert "not the 2 listed" in proc.stderr


def test_a_full_crawl_may_audit_linked_pages_beyond_the_list_and_a_sample_may_not(
    tmp_path: Path,
) -> None:
    pages, listed = ["/", "/de/automate", "/de/automate/page/2"], ["/", "/de/automate"]
    assert _ratchet(tmp_path, [], "", pages=pages, listed=listed).returncode == 0
    sample = _ratchet(tmp_path, [], "", "--sample", pages=pages, listed=listed)
    assert sample.returncode != 0
    assert "extra ['/de/automate/page/2']" in sample.stderr


def test_drop_applies_the_fixes_a_ratchet_run_printed(tmp_path: Path) -> None:
    baseline = "score:Images=51\n/a\tcore/h1/missing-h1\n/b\tcontent/keyword-stuffing/keyword-stuffing\tgaia\n/c\tcore/h1/missing-h1\n"
    rows = [_row("/c", "core/h1", "missing-h1")]
    proc = _ratchet(tmp_path, rows, baseline, scores={"Images": 60})
    log = tmp_path / "ci.log"
    log.write_text(
        "".join(f"2026-11-12T00:00:00Z ##[error]{line}\n" for line in proc.stdout.splitlines())
    )
    dropped = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "drop", "--log", str(log), "--baseline", str(tmp_path / "baseline.txt")],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert dropped.returncode == 0, dropped.stderr
    assert _lines(tmp_path) == ["score:Images=60", "/c\tcore/h1/missing-h1"]
    assert _ratchet(tmp_path, rows, (tmp_path / "baseline.txt").read_text(), "--strict", scores={"Images": 60}).returncode == 0  # fmt: skip


def test_drop_refuses_a_fix_the_baseline_does_not_list(tmp_path: Path) -> None:
    (tmp_path / "baseline.txt").write_text("/a\tcore/h1/missing-h1\n")
    log = tmp_path / "ci.log"
    log.write_text("squirrel: fixed, drop it from the baseline: /z core/h1/missing-h1\n")
    dropped = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "drop", "--log", str(log), "--baseline", str(tmp_path / "baseline.txt")],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert dropped.returncode != 0
    assert "not in" in dropped.stderr


@pytest.mark.parametrize(
    "row",
    [
        _row("/ja/compare/asana", "content/word-count", "word-count"),
        _row("/ja/compare/asana", "core/meta-title", "meta-title"),
        _row("/ko/compare/asana", "core/meta-description", "meta-description"),
        _row("/learn/cron-job", "content/unrendered-markup", "unrendered-markup", [{"id": f"{SITE}/learn/cron-job", "label": "4 unrendered markup occurrence(s) in visible text (markdown-emphasis): example (*/15 in the minute field means every 15 minutes). Common examples: 0 2 *"}]),
        _row("/ko/compare/asana", "content/keyword-stuffing", "keyword-stuffing", [{"id": "asana"}]),
        _row("/a", "content/placeholder-text", "placeholder-content", [{"id": "unrendered-template", "snippet": "[[wiki links]]"}]),
        _row("/a", "content/word-count", "word-count"),
        _row("/contact", "content/word-count", "word-count"),
    ],
)  # fmt: skip
def test_the_ignore_list_drops_what_is_not_a_finding(tmp_path: Path, row: Row) -> None:
    pages = [
        "/",
        "/a",
        "/a/x",
        "/contact",
        "/learn/cron-job",
        "/ja/compare/asana",
        "/ko/compare/asana",
    ]
    proc = _ratchet(tmp_path, [row], "", pages=pages)
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize(
    "row",
    [
        _row("/About", "url/lowercase", "lowercase"),
        _row("/pt-br/compare", "url/lowercase", "lowercase"),
        _row("/de/compare/asana", "content/word-count", "word-count"),
        _row("/de/compare/asana", "core/meta-title", "meta-title"),
        _row("/ja/compare/asana", "core/canonical", "canonical"),
        _row("/b", "content/unrendered-markup", "unrendered-markup", [{"id": f"{SITE}/b", "label": "2 unrendered markup occurrence(s) in visible text (markdown-emphasis): example *bold* text"}]),
        _row("/b", "content/placeholder-text", "placeholder-content", [{"id": "unrendered-template", "snippet": "[['L-12345',85,'Hot']]"}]),
        _row("/b", "content/word-count", "word-count"),
    ],
)  # fmt: skip
def test_the_same_rules_still_count_a_real_finding(tmp_path: Path, row: Row) -> None:
    pages = [
        "/",
        "/a",
        "/a/x",
        "/b",
        "/About",
        "/pt-br/compare",
        "/de/compare/asana",
        "/ja/compare/asana",
    ]
    assert _ratchet(tmp_path, [row], "", pages=pages).returncode == 1


def test_a_red_full_crawl_writes_a_short_alert(tmp_path: Path) -> None:
    output = tmp_path / "github_output"
    pages = ["/", *(f"/p{n}" for n in range(8))]
    rows = [_row(f"/p{n}", f"rule{r}/x", "check") for r in range(6) for n in range(r + 1)]
    proc = _ratchet(tmp_path, rows, "score:Links=90\n", "--github-output", str(output), pages=pages, scores={"Links": 85})  # fmt: skip
    assert proc.returncode == 1
    alert = output.read_text().split("\n", 1)[1].rsplit("\nSQUIRREL_EOF", 1)[0].splitlines()
    assert alert[0] == "🔴 **SEO crawl of heygaia.io**: 1 categories dropped, 21 new findings"
    assert alert[1] == "Scores: Links 90 -> 85"
    assert alert[2] == "`rule5/x/check` +6: /p0, /p1, /p2"
    assert alert[-1] == "…and 3 more in 2 other rules"
    assert len(alert) == 7
    env = {**os.environ, "DRY_RUN": "true", "COLOR": "#ff6b6b", "RUN_LINK": "https://x.test/runs/1"}
    notify = subprocess.run(
        ["bash", str(SCRIPT.parents[1] / "deploy.sh"), "notify"],
        env={**env, "MESSAGE": "\n".join(alert)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert notify.returncode == 0, notify.stdout + notify.stderr


def test_a_malformed_baseline_line_fails_loud(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "core/h1=2\n")
    assert proc.returncode != 0
    assert "expected `<page>" in proc.stderr


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


SITEMAP_PATHS = ["", "/about", "/compare", "/compare/b", "/compare/a", "/compare/c", "/de/compare", "/de/compare/c", "/de/compare/b", "/features", "/features/x", "/features/y"]  # fmt: skip
LANDING = "apps/web/src/app/[locale]/(landing)"
TEMPLATES = ["", "/about", "/compare", "/compare/a", "/de/compare", "/de/compare/b", "/features", "/features/x"]  # fmt: skip


@pytest.mark.parametrize(
    ("changed", "extra"),
    [
        ({"apps/web/public/data/comparisons/c.json": '{"name": "C"}'}, ["/compare/c", "/de/compare/c"]),
        ({f"{LANDING}/compare/[slug]/page.tsx": "2"}, ["/compare/b", "/compare/c", "/de/compare/c"]),
        ({"apps/web/src/features/landing/data/features/productivity.ts": "2"}, ["/features/y"]),
        ({f"{LANDING}/layout.tsx": "2"}, []),
    ],
    ids=["page-data", "route-template", "page-copy-module", "site-shell"],
)  # fmt: skip
def test_a_pr_audits_one_page_per_template_per_locale_and_every_page_its_diff_renders(
    tmp_path: Path, changed: dict[str, str], extra: list[str]
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    config = 'export const locales = ["en", "de"] as const;\nexport const defaultLocale: Locale = "en";\n'
    previous = _commit(repo, {"apps/web/src/i18n/config.ts": config, **dict.fromkeys(changed, "1")})
    head = _commit(repo, changed)
    urls = "".join(f"<url><loc>{SITE}{p}</loc></url>" for p in SITEMAP_PATHS)
    routes: Routes = {"/sitemap.xml": (200, {}, f"<urlset>{urls}</urlset>")}
    out = tmp_path / "pages.txt"
    with serve(routes) as base:
        subprocess.run(
            [
                sys.executable, "-I", str(SCRIPT), "pages", "--site", SITE, "--base", base,
                "--repo", str(repo), "--previous", previous, "--head", head, "--out", str(out),
            ],
            check=True,
            env={**os.environ},
        )  # fmt: skip
    assert out.read_text().split() == sorted({SITE + p for p in TEMPLATES + extra})


def test_a_full_crawl_drops_the_lines_of_a_page_the_sitemap_no_longer_lists(tmp_path: Path) -> None:
    proc = _ratchet(tmp_path, [], "/gone\tcore/h1/missing-h1\n", "--tighten")
    assert proc.returncode == 0, proc.stdout
    assert _lines(tmp_path) == []


def test_a_sample_does_not_judge_a_rule_that_needs_the_whole_site(tmp_path: Path) -> None:
    rows = [_row("/a", "links/orphan-pages", "orphan-pages")]
    baseline = "/b\tlinks/orphan-pages/orphan-pages\n"
    assert _ratchet(tmp_path, rows, baseline, "--sample", "--strict").returncode == 0
    _ratchet(tmp_path, rows, baseline, "--sample", "--update")
    assert _lines(tmp_path) == ["/b\tlinks/orphan-pages/orphan-pages"]
    assert _ratchet(tmp_path, rows, baseline).returncode == 1
