"""Configure squirrelscan for the SEO lane and ratchet its findings against a baseline.

config  writes config/squirrel.toml plus the title and description windows from
        apps/web/src/config/seoSnippet.json, so squirrel and seo_audit.py judge one standard.
ratchet measures a squirrel JSON report (findings per rule, score per category) and
        fails on any measure worse than the baseline; one better than it is reported,
        and with --strict fails too. --update rewrites the baseline from the report.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import TypedDict
import urllib.parse

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_CONFIG = REPO_ROOT / "config/squirrel.toml"
SNIPPET_CONFIG = REPO_ROOT / "apps/web/src/config/seoSnippet.json"
PASSING_STATUSES = {"pass", "skip"}
SCORE_PREFIX = "score:"
PERFECT_SCORE = 100
UPDATE_HINT = "SMOKE_SQUIRREL_UPDATE=1 on the smoke-web.sh subcommand that checks it"
# BCP 47 region casing, which hreflang requires: /pt-BR is the locale prefix, not a stray capital.
LOCALE_PREFIX = re.compile(r"^/pt-BR(?=/|$)")
BASELINE_HEADER = """\
# squirrelscan at --level surface, which `scripts/ci/smoke-web.sh` holds to this
# file. `<rule id>=<count>` is the most pages (or, for a site-wide check, items)
# the rule may flag; `score:<category>=<score>` the lowest score a category below
# 100 may fall to. squirrel-build.txt is the PR gate's, on the production build
# served locally (`audit-build`); squirrel-live.txt is the post-deploy run's, on
# https://heygaia.io (`squirrel`). They differ where Cloudflare's edge does:
# image resizing, caching and response headers.
#
# This file only tightens. The PR that fixes a finding rewrites it
# (SMOKE_SQUIRREL_UPDATE=1 on the subcommand above), and the PR gate fails until
# it does; a rule or category worse than its line fails every run.
"""


def _feed_is_not_a_sitemap(rule: str, page: str) -> bool:
    """Google reads the RSS feed robots.txt lists as a sitemap; squirrel only parses sitemap XML."""
    return rule == "crawl/sitemap-valid" and urllib.parse.urlparse(page).path == "/feed.xml"


def _locale_casing(rule: str, page: str) -> bool:
    """Ignore pt-BR's capitals when they are the only capitals in the path."""
    path = urllib.parse.urlparse(page).path
    rest = LOCALE_PREFIX.sub("", path)
    return rule == "url/lowercase" and rest != path and rest == rest.lower()


FALSE_POSITIVES = (_feed_is_not_a_sitemap, _locale_casing)


def _false_positive(rule: str, page: str) -> bool:
    return any(check(rule, page) for check in FALSE_POSITIVES)


class _CheckStatus(TypedDict):
    status: str


class Check(_CheckStatus, total=False):
    """One check of a rule in squirrel's JSON report; the fields the count reads."""

    affectedPages: list[str]
    affectedPagesCount: int
    affectedPagesHasMore: bool
    items: list[object]


class Issue(TypedDict):
    ruleId: str
    checks: list[Check]


class Category(TypedDict):
    name: str
    score: int


class Score(TypedDict):
    categories: list[Category]


class Report(TypedDict):
    """The parts of squirrel's --format json report the ratchet reads."""

    issues: list[Issue]
    score: Score


def _check_count(rule: str, check: Check) -> int:
    pages = check.get("affectedPages", [])
    if check.get("affectedPagesHasMore"):
        return check["affectedPagesCount"] - sum(_false_positive(rule, p) for p in pages)
    if pages:
        return sum(not _false_positive(rule, p) for p in pages)
    return len(check.get("items", [])) or 1


def finding_counts(issues: list[Issue]) -> dict[str, int]:
    """Count the findings per rule id in a squirrel report's issues, false positives dropped."""
    counts: dict[str, int] = {}
    for issue in issues:
        rule = issue["ruleId"]
        total = sum(
            _check_count(rule, check)
            for check in issue["checks"]
            if check["status"] not in PASSING_STATUSES
        )
        if total:
            counts[rule] = counts.get(rule, 0) + total
    return counts


def category_scores(report: Report) -> dict[str, int]:
    """Return each category's score, keyed as the baseline names it."""
    return {f"{SCORE_PREFIX}{c['name']}": c["score"] for c in report["score"]["categories"]}


