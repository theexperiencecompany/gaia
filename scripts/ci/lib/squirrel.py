"""Choose the pages squirrelscan audits for the SEO lane and hold its findings to a baseline.

pages   lists the pages to audit: every sitemap URL (--all), or for a PR one page per
        template per locale plus every page the diff renders (indexnow.py's mapping).
ratchet reads the finished crawl from squirrel's own database, one finding per page,
        check and item, and fails on any finding the baseline does not list. A full
        crawl also holds every category score to its baseline and, with --tighten,
        rewrites the baseline without what it fixed; a PR's crawl judges only its pages.
drop    applies the fixes a ratchet run printed (its CI log or verdict) to the baseline,
        so the PR that fixed them drops their lines without a full crawl.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import TypedDict
import urllib.parse

# python -I leaves scripts/ci off sys.path; the sitemap reader and the diff mapping are shared.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.indexnow import classify, load_repo, map_changes, split_url, web_diff
from lib.seo_audit import LOCALE_PREFIX as SITE_LOCALE, Site, sitemap_urls

REPO_ROOT = Path(__file__).resolve().parents[3]
FINDING_STATUSES = ("fail", "warn")
SCORE_PREFIX = "score:"
PERFECT_SCORE = 100
SITE_WIDE = "*"
UPDATE_HINT = "`python3 scripts/ci/lib/squirrel.py drop --log <this log> --baseline <it>`"
FIXED = re.compile(r"squirrel: fixed, drop it from the baseline: (\S+) (\S+)(?: \[(.*)\])?\s*$")
RAISED = re.compile(r"squirrel: (.+?) rose to (\d+), baseline (\d+)\s*$")
ALERT_RULES = 4
ALERT_EXAMPLES = 3
CJK_LOCALES = ("ja", "ko")
CJK_LENGTH_RULES = frozenset(
    {"content/word-count", "content/keyword-stuffing", "core/meta-title", "core/meta-description"}
)
# A cron field (*/15) or a run of them (0 2 * * *): squirrel reads the asterisks as markdown.
CRON_SYNTAX = re.compile(r"\*/\d|\d \d+ \*|\* \* \*")
# Next.js content-hashes every build asset: /_next/static/chunks/2o_wf2t990r7t.css.
BUILD_ASSET = re.compile(r"(/_next/static/(?:chunks|media|css)/)[^/\s\"]+?(\.[a-z0-9]+)\b")
BUILD_ID = re.compile(r"/_next/static/(?!chunks/|media/|css/)[^/\s\"]+/")
# An item naming a build asset (a CSS chunk, a source map) is one finding however many
# pages load it: keyed per page, two such checks were 8,800 of 10,400 baseline lines.
BUILD_PATH = re.compile(r"/_next/")
# React's useId values move whenever the component tree above them does.
REACT_ID = re.compile(r"react-aria-[\w-]+")
# A timing is a moment, not a page: two live crawls an hour apart flagged 1,008 and
# 1,336 pages slow, so it counts only through the Performance score.
TIMED_RULES = frozenset({"perf/ttfb"})
# Rules that judge a page against the rest of the crawl (its inbound links, its schema
# next to its peers'): on the PR gate's 126 pages they disagreed with the full crawl of
# the same build on 69 pages, and no-contextual-inbound on 18, so only a full crawl judges them.
CRAWL_RELATIVE_RULES = frozenset(
    {
        "links/orphan-pages",
        "links/weak-internal-links",
        "links/no-contextual-inbound",
        "schema/coverage-outlier",
    }
)
# Listing pages with no sitemap page under them, kept short on purpose (#1701 shortened their intros).
SHORT_PAGES = frozenset({"/download", "/contact"})
WIKI_LINK = re.compile(r"^\[\[[^\[\]'\"]+\]\]$")
# One integration's page; the paginated hub (/marketplace/page/N) is ours and stays checked.
MARKETPLACE_DETAIL = re.compile(r"^/marketplace/[^/]+$")
PLACEHOLDER_RULES = frozenset({"content/placeholder-contact", "content/placeholder-text"})
BASELINE_HEADER = """\
# squirrelscan's findings, which `scripts/ci/smoke-web.sh` holds to this file:
# `<page path>\\t<rule id>/<check>[\\t<item>]`, one per line, `*` as the page of a
# site-wide finding, and `score:<category>=<score>` the lowest score a category
# below 100 may fall to. squirrel-build.txt is the PR gate's, on the production
# build served locally (`audit-build`, which audits only some pages and judges
# only those); squirrel-live.txt is the full crawl's, on https://heygaia.io
# (`squirrel`, after every deploy and nightly). They differ where Cloudflare's
# edge does: image resizing, caching and response headers.
#
# Generated, never hand-edited: a crawl rewrites it (SMOKE_SQUIRREL_UPDATE=1).
# The PR that fixes a finding drops its line, and a finding not listed fails.
"""


class Item(TypedDict, total=False):
    """One item of a squirrel check result: what on the page the check names."""

    id: str
    label: str
    snippet: str


@dataclass(frozen=True, order=True)
class Finding:
    """One finding: the page it is on (or SITE_WIDE), the rule's check and the item it names."""

    page: str
    check: str
    item: str = ""

    @property
    def rule(self) -> str:
        return self.check.rsplit("/", 1)[0]

    def line(self) -> str:
        return "\t".join(field for field in (self.page, self.check, self.item) if field)

    def __str__(self) -> str:
        return f"{self.page} {self.check}" + (f" [{self.item}]" if self.item else "")


