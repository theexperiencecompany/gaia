"""Tell IndexNow (Bing, Yandex, Seznam, Naver) which marketing pages a production deploy changed.

Files changed between the last successfully deployed commit and this one map to the
pages they render; the live sitemap splits those into updated (listed) and deleted
(no longer listed). At most 10,000 URLs per request; a non-2xx answer fails the run.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

# python -I leaves the script's own directory off sys.path; the sitemap reader is shared with the audit.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seo_audit import Site, sitemap_urls

ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH_MAX = 10_000
TIMEOUT_S = 30
DEPLOY_BRANCH = "master"
WEB = "apps/web"
PUBLIC = f"{WEB}/public"
LOCALE_CONFIG = f"{WEB}/src/i18n/config.ts"
KEY_FILE = re.compile(r"^[0-9a-f]{32}\.txt$")
SLUG_INDEX = "_slugs"

# public/data/<feature> -> its route, and whether sitemapData.ts lists it per locale (withLocaleUrls).
FAMILIES: dict[str, tuple[str, bool]] = {
    "comparisons": ("/compare", True),
    "alternatives": ("/alternative-to", True),
    "glossary": ("/learn", True),
    "combos": ("/automate", True),
    "personas": ("/for", True),
    "blog": ("/blog", False),
}
# public/data/i18n/<feature> -> the public/data feature its <locale>.json overlays, keyed by slug.
I18N_FEATURES = {
    "comparisons": "comparisons",
    "alternatives": "alternatives",
    "glossary": "glossary",
    "personas": "personas",
    "integrations": "combos",
}

DATA_FILE = re.compile(rf"^{PUBLIC}/data/([^/]+)/([^/]+)\.json$")
I18N_FILE = re.compile(rf"^{PUBLIC}/data/i18n/([^/]+)/([^/]+)\.json$")
BLOG_SOURCE = re.compile(rf"^{WEB}/content/blog/([^/]+)\.mdx?$")
LANDING_FILE = re.compile(rf"^{re.escape(WEB + '/src/app/[locale]/(landing)/')}(.+)$")
FRONTMATTER_SLUG = re.compile(
    r"\A---\n.*?^slug:\s*[\"']?([^\"'\n]+?)[\"']?\s*$.*?^---", re.M | re.S
)


@dataclass(frozen=True)
class Page:
    """One detail page: its route, its locale ("" for the default) and its slug."""

    route: str
    locale: str
    slug: str

    def url(self, site: str) -> str:
        return f"{self.hub(site)}/{self.slug}"

    def hub(self, site: str) -> str:
        return f"{site}{'/' + self.locale if self.locale else ''}{self.route}"


@dataclass
class Changes:
    touched: set[Page] = field(default_factory=set)
    removed: set[Page] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise SystemExit(f"indexnow: git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


@dataclass(frozen=True)
class Repo:
    root: Path
    previous: str
    head: str
    locales: tuple[str, ...]
    default_locale: str

    def show(self, rev: str, path: str) -> str:
        return git(self.root, "show", f"{rev}:{path}")

    def prefixes(self, localized: bool) -> list[str]:
        if not localized:
            return [""]
        return ["" if loc == self.default_locale else loc for loc in self.locales]


def read_locales(root: Path) -> tuple[tuple[str, ...], str]:
    """Read the locales and default locale src/i18n/config.ts declares."""
    text = (root / LOCALE_CONFIG).read_text()
    listed = re.search(r"export const locales = \[([^\]]*)\]", text)
    default = re.search(r'export const defaultLocale: Locale = "([^"]+)"', text)
    if not listed or not default:
        raise SystemExit(f"indexnow: cannot read locales / defaultLocale from {LOCALE_CONFIG}")
    return tuple(re.findall(r'"([^"]+)"', listed.group(1))), default.group(1)


def read_key(root: Path) -> str:
    """Read the one IndexNow key, served as public/<key>.txt holding the key itself."""
    files = sorted(p for p in (root / PUBLIC).iterdir() if KEY_FILE.match(p.name))
    if len(files) != 1:
        raise SystemExit(
            f"indexnow: expected exactly one key file {PUBLIC}/<32 hex>.txt, found {len(files)}"
        )
    key = files[0].stem
    if files[0].read_text().strip() != key:
        raise SystemExit(f"indexnow: key file {files[0].name} does not contain its own key")
    return key


def _json_at(repo: Repo, rev: str | None, path: str) -> object:
    return json.loads(repo.show(rev, path)) if rev else None


def _blog_slug(repo: Repo, rev: str | None, path: str, stem: str) -> str | None:
    if rev is None:
        return None
    match = FRONTMATTER_SLUG.search(repo.show(rev, path))
    return match.group(1) if match else stem


def _route_of(feature: str) -> tuple[str, bool]:
    if feature not in FAMILIES:
        raise SystemExit(f"indexnow: public/data/{feature} has no route; add it to FAMILIES")
    return FAMILIES[feature]


def _map_overlay(
    repo: Repo,
    changes: Changes,
    path: str,
    revs: tuple[str | None, str | None],
    feature: str,
    locale: str,
) -> None:
    if feature not in I18N_FEATURES:
        raise SystemExit(f"indexnow: {path} overlays no known feature; add it to I18N_FEATURES")
    if locale == repo.default_locale:
        return  # loadFeatureTranslations never reads the default locale's overlay
    if locale not in repo.locales:
        raise SystemExit(f"indexnow: {path} is for a locale {LOCALE_CONFIG} does not declare")
    route, _ = _route_of(I18N_FEATURES[feature])
    before = _json_at(repo, revs[0], path) or {}
    after = _json_at(repo, revs[1], path) or {}
    for slug in set(before) | set(after):
        if before.get(slug) != after.get(slug):
            changes.touched.add(Page(route, locale, slug))


def _map_data(
    repo: Repo,
    changes: Changes,
    path: str,
    revs: tuple[str | None, str | None],
    feature: str,
    slug: str,
) -> None:
    route, localized = _route_of(feature)
    prefixes = repo.prefixes(localized)
    if slug == SLUG_INDEX:
        before = set(_json_at(repo, revs[0], path) or [])
        after = set(_json_at(repo, revs[1], path) or [])
        changes.touched |= {Page(route, p, s) for s in after - before for p in prefixes}
        changes.removed |= {Page(route, p, s) for s in before - after for p in prefixes}
    else:
        (changes.removed if revs[1] is None else changes.touched).update(
            Page(route, p, slug) for p in prefixes
        )


def _map_blog(
    repo: Repo, changes: Changes, path: str, revs: tuple[str | None, str | None], stem: str
) -> None:
    route, _ = FAMILIES["blog"]
    before, after = _blog_slug(repo, revs[0], path, stem), _blog_slug(repo, revs[1], path, stem)
    if after:
        changes.touched.add(Page(route, "", after))
    if before and before != after:
        changes.removed.add(Page(route, "", before))


def _map_landing(changes: Changes, relative: str) -> None:
    segment, _, rest = relative.partition("/")
    if rest:
        changes.routes.add(f"/{segment}")
    elif segment == "page.tsx":
        changes.routes.add("")


def map_changes(repo: Repo, diff: list[tuple[str, str]]) -> Changes:
    """Map each changed file to the detail pages it renders, or the route family a template serves."""
    changes = Changes()
    for status, path in diff:
        revs = (None if status == "A" else repo.previous, None if status == "D" else repo.head)
        if match := I18N_FILE.match(path):
            _map_overlay(repo, changes, path, revs, *match.groups())
        elif match := DATA_FILE.match(path):
            _map_data(repo, changes, path, revs, *match.groups())
        elif match := BLOG_SOURCE.match(path):
            _map_blog(repo, changes, path, revs, match.group(1))
        elif match := LANDING_FILE.match(path):
            _map_landing(changes, match.group(1))
    return changes


def _route_path(url: str, site: str, locales: tuple[str, ...]) -> str:
    path = url[len(site) :].rstrip("/")
    for locale in locales:
        if path == f"/{locale}" or path.startswith(f"/{locale}/"):
            return path[len(locale) + 1 :]
    return path


def classify(changes: Changes, live: set[str], site: str, repo: Repo) -> tuple[set[str], set[str]]:
    """Split the changed pages into (updated, deleted) by whether the live sitemap still lists them."""
    updated = {p.url(site) for p in changes.touched | changes.removed if p.url(site) in live}
    deleted = {p.url(site) for p in changes.removed if p.url(site) not in live}
    for page in changes.touched | changes.removed:
        if page.url(site) in updated | deleted and page.hub(site) in live:
            updated.add(page.hub(site))
    for url in live:
        path = _route_path(url, site, repo.locales)
        if any(path == route or path.startswith(f"{route}/") for route in changes.routes):
            updated.add(url)
    return updated, deleted


def _github(path: str) -> dict[str, object]:
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    request = urllib.request.Request(  # noqa: S310 - the Actions API origin from the runner's own env
        f"{api}{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:  # noqa: S310 - see above
        return json.load(resp)


def last_deployed_sha() -> str:
    """Find the head SHA of the newest earlier run of this workflow whose deploy job succeeded."""
    for name in ("GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GH_TOKEN", "INDEXNOW_DEPLOY_JOB"):
        if not os.environ.get(name):
            raise SystemExit(f"indexnow: {name} is unset; pass --previous outside Actions")
    repo, job = os.environ["GITHUB_REPOSITORY"], os.environ["INDEXNOW_DEPLOY_JOB"]
    run_id = int(os.environ["GITHUB_RUN_ID"])
    workflow = _github(f"/repos/{repo}/actions/runs/{run_id}")["workflow_id"]
    page = 1
    while runs := _github(
        f"/repos/{repo}/actions/workflows/{workflow}/runs?branch={DEPLOY_BRANCH}&per_page=100&page={page}"
    )["workflow_runs"]:
        for run in runs:
            if run["id"] >= run_id:
                continue  # this run, and pushes queued behind it
            jobs = _github(
                f"/repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100"
            )
            if any(j["name"] == job and j["conclusion"] == "success" for j in jobs["jobs"]):
                return run["head_sha"]
        page += 1
    raise SystemExit(
        f"indexnow: no earlier {DEPLOY_BRANCH} run has a successful '{job}' job to diff from"
    )


def submit(endpoint: str, site: str, key: str, urls: list[str]) -> None:
    """POST the URLs in batches of BATCH_MAX; any non-2xx answer ends the run."""
    batches = [urls[i : i + BATCH_MAX] for i in range(0, len(urls), BATCH_MAX)]
    for n, batch in enumerate(batches, 1):
        body = {
            "host": urllib.parse.urlparse(site).netloc,
            "key": key,
            "keyLocation": f"{site}/{key}.txt",
            "urlList": batch,
        }
        request = urllib.request.Request(  # noqa: S310 - the IndexNow endpoint, https in CI
            endpoint,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:  # noqa: S310 - see above
                status = resp.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()
            raise SystemExit(
                f"indexnow: {endpoint} answered {exc.code} to batch {n}: {detail}"
            ) from exc
        print(f"indexnow: batch {n}/{len(batches)} ({len(batch)} URLs) accepted, HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--site", default="https://heygaia.io")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--previous", help="last deployed commit (default: from the Actions API)")
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--dry-run", action="store_true", help="print the URL list, post nothing")
    args = parser.parse_args()

    site = args.site.rstrip("/")
    key = read_key(args.repo)
    locales, default_locale = read_locales(args.repo)
    previous = args.previous or last_deployed_sha()
    head, previous = (git(args.repo, "rev-parse", rev).strip() for rev in (args.head, previous))
    repo = Repo(args.repo, previous, head, locales, default_locale)

    out = git(args.repo, "diff", "--name-status", "--no-renames", "-z", previous, head, "--", WEB)
    fields = out.split("\0")[:-1]
    diff = list(zip(fields[::2], fields[1::2], strict=True))
    changes = map_changes(repo, diff)
    live = set(sitemap_urls(Site(site, site), None))
    updated, deleted = classify(changes, live, site, repo)

    for url in sorted(updated):
        print(f"updated {url}")
    for url in sorted(deleted):
        print(f"deleted {url}")
    print(
        f"indexnow: {len(updated)} updated, {len(deleted)} deleted "
        f"({len(diff)} files changed in {previous[:7]}..{head[:7]})"
    )
    urls = sorted(updated | deleted)
    if args.dry_run or not urls:
        print(
            "indexnow: dry run, nothing submitted"
            if args.dry_run
            else "indexnow: nothing to submit"
        )
        return 0
    submit(args.endpoint, site, key, urls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
