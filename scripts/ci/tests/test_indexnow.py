"""IndexNow submission, run for real over a throwaway git repo and a local site + API."""

from __future__ import annotations

from collections.abc import Iterator
import json
import os
from pathlib import Path
import subprocess
import sys

from http_stub import Routes, serve
import pytest

INDEXNOW = Path(__file__).resolve().parents[1] / "lib" / "indexnow.py"
KEY = "0123456789abcdef0123456789abcdef"
LANDING = "apps/web/src/app/[locale]/(landing)"
LOCALE_CONFIG = (
    'export const locales = ["en", "de"] as const;\nexport const defaultLocale: Locale = "en";\n'
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(repo: Path, files: dict[str, str | None]) -> str:
    """Apply files (None deletes) and commit; return the new commit's SHA."""
    for rel, content in files.items():
        path = repo / rel
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(
        root,
        {
            f"apps/web/public/{KEY}.txt": KEY,
            "apps/web/src/i18n/config.ts": LOCALE_CONFIG,
            "apps/web/public/data/comparisons/_slugs.json": '["a", "b", "c", "d"]',
            "apps/web/public/data/comparisons/a.json": '{"name": "A"}',
            "apps/web/public/data/comparisons/b.json": '{"name": "B"}',
            "apps/web/public/data/comparisons/c.json": '{"name": "C"}',
            "apps/web/public/data/comparisons/d.json": '{"name": "D"}',
            "apps/web/public/data/comparisons/victim.json": '{"name": "V"}',
            "apps/web/public/data/i18n/comparisons/de.json": '{"c": {"name": "C"}}',
            "apps/web/public/data/i18n/comparisons/en.json": '{"c": {"name": "C"}}',
            "apps/web/public/data/personas/_slugs.json": '["z"]',
            "apps/web/public/data/personas/z.json": '{"name": "Z"}',
            "apps/web/content/blog/README.md": "# how to write a post",
            "apps/web/content/blog/launch.mdx": "---\nslug: launch\n---\nBody",
            f"{LANDING}/learn/[slug]/page.tsx": "export default 1;",
            f"{LANDING}/layout.tsx": "export default 1;",
        },
    )
    return root


def _shipped(repo: Path) -> tuple[str, str]:
    """One deploy's worth of change: every mapping rule fires once."""
    previous = _git(repo, "rev-parse", "HEAD")
    head = _write(
        repo,
        {
            "apps/web/public/data/comparisons/a.json": '{"name": "A2"}',
            "apps/web/public/data/comparisons/b.json": None,
            "apps/web/public/data/comparisons/_slugs.json": '["a", "c"]',
            "apps/web/public/data/comparisons/victim.json": '{"name": "V2"}',
            "apps/web/public/data/i18n/comparisons/de.json": '{"c": {"name": "C-de"}}',
            "apps/web/public/data/i18n/comparisons/en.json": '{"c": {"name": "C-en"}}',
            "apps/web/content/blog/hello-world.mdx": '---\ntitle: "Hi"\nslug: "hello"\n---\nBody',
            "apps/web/content/blog/README.md": "# how to write a post, revised",
            "apps/web/content/blog/launch.mdx": "---\nslug: launch-day\n---\nBody",
            f"{LANDING}/learn/[slug]/page.tsx": "export default 2;",
            f"{LANDING}/layout.tsx": "export default 2;",
        },
    )
    return previous, head


LIVE_PATHS = [
    "/compare",
    "/de/compare",
    "/compare/a",
    "/de/compare/a",
    "/compare/c",
    "/de/compare/c",
    "/for",
    "/for/z",
    "/de/for/z",
    "/blog",
    "/blog/hello",
    "/blog/launch-day",
    "/learn",
    "/de/learn",
    "/learn/x",
    "/de/learn/x",
    "/learnings",
]


def _sitemap(base: str, paths: list[str]) -> Routes:
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in paths)
    index = f"<sitemapindex><sitemap><loc>{base}/sitemap/0.xml</loc></sitemap></sitemapindex>"
    return {
        "/sitemap.xml": (200, {}, index),
        "/sitemap/0.xml": (200, {}, f"<urlset>{urls}</urlset>"),
    }


def _run(
    repo: Path, base: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(INDEXNOW), "--repo", str(repo), "--site", base, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, **(env or {})},
    )


def _listed(stdout: str, kind: str, base: str) -> set[str]:
    prefix = f"{kind} {base}"
    return {line[len(prefix) :] for line in stdout.splitlines() if line.startswith(prefix)}


@pytest.fixture
def site() -> Iterator[tuple[str, Routes, list[tuple[str, bytes]]]]:
    routes: Routes = {}
    posts: list[tuple[str, bytes]] = []
    with serve(routes, posts) as base:
        routes.update(_sitemap(base, LIVE_PATHS))
        routes["/indexnow"] = (202, {}, "")
        yield base, routes, posts