@dataclass(frozen=True)
class Observed:
    finding: Finding
    item: Item


@dataclass(frozen=True)
class Ignore:
    """A finding squirrel reports that is not one: the predicate, why, and what showed it."""

    reason: str
    evidence: str
    applies: Callable[[Observed, frozenset[str]], bool]


def _cjk_length(seen: Observed, _pages: frozenset[str]) -> bool:
    page = seen.finding.page
    on_cjk = any(page == f"/{loc}" or page.startswith(f"/{loc}/") for loc in CJK_LOCALES)
    return on_cjk and seen.finding.rule in CJK_LENGTH_RULES


def _wiki_link_text(seen: Observed, _pages: frozenset[str]) -> bool:
    snippet = seen.item.get("snippet", "")
    return seen.finding.rule == "content/placeholder-text" and bool(WIKI_LINK.match(snippet))


def _cron_as_markdown(seen: Observed, _pages: frozenset[str]) -> bool:
    label = seen.item.get("label", "")
    emphasis = "(markdown-emphasis)" in label and bool(CRON_SYNTAX.search(label))
    return seen.finding.rule == "content/unrendered-markup" and emphasis


def _synced_tool_docs(seen: Observed, _pages: frozenset[str]) -> bool:
    page = seen.finding.page
    return seen.finding.rule in PLACEHOLDER_RULES and bool(MARKETPLACE_DETAIL.match(page))


def _hub_word_count(seen: Observed, pages: frozenset[str]) -> bool:
    page = seen.finding.page
    index = page != "/" and any(other.startswith(f"{page}/") for other in pages)
    listing = SITE_LOCALE.sub("", page) in SHORT_PAGES
    return seen.finding.rule == "content/word-count" and (index or listing)


# Only squirrel's own bugs, and one design decision: everything else is a finding.
IGNORED = (
    Ignore(
        "squirrel measures Japanese and Korean by Latin rules: words by spaces, lengths in "
        "characters, so CJK prose reads thin, a Latin product name in it as stuffing, and a "
        "title or description too short",
        "/ja/compare/asana has 2,726 CJK characters, reported as 107 words and 'asana' at "
        "16.9%; '2026年版 Any.do 最良の代替 | GAIA' reported as a 26-character title, too short; "
        "its 120-character description minimum overflows a CJK snippet, which shows ~70-80 "
        "characters on mobile and ~90-120 on desktop (sungrove.co.jp, xserver.ne.jp, 2025), "
        "where ours run 70-129 (ja median 82, ko median 87)",
        _cjk_length,
    ),
    Ignore(
        "[[...]] in copy is the wiki-link syntax the glossary and comparisons describe, not an "
        "unrendered template",
        "/compare/obsidian quotes [[wiki links]]; /alternative-to/roam-research quotes [[bracket]]",
        _wiki_link_text,
    ),
    Ignore(
        "a cron expression's asterisks read as markdown emphasis",
        "/learn/cron-job: 'example (*/15 in the minute field means every 15 minutes). Common "
        "examples: 0 2 *' reported as unrendered markdown-emphasis",
        _cron_as_markdown,
    ),
    Ignore(
        "an integration page shows its tools' documentation as the API syncs it from the "
        "provider (Composio), sample addresses included; it changes with no deploy of ours, "
        "so no baseline can pin it",
        "/marketplace/googlesheets gained jane@example.com and john@example.com from its "
        "Composio tool docs between two crawls on 2026-11-12, with no commit in between",
        _synced_tool_docs,
    ),
    Ignore(
        "founder's decision, not a squirrel bug: hub indexes (a page other pages sit under: "
        "/marketplace, /blog, /use-cases, /compare, /ja/for) and the /download and /contact "
        "listings are short by design",
        "/ja/for 49 words, /contact 59, /marketplace 178, /blog 188, /download 193; #1701 "
        "shortened their intros on purpose",
        _hub_word_count,
    ),
)