def read_baseline(path: Path) -> dict[str, int]:
    baseline: dict[str, int] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not value.strip().isdigit():
            raise SystemExit(f"{path}:{number}: expected `<rule id>=<count>`, got {line!r}")
        baseline[key.strip()] = int(value)
    return baseline


def measure(report: Report) -> dict[str, int]:
    """Return every finding count and every category score below a perfect 100."""
    scores = {k: v for k, v in category_scores(report).items() if v < PERFECT_SCORE}
    return finding_counts(report["issues"]) | scores


def write_baseline(path: Path, measured: dict[str, int]) -> None:
    lines = [f"{key}={value}" for key, value in sorted(measured.items())]
    path.write_text(BASELINE_HEADER + "\n" + "\n".join(lines) + "\n")


@dataclass(frozen=True)
class Ratchet:
    regressions: list[str]
    slack: list[str]


def compare(measured: dict[str, int], baseline: dict[str, int]) -> Ratchet:
    """Split the measures into those worse than the baseline and baseline lines left loose."""
    regressions: list[str] = []
    slack: list[str] = []
    for key in sorted(measured.keys() | baseline.keys()):
        if key.startswith(SCORE_PREFIX):
            now, allowed = measured.get(key, PERFECT_SCORE), baseline.get(key, PERFECT_SCORE)
            if now < allowed:
                regressions.append(f"{key}: {now}, baseline {allowed}")
            elif now > allowed:
                slack.append(f"{key}: baseline {allowed}, now {now}")
        else:
            now, allowed = measured.get(key, 0), baseline.get(key, 0)
            if now > allowed:
                regressions.append(f"{key}: {now} finding(s), baseline {allowed}")
            elif now < allowed:
                slack.append(f"{key}: baseline {allowed}, now {now}")
    return Ratchet(regressions, slack)


def cmd_config(args: argparse.Namespace) -> int:
    snippet = json.loads(SNIPPET_CONFIG.read_text())
    windows = {"core/meta-title": "titleLength", "core/meta-description": "descriptionLength"}
    generated = "".join(
        f'\n[rule_options."{rule}"]\nmin_length = {snippet[key]["min"]}\nmax_length = {snippet[key]["max"]}\n'
        for rule, key in windows.items()
    )
    args.out.write_text(BASE_CONFIG.read_text() + generated)
    return 0


def cmd_ratchet(args: argparse.Namespace) -> int:
    measured = measure(json.loads(args.report.read_text()))
    if args.update:
        write_baseline(args.baseline, measured)
        print(f"squirrel: wrote {len(measured)} line(s) to {args.baseline}")
        return 0
    result = compare(measured, read_baseline(args.baseline))
    baseline = args.baseline.resolve()
    annotated = baseline.relative_to(REPO_ROOT) if baseline.is_relative_to(REPO_ROOT) else baseline
    for line in result.regressions:
        print(f"::error file={annotated}::squirrel regression: {line}")
    for line in result.slack:
        prefix = f"::error file={annotated}::" if args.strict else ""
        print(f"{prefix}squirrel: improved past the baseline, tighten it: {line}")
    if result.slack:
        print(f"squirrel: rewrite {annotated} in this PR with {UPDATE_HINT}")
    findings = sum(v for k, v in measured.items() if not k.startswith(SCORE_PREFIX))
    if result.regressions or (args.strict and result.slack):
        print(
            f"squirrel: FAIL ({len(result.regressions)} worse than the baseline, "
            f"{len(result.slack)} better and not yet recorded; {findings} findings)"
        )
        return 1
    print(f"squirrel: OK ({findings} findings, no rule or category worse than the baseline)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("config", help="write the effective squirrel.toml")
    config.add_argument("--out", type=Path, required=True)
    config.set_defaults(run=cmd_config)
    ratchet = sub.add_parser("ratchet", help="compare a report with the baseline")
    ratchet.add_argument("--report", type=Path, required=True)
    ratchet.add_argument("--baseline", type=Path, required=True)
    ratchet.add_argument(
        "--update", action="store_true", help="rewrite the baseline from the report"
    )
    ratchet.add_argument(
        "--strict", action="store_true", help="also fail on a baseline line the report beats"
    )
    ratchet.set_defaults(run=cmd_ratchet)
    args = parser.parse_args()
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