def test_maps_each_changed_file_to_the_pages_it_renders(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, _routes, posts = site
    previous, head = _shipped(repo)

    result = _run(repo, base, "--previous", previous, "--head", head, "--dry-run")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _listed(result.stdout, "updated", base) == {
        "/compare",
        "/de/compare",
        "/compare/a",
        "/de/compare/a",
        "/de/compare/c",
        "/blog",
        "/blog/hello",
        "/blog/launch-day",
        "/learn",
        "/de/learn",
        "/learn/x",
        "/de/learn/x",
    }
    assert _listed(result.stdout, "deleted", base) == {
        "/compare/b",
        "/de/compare/b",
        "/compare/d",
        "/de/compare/d",
        "/blog/launch",
    }
    assert posts == []


def test_posts_the_list_with_the_key_the_site_serves(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, _routes, posts = site
    previous, head = _shipped(repo)

    result = _run(
        repo, base, "--previous", previous, "--head", head, "--endpoint", f"{base}/indexnow"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    [(path, raw)] = posts
    body = json.loads(raw)
    assert path == "/indexnow"
    assert body["host"] == base.removeprefix("http://")
    assert body["key"] == KEY
    assert body["keyLocation"] == f"{base}/{KEY}.txt"
    assert len(body["urlList"]) == 17
    assert f"{base}/compare/b" in body["urlList"]


def test_nothing_changed_posts_nothing(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, _routes, posts = site
    head = _git(repo, "rev-parse", "HEAD")

    result = _run(repo, base, "--previous", head, "--head", head, "--endpoint", f"{base}/indexnow")

    assert result.returncode == 0, result.stdout + result.stderr
    assert posts == []


def test_a_rejected_submission_fails_the_run(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, routes, _posts = site
    routes["/indexnow"] = (422, {}, "URLs don't belong to the host")
    previous, head = _shipped(repo)

    result = _run(
        repo, base, "--previous", previous, "--head", head, "--endpoint", f"{base}/indexnow"
    )

    assert result.returncode != 0
    assert "422" in result.stderr


def test_splits_more_than_ten_thousand_urls_into_batches(repo: Path) -> None:
    previous = _git(repo, "rev-parse", "HEAD")
    head = _write(repo, {f"{LANDING}/learn/[slug]/page.tsx": "export default 3;"})
    posts: list[tuple[str, bytes]] = []
    routes: Routes = {"/indexnow": (200, {}, "")}
    with serve(routes, posts) as base:
        routes.update(_sitemap(base, ["/learn", *(f"/learn/t{i}" for i in range(10_000))]))
        result = _run(
            repo, base, "--previous", previous, "--head", head, "--endpoint", f"{base}/indexnow"
        )

    assert result.returncode == 0, result.stdout + result.stderr
    sizes = [len(json.loads(raw)["urlList"]) for _path, raw in posts]
    assert sizes == [10_000, 1]


def test_fails_without_exactly_one_key_file(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, _routes, _posts = site
    previous, head = _shipped(repo)
    (repo / f"apps/web/public/{'f' * 32}.txt").write_text("f" * 32)

    result = _run(repo, base, "--previous", previous, "--head", head, "--dry-run")

    assert result.returncode != 0
    assert "key file" in result.stderr


def _github(repo: str, run_id: int, runs: list[tuple[int, str, str]]) -> Routes:
    """Serve the Actions API for one workflow; runs are (id, head_sha, deploy job conclusion), newest first."""
    api = f"/repos/{repo}/actions"
    routes: Routes = {
        f"{api}/runs/{run_id}": (200, {}, json.dumps({"id": run_id, "workflow_id": 7})),
        f"{api}/workflows/7/runs?branch=master&per_page=100&page=1": (
            200,
            {},
            json.dumps({"workflow_runs": [{"id": i, "head_sha": sha} for i, sha, _ in runs]}),
        ),
        f"{api}/workflows/7/runs?branch=master&per_page=100&page=2": (
            200,
            {},
            json.dumps({"workflow_runs": []}),
        ),
    }
    for run, _sha, conclusion in runs:
        jobs = [
            {"name": "build (cf:build)", "conclusion": "success"},
            {"name": "deploy (production)", "conclusion": conclusion},
        ]
        routes[f"{api}/runs/{run}/jobs?filter=latest&per_page=100"] = (
            200,
            {},
            json.dumps({"jobs": jobs}),
        )
    return routes


def _actions_env(api: str, run_id: int) -> dict[str, str]:
    return {
        "GITHUB_API_URL": api,
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": str(run_id),
        "GH_TOKEN": "t",
        "INDEXNOW_DEPLOY_JOB": "deploy (production)",
    }


def test_previous_is_the_last_run_whose_deploy_job_succeeded(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, routes, _posts = site
    previous, head = _shipped(repo)
    coalesced = _write(repo, {"apps/web/public/data/personas/z.json": '{"name": "Z2"}'})
    head = _write(repo, {"apps/web/public/data/personas/z.json": '{"name": "Z3"}'})
    # This run (30); 29 was cancelled by a newer queued push before it deployed;
    # 28 deployed but its seo-audit went red, so the run itself failed.
    routes.update(
        _github(
            "o/r",
            30,
            [(30, head, "success"), (29, coalesced, "cancelled"), (28, previous, "success")],
        )
    )

    result = _run(repo, base, "--head", head, "--dry-run", env=_actions_env(base, 30))

    assert result.returncode == 0, result.stdout + result.stderr
    updated = _listed(result.stdout, "updated", base)
    assert {"/compare/a", "/for/z", "/de/for/z", "/for"} <= updated


def test_no_earlier_successful_deploy_fails_the_run(
    repo: Path, site: tuple[str, Routes, list[tuple[str, bytes]]]
) -> None:
    base, routes, _posts = site
    _previous, head = _shipped(repo)
    routes.update(_github("o/r", 30, [(30, head, "success"), (29, "dead" * 10, "skipped")]))

    result = _run(repo, base, "--head", head, "--dry-run", env=_actions_env(base, 30))

    assert result.returncode != 0
    assert "deploy (production)" in result.stderr