def _ignored(seen: Observed, pages: frozenset[str]) -> bool:
    return any(rule.applies(seen, pages) for rule in IGNORED)


def _path(url: str, site: str) -> str:
    return (url[len(site) :] or "/") if url.startswith(site) else url


def _stable(item_id: str, site: str) -> str:
    """Strip what changes between builds from an item id, and the site's own origin."""
    item_id = BUILD_ASSET.sub(r"\1*\2", item_id.replace(site, ""))
    return " ".join(REACT_ID.sub("react-aria-*", BUILD_ID.sub("/_next/static/*/", item_id)).split())


@dataclass(frozen=True)
class Crawl:
    pages: frozenset[str]
    findings: frozenset[Finding]


def _items(raw: str | None) -> list[Item]:
    return list(json.loads(raw)) if raw else []


def _observe(
    row: tuple[str, str, str, str, str | None, str | None], site: str, crawled: frozenset[str]
) -> Iterable[Observed]:
    page_url, rule, check, message, raw_items, raw_pages = row
    name, items = f"{rule}/{check}", _items(raw_items)
    if page_url:
        page = _path(page_url, site)
        for item in items:
            named = "" if item["id"] == page_url else _stable(item["id"], site)
            where = SITE_WIDE if BUILD_PATH.search(named) else page
            yield Observed(Finding(where, name, named), item)
        if not items:
            yield Observed(Finding(page, name), Item(label=message))
        return
    for item in items:
        if item["id"] in crawled:
            yield Observed(Finding(_path(item["id"], site), name), item)
        else:
            yield Observed(Finding(SITE_WIDE, name, _stable(item["id"], site)), item)
    listed = json.loads(raw_pages) if raw_pages else []
    if not items:
        for url in listed or [""]:
            yield Observed(
                Finding(_path(url, site) if url else SITE_WIDE, name), Item(label=message)
            )


def project_db(home: Path) -> Path:
    """Find the one project database squirrel wrote under the HOME it ran with."""
    found = sorted(home.glob(".squirrel/projects/*/project.db"))
    if len(found) != 1:
        raise SystemExit(f"squirrel: expected one project database under {home}, found {found}")
    return found[0]


def read_crawl(db: Path, site: str) -> Crawl:
    """Read the one crawl in squirrel's project database as findings, the ignored ones dropped."""
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as con:
        crawls = [row[0] for row in con.execute("SELECT id FROM crawls")]
        if len(crawls) != 1:
            raise SystemExit(f"squirrel: expected one crawl in {db}, found {len(crawls)}")
        crawled = frozenset(
            u for (u,) in con.execute("SELECT url FROM pages WHERE crawl_id = ?", crawls)
        )
        rows = con.execute(
            "SELECT page_url, rule_id, check_name, message, items, pages FROM rule_results"
            " WHERE crawl_id = ? AND status IN (?, ?)",
            (*crawls, *FINDING_STATUSES),
        ).fetchall()
    paths = frozenset(_path(u, site) for u in crawled)
    seen = (o for row in rows for o in _observe(row, site, crawled))
    kept = (o.finding for o in seen if o.finding.rule not in TIMED_RULES and not _ignored(o, paths))
    return Crawl(paths, frozenset(kept))


class _Category(TypedDict):
    name: str
    score: int


class _Score(TypedDict):
    categories: list[_Category]


class Report(TypedDict):
    """The part of squirrel's --format json report the ratchet reads."""

    score: _Score


def category_scores(report: Report) -> dict[str, int]:
    """Return each category's score, keyed as the baseline names it."""
    return {f"{SCORE_PREFIX}{c['name']}": c["score"] for c in report["score"]["categories"]}


@dataclass(frozen=True)
class Baseline:
    findings: frozenset[Finding]
    scores: dict[str, int]


def read_baseline(path: Path) -> Baseline:
    findings: set[Finding] = set()
    scores: dict[str, int] = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith(SCORE_PREFIX):
            key, _, value = line.partition("=")
            if not value.isdigit():
                raise SystemExit(
                    f"{path}:{number}: expected `score:<category>=<score>`, got {line!r}"
                )
            scores[key] = int(value)
            continue
        fields = line.split("\t")
        if len(fields) not in (2, 3):
            raise SystemExit(
                f"{path}:{number}: expected `<page>\\t<rule>/<check>[\\t<item>]`, got {line!r}"
            )
        findings.add(Finding(*fields))
    return Baseline(frozenset(findings), scores)


def write_baseline(path: Path, baseline: Baseline) -> None:
    scores = [f"{k}={v}" for k, v in sorted(baseline.scores.items()) if v < PERFECT_SCORE]
    lines = scores + [f.line() for f in sorted(baseline.findings)]
    path.write_text(BASELINE_HEADER + "\n" + "\n".join(lines) + "\n")


# (category, baseline score, crawled score)
ScoreChange = tuple[str, int, int]


@dataclass(frozen=True)
class Verdict:
    new: list[Finding]
    fixed: list[Finding]
    dropped: list[ScoreChange]
    raised: list[ScoreChange]


def _sampled(finding: Finding, crawl: Crawl) -> bool:
    """Whether a crawl of only some pages can tell this finding is gone."""
    return finding.page in crawl.pages and finding.rule not in CRAWL_RELATIVE_RULES


def judge(crawl: Crawl, scores: dict[str, int] | None, baseline: Baseline) -> Verdict:
    """Compare a crawl with the baseline; scores is None for a crawl of only some pages.

    A crawl of some pages judges only the page findings on them, and none of a rule
    that needs the whole site: a finding it does not see may be on a page it skipped.
    """
    if scores is None:
        found = {f for f in crawl.findings if f.rule not in CRAWL_RELATIVE_RULES}
        judged = {f for f in baseline.findings if _sampled(f, crawl)}
    else:
        # Every line, a page no longer in the sitemap included: its findings are gone too.
        found = set(crawl.findings)
        judged = set(baseline.findings)
    dropped: list[ScoreChange] = []
    raised: list[ScoreChange] = []
    for key in sorted((scores or {}).keys() | baseline.scores.keys()):
        now = (scores or {}).get(key, PERFECT_SCORE)
        allowed = baseline.scores.get(key, PERFECT_SCORE)
        if scores is not None and now != allowed:
            (dropped if now < allowed else raised).append((key[len(SCORE_PREFIX) :], allowed, now))
    return Verdict(sorted(found - baseline.findings), sorted(judged - found), dropped, raised)


def tightened(baseline: Baseline, verdict: Verdict) -> Baseline:
    scores = dict(baseline.scores) | {f"{SCORE_PREFIX}{c}": now for c, _, now in verdict.raised}
    return Baseline(baseline.findings - set(verdict.fixed), scores)


def recorded(baseline: Baseline, crawl: Crawl, scores: dict[str, int] | None) -> Baseline:
    """Accept a crawl as the baseline: a full one replaces it, a sample replaces its pages' lines."""
    if scores is not None:
        return Baseline(crawl.findings, scores)
    kept = {f for f in baseline.findings if not _sampled(f, crawl)}
    found = {f for f in crawl.findings if f.rule not in CRAWL_RELATIVE_RULES}
    return Baseline(frozenset(kept | found), baseline.scores)


def alert_message(verdict: Verdict, site: str) -> str:
    """Render a red full crawl as a few short lines: what dropped and the new findings by rule."""
    by_rule: dict[str, list[Finding]] = defaultdict(list)
    for finding in verdict.new:
        by_rule[finding.check].append(finding)
    host = urllib.parse.urlparse(site).netloc
    parts = []
    if verdict.dropped:
        parts.append(f"{len(verdict.dropped)} categories dropped")
    if verdict.new:
        parts.append(f"{len(verdict.new)} new findings")
    lines = [f"🔴 **SEO crawl of {host}**: {', '.join(parts)}"]
    if verdict.dropped:
        lines.append(
            "Scores: " + ", ".join(f"{c} {old} -> {new}" for c, old, new in verdict.dropped)
        )
    ranked = sorted(by_rule.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for check, found in ranked[:ALERT_RULES]:
        examples = ", ".join(sorted({f.page for f in found})[:ALERT_EXAMPLES])
        lines.append(f"`{check}` +{len(found)}: {examples}")
    if len(ranked) > ALERT_RULES:
        rest = sum(len(found) for _, found in ranked[ALERT_RULES:])
        lines.append(f"…and {rest} more in {len(ranked) - ALERT_RULES} other rules")
    return "\n".join(lines)


def _annotated(path: Path) -> Path:
    resolved = path.resolve()
    return resolved.relative_to(REPO_ROOT) if resolved.is_relative_to(REPO_ROOT) else resolved


def _write_output(path: Path, name: str, value: str) -> None:
    with path.open("a") as out:
        out.write(f"{name}<<SQUIRREL_EOF\n{value}\nSQUIRREL_EOF\n")


def _check_coverage(crawl: Crawl, pages_file: Path, site: str, sample: bool) -> None:
    """Fail unless a sample audited exactly its list, and a full crawl at least every listed page."""
    listed = frozenset(_path(u, site) for u in pages_file.read_text().split())
    missing, extra = sorted(listed - crawl.pages), sorted(crawl.pages - listed)
    if missing or (sample and extra):
        raise SystemExit(
            f"squirrel: audited {len(crawl.pages)} pages, not the {len(listed)} listed "
            f"(missing {missing[:5]}, extra {extra[:5]})"
        )


def _report(verdict: Verdict, strict: bool, annotated: Path) -> bool:
    """Print the verdict as annotations; return whether it fails the run."""
    for finding in verdict.new:
        print(f"::error file={annotated}::squirrel: new finding {finding}")
    for category, old, new in verdict.dropped:
        print(f"::error file={annotated}::squirrel: {category} scored {new}, baseline {old}")
    prefix = f"::error file={annotated}::" if strict else ""
    for finding in verdict.fixed:
        print(f"{prefix}squirrel: fixed, drop it from the baseline: {finding}")
    for category, old, new in verdict.raised:
        print(f"{prefix}squirrel: {category} rose to {new}, baseline {old}")
    if strict and (verdict.fixed or verdict.raised):
        print(f"squirrel: drop the fixes from {annotated} in this PR: {UPDATE_HINT}")
    return bool(verdict.new or verdict.dropped or (strict and (verdict.fixed or verdict.raised)))


def cmd_ratchet(args: argparse.Namespace) -> int:
    site = args.site.rstrip("/")
    crawl = read_crawl(project_db(args.home), site)
    _check_coverage(crawl, args.pages, site, args.sample)
    scores = None if args.sample else category_scores(json.loads(args.report.read_text()))
    if not args.baseline.exists() and not args.update:
        raise SystemExit(f"squirrel: no baseline at {args.baseline}; record one with {UPDATE_HINT}")
    baseline = read_baseline(args.baseline) if args.baseline.exists() else Baseline(frozenset(), {})
    if args.update:
        write_baseline(args.baseline, recorded(baseline, crawl, scores))
        print(
            f"squirrel: recorded {len(crawl.findings)} findings on {len(crawl.pages)} pages in {args.baseline}"
        )
        return 0
    verdict = judge(crawl, scores, baseline)
    failed = _report(verdict, args.strict, _annotated(args.baseline))
    if args.tighten and (verdict.fixed or verdict.raised):
        write_baseline(args.baseline, tightened(baseline, verdict))
        print(
            f"squirrel: tightened {args.baseline} ({len(verdict.fixed)} fixed, {len(verdict.raised)} raised)"
        )
    if failed and args.github_output and (verdict.new or verdict.dropped):
        _write_output(args.github_output, "alert", alert_message(verdict, site))
    summary = (
        f"{len(crawl.findings)} findings on {len(crawl.pages)} pages: {len(verdict.new)} new, "
        f"{len(verdict.dropped)} scores dropped, {len(verdict.fixed)} fixed, {len(verdict.raised)} raised"
    )
    print(f"squirrel: {'FAIL' if failed else 'OK'} ({summary})")
    return int(failed)


def template_of(url: str, site: str, locales: tuple[str, ...]) -> tuple[str, str]:
    """Name the template a sitemap URL renders: its locale and its route with each slug as *."""
    locale, path = split_url(url, site, locales)
    segments = [s for s in path.split("/") if s]
    return locale, "/" + "/".join(segments[:1] + ["*"] * (len(segments) - 1))


def sample(urls: list[str], site: str, locales: tuple[str, ...]) -> list[str]:
    """Pick one page per template per locale: the first URL of each in sort order."""
    picked: dict[tuple[str, str], str] = {}
    for url in sorted(urls):
        picked.setdefault(template_of(url, site, locales), url)
    return sorted(picked.values())


def cmd_pages(args: argparse.Namespace) -> int:
    site = args.site.rstrip("/")
    urls = sitemap_urls(Site(site, args.base.rstrip("/")), None)
    if args.all:
        chosen = set(urls)
    else:
        repo = load_repo(args.repo, args.previous, args.head)
        # Every page the diff renders, as IndexNow is told, but for a change to the shell
        # every page wraps: it renders the same on each, so one page per template judges it.
        changes = replace(map_changes(repo, web_diff(repo)), whole_site=False)
        changed, _ = classify(changes, set(urls), site, repo)
        templates = sample(urls, site, repo.locales)
        chosen = set(templates) | changed
        print(
            f"squirrel: {len(templates)} template pages + {len(changed - set(templates))} the diff renders"
        )
    args.out.write_text("\n".join(sorted(chosen)) + "\n")
    print(f"squirrel: {len(chosen)} of {len(urls)} sitemap pages to audit")
    return 0


def cmd_drop(args: argparse.Namespace) -> int:
    baseline = read_baseline(args.baseline)
    fixed: set[Finding] = set()
    scores = dict(baseline.scores)
    for line in args.log.read_text(errors="replace").splitlines():
        if match := FIXED.search(line):
            fixed.add(Finding(match[1], match[2], match[3] or ""))
        elif match := RAISED.search(line):
            key, now, logged = f"{SCORE_PREFIX}{match[1]}", int(match[2]), int(match[3])
            if baseline.scores.get(key, PERFECT_SCORE) != logged:
                raise SystemExit(
                    f"squirrel: {key} is {baseline.scores.get(key)} in {args.baseline}, the log saw {logged}: a stale log"
                )
            scores[key] = now
    unknown = fixed - baseline.findings
    if unknown:
        raise SystemExit(
            f"squirrel: {len(unknown)} fixed finding(s) not in {args.baseline}: {sorted(unknown)[:3]}"
        )
    write_baseline(args.baseline, Baseline(baseline.findings - fixed, scores))
    print(f"squirrel: dropped {len(fixed)} fixed finding(s) from {args.baseline}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    drop = sub.add_parser("drop", help="apply the fixes a ratchet run printed to the baseline")
    drop.add_argument(
        "--log", type=Path, required=True, help="a CI log or verdict that printed them"
    )
    drop.add_argument("--baseline", type=Path, required=True)
    drop.set_defaults(run=cmd_drop)
    pages = sub.add_parser("pages", help="list the pages to audit")
    pages.add_argument("--site", required=True, help="the origin the pages name")
    pages.add_argument("--base", required=True, help="where to fetch the sitemap from")
    pages.add_argument("--out", type=Path, required=True)
    pages.add_argument("--all", action="store_true", help="every sitemap URL")
    pages.add_argument("--repo", type=Path, default=REPO_ROOT)
    pages.add_argument("--previous", help="the commit the diff starts from")
    pages.add_argument("--head", default="HEAD")
    pages.set_defaults(run=cmd_pages)
    ratchet = sub.add_parser("ratchet", help="compare a finished crawl with the baseline")
    ratchet.add_argument("--site", required=True)
    ratchet.add_argument("--home", type=Path, required=True, help="the HOME squirrel ran under")
    ratchet.add_argument("--report", type=Path, required=True, help="the --format json report")
    ratchet.add_argument("--pages", type=Path, required=True, help="the pages the crawl was given")
    ratchet.add_argument("--baseline", type=Path, required=True)
    ratchet.add_argument("--sample", action="store_true", help="the crawl audited only some pages")
    ratchet.add_argument("--update", action="store_true", help="record the crawl as the baseline")
    ratchet.add_argument(
        "--strict", action="store_true", help="also fail on a fix not yet recorded"
    )
    ratchet.add_argument(
        "--tighten", action="store_true", help="drop fixed findings from the baseline"
    )
    ratchet.add_argument("--github-output", type=Path, help="write the alert message here")
    ratchet.set_defaults(run=cmd_ratchet)
    args = parser.parse_args()
    if args.command == "pages" and not args.all and not args.previous:
        parser.error("pages: --previous is required unless --all")
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
