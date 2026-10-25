"""changes.sh: the diff every lane scopes itself to.

Driven against a real throwaway git repo — the script's whole job is git
plumbing, so stubbing git would test the stub.

Each test names a way the answer could be wrong in the direction that costs a
green PR on a broken tree:

* `files` must print `__FULL__` and nothing else on a push, or every scoped
  lane reports "no changed files — skipping" on the one branch that needs
  scanning;
* `docker-inputs` must notice `apps/api/Dockerfile.dockerignore`. It decides
  what enters the build CONTEXT, so a newly-excluded path drops out of the
  image — while the lane said "image inputs unchanged" and skipped the build.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
import yaml

CI = Path(__file__).resolve().parent.parent
SCRIPT = CI / "changes.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/tmp",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=GIT_ENV, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Return a repo with a `master` commit and a branch on top of it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    for rel in ("apps/api/Dockerfile", "apps/api/Dockerfile.dockerignore", ".dockerignore"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("base\n")
    (root / "app.py").write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    # A real `origin`: `docker-inputs` fetches it before diffing, so a repo with
    # only a remote-tracking ref would fail on the fetch rather than exercise
    # the diff.
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "master", str(origin)],
        check=True,
        env=GIT_ENV,
        capture_output=True,
    )
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "origin", "master")
    _git(root, "checkout", "-qb", "feature")
    return root


def _docker_inputs(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "gh_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "docker-inputs"],
        cwd=repo,
        env={**GIT_ENV, "BASE_BRANCH": "master", "GITHUB_OUTPUT": str(out)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text()


def test_a_dockerignore_change_rebuilds_the_image(repo: Path, tmp_path: Path) -> None:
    (repo / "apps/api/Dockerfile.dockerignore").write_text("base\n**/tests\n")
    _git(repo, "commit", "-aqm", "narrow the build context")
    assert "build=true" in _docker_inputs(repo, tmp_path)


def test_the_root_dockerignore_still_rebuilds_the_image(repo: Path, tmp_path: Path) -> None:
    (repo / ".dockerignore").write_text("base\nnode_modules\n")
    _git(repo, "commit", "-aqm", "root ignore")
    assert "build=true" in _docker_inputs(repo, tmp_path)


def test_an_unrelated_change_skips_the_build(repo: Path, tmp_path: Path) -> None:
    # The control: without this the test above would pass on a script that
    # answered build=true unconditionally.
    (repo / "app.py").write_text("x = 2\n")
    _git(repo, "commit", "-aqm", "unrelated")
    assert "build=false" in _docker_inputs(repo, tmp_path)


def _selfhost_inputs(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "gh_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "selfhost-inputs"],
        cwd=repo,
        env={**GIT_ENV, "BASE_BRANCH": "master", "GITHUB_OUTPUT": str(out)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return out.read_text()


def test_a_cli_change_runs_the_selfhost_e2e(repo: Path, tmp_path: Path) -> None:
    path = repo / "packages/cli/src/commands/up/flow.ts"
    path.parent.mkdir(parents=True)
    path.write_text("export {};\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "cli change")
    assert "build=true" in _selfhost_inputs(repo, tmp_path)


def test_a_selfhost_compose_change_runs_the_selfhost_e2e(repo: Path, tmp_path: Path) -> None:
    path = repo / "infra/docker/docker-compose.selfhost.yml"
    path.parent.mkdir(parents=True)
    path.write_text("services: {}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "compose change")
    assert "build=true" in _selfhost_inputs(repo, tmp_path)


def test_an_unrelated_change_skips_the_selfhost_e2e(repo: Path, tmp_path: Path) -> None:
    (repo / "app.py").write_text("x = 2\n")
    _git(repo, "commit", "-aqm", "unrelated")
    assert "build=false" in _selfhost_inputs(repo, tmp_path)


def test_files_prints_only_the_full_sentinel_on_a_push(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "files", "py"],
        cwd=repo,
        env={**GIT_ENV, "GITHUB_ACTIONS": "true", "GITHUB_BASE_REF": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    # Byte-for-byte: callers compare with `[ "$FILES" = "__FULL__" ]`.
    assert proc.stdout == "__FULL__\n"


def test_files_requires_an_extension(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "files"],
        cwd=repo,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2


def test_an_unknown_subcommand_exits_two(repo: Path) -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "nope"],
        cwd=repo,
        env=GIT_ENV,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# `base` — the branch this PR is REALLY based on.
#
# For a PR in a native GitHub stack the `pull_request` payload carries the
# stack's TRUNK in base.ref, not the PR's parent. Measured 2026-09-11 on
# #1161/#1202/#1175: `gh api pulls/N --jq .base.ref` named the parent for each
# while `github.base_ref` inside every job said `master`, from the morning's
# `gh stack link` onward. Every lane scopes to that value, so all three PRs
# linted, type-checked and mutated the entire stack — #1175's mutation plan
# took 119 modules for a one-module diff.
#
# The API is the only source that tells the truth, so the run asks it once and
# hands the answer down as $GAIA_PR_BASE.
# ---------------------------------------------------------------------------

TRUNK = "master"
PARENT = "feat/the-pr-below-this-one"


def _fake_gh(tmp_path: Path, stdout: str = "", exit_code: int = 0) -> str:
    """Put a `gh` that answers the pulls API on PATH and return the new PATH."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "{stdout}"\nexit {exit_code}\n')
    gh.chmod(0o755)
    return f"{bin_dir}:{GIT_ENV['PATH']}"


def _base(repo: Path, tmp_path: Path, path: str, **env: str) -> tuple[str, str]:
    out = tmp_path / "gh_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "base"],
        cwd=repo,
        env={
            **GIT_ENV,
            "PATH": path,
            "GITHUB_REPOSITORY": "theexperiencecompany/gaia",
            "GITHUB_OUTPUT": str(out),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip(), out.read_text()


def test_base_prefers_the_api_over_the_event_payload(repo: Path, tmp_path: Path) -> None:
    # The whole point: the payload says trunk, the API says parent, the parent
    # wins. Reversing this is the bug, and it is invisible — every lane just
    # quietly scopes to the bottom of the stack.
    resolved, _ = _base(
        repo,
        tmp_path,
        _fake_gh(tmp_path, PARENT),
        PR_NUMBER="1175",
        GITHUB_BASE_REF=TRUNK,
    )

    assert resolved == PARENT


def test_base_publishes_the_resolved_ref_as_a_job_output(repo: Path, tmp_path: Path) -> None:
    # Every downstream job reads it from here; without the output the resolver
    # has resolved nothing anyone can use.
    _, output = _base(
        repo,
        tmp_path,
        _fake_gh(tmp_path, PARENT),
        PR_NUMBER="1175",
        GITHUB_BASE_REF=TRUNK,
    )

    assert output.strip() == f"base_ref={PARENT}"


def test_base_falls_back_to_the_payload_when_there_is_no_pr(repo: Path, tmp_path: Path) -> None:
    # A push has no PR to ask about. The payload's base ref (empty on a push) is
    # then the answer, and `files` turns an empty one into the full-scan
    # sentinel exactly as it always has.
    resolved, _ = _base(repo, tmp_path, _fake_gh(tmp_path, PARENT), GITHUB_BASE_REF=TRUNK)

    assert resolved == TRUNK


def test_base_says_so_out_loud_when_the_api_call_fails(repo: Path, tmp_path: Path) -> None:
    # It falls back rather than failing the run — a GitHub API blip must not red
    # every PR — but the fallback is the WRONG base for a stacked PR, so it
    # cannot be silent. This is the one line that tells a reader why a lane
    # suddenly scoped to the whole stack.
    out = tmp_path / "gh_output"
    out.write_text("")
    proc = subprocess.run(
        ["bash", str(SCRIPT), "base"],
        cwd=repo,
        env={
            **GIT_ENV,
            "PATH": _fake_gh(tmp_path, "gh: HTTP 503", exit_code=1),
            "GITHUB_REPOSITORY": "theexperiencecompany/gaia",
            "GITHUB_OUTPUT": str(out),
            "PR_NUMBER": "1175",
            "GITHUB_BASE_REF": TRUNK,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "::warning::" in proc.stdout + proc.stderr
    assert proc.stdout.strip().endswith(TRUNK)


def test_files_scopes_to_the_resolved_base_not_the_payload(repo: Path) -> None:
    # The end-to-end shape of the bug, in one repo: a commit on the parent and a
    # commit of our own. Scoped to the payload (trunk) BOTH show up; scoped to
    # the resolved parent, only ours does.
    _git(repo, "checkout", "-q", "master")
    _git(repo, "checkout", "-qb", "parent")
    (repo / "from_the_pr_below.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the PR below this one")
    _git(repo, "push", "-q", "origin", "parent")
    _git(repo, "checkout", "-qb", "stacked")
    (repo / "ours.py").write_text("y = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "our one file")

    def files(**env: str) -> list[str]:
        proc = subprocess.run(
            ["bash", str(SCRIPT), "files", "py"],
            cwd=repo,
            env={**GIT_ENV, "GITHUB_ACTIONS": "true", **env},
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.split()

    assert files(GITHUB_BASE_REF="master") == ["from_the_pr_below.py", "ours.py"]
    assert files(GITHUB_BASE_REF="master", GAIA_PR_BASE="parent") == ["ours.py"]


# ---------------------------------------------------------------------------
# The merge queue: a merge_group run has no PR number and no GITHUB_BASE_REF.
# Its base is `merge_group.base_sha`, the commit the queued group was built on
# — for the second PR in the queue that is the FIRST PR's group commit, not
# master, so a branch name would charge it with the PR ahead of it.
# ---------------------------------------------------------------------------


def _rev(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        check=True,
        env=GIT_ENV,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _queue(repo: Path) -> str:
    """Build a group commit for the PR ahead in the queue and ours on top; return the one ahead."""
    _git(repo, "checkout", "-q", "master")
    _git(repo, "checkout", "-qb", "gh-readonly-queue/master/pr-1-aaaa")
    (repo / "ahead.py").write_text("a = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the PR ahead in the queue")
    ahead = _rev(repo, "HEAD")
    (repo / "ours.py").write_text("b = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "our PR")
    # GitHub holds every queue commit, so a fetch of the base sha succeeds there too.
    _git(repo, "push", "-q", "origin", "HEAD")
    return ahead


def _run(repo: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        env={**GIT_ENV, "GITHUB_ACTIONS": "true", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_base_on_a_merge_group_is_the_group_base_sha(repo: Path, tmp_path: Path) -> None:
    ahead = _queue(repo)

    resolved, output = _base(repo, tmp_path, _fake_gh(tmp_path, PARENT), MERGE_GROUP_BASE_SHA=ahead)

    assert resolved == ahead
    assert output.strip() == f"base_ref={ahead}"


def test_files_on_a_merge_group_is_only_this_prs_diff(repo: Path) -> None:
    ahead = _queue(repo)

    proc = _run(repo, "files", "py", GAIA_PR_BASE=ahead)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["ours.py"]


def test_base_rev_names_a_branch_by_its_remote_and_a_commit_as_itself(repo: Path) -> None:
    ahead = _queue(repo)

    assert _run(repo, "base-rev", GAIA_PR_BASE="master").stdout.strip() == "origin/master"
    assert _run(repo, "base-rev", GAIA_PR_BASE=ahead).stdout.strip() == ahead


def test_base_rev_refuses_a_base_it_cannot_resolve(repo: Path) -> None:
    proc = _run(repo, "base-rev", GAIA_PR_BASE="no-such-branch")

    assert proc.returncode != 0
    assert "no-such-branch" in proc.stderr


def test_docker_inputs_on_a_merge_group_diffs_against_the_group_base(
    repo: Path, tmp_path: Path
) -> None:
    ahead = _queue(repo)
    out = tmp_path / "gh_output"
    out.write_text("")

    proc = _run(repo, "docker-inputs", BASE_BRANCH=ahead, GITHUB_OUTPUT=str(out))

    assert proc.returncode == 0, proc.stderr
    assert "build=false" in out.read_text()


# ---------------------------------------------------------------------------
# web-inputs: deploy-web's build is a required pre-merge check, so it runs on
# every PR and decides for itself whether the bundle's inputs moved.
# ---------------------------------------------------------------------------


def _web_inputs(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "web_output"
    out.write_text("")
    proc = _run(repo, "web-inputs", BASE_BRANCH="master", GITHUB_OUTPUT=str(out))
    assert proc.returncode == 0, proc.stderr
    return out.read_text()


def test_a_web_change_builds_the_bundle(repo: Path, tmp_path: Path) -> None:
    (repo / "apps/web").mkdir(parents=True)
    (repo / "apps/web/page.tsx").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "web")
    assert "build=true" in _web_inputs(repo, tmp_path)


def test_a_change_outside_the_web_inputs_skips_the_bundle(repo: Path, tmp_path: Path) -> None:
    (repo / "app.py").write_text("x = 3\n")
    _git(repo, "commit", "-aqm", "api only")
    assert "build=false" in _web_inputs(repo, tmp_path)


def test_web_inputs_match_the_deploy_trigger() -> None:
    # The push trigger and the pre-merge decision must agree, or the merge queue
    # passes a web change that master then deploys untested — or the reverse.
    workflow = yaml.safe_load((CI.parent.parent / ".github/workflows/deploy-web.yml").read_text())
    triggers = workflow[True] if True in workflow else workflow["on"]
    script = SCRIPT.read_text()
    body = script[script.index("WEB_INPUTS=(") :]
    listed = [line.strip() for line in body[: body.index(")")].splitlines()[1:] if line.strip()]
    expected = [p if p.endswith(".yml") else f"{p}/**" for p in listed]
    assert triggers["push"]["paths"] == expected


# ---------------------------------------------------------------------------
# desktop-inputs: desktop-pr-build runs on every PR and merge group and decides
# for itself whether the packaged app's inputs moved, so a merge group that
# touches no desktop path skips in seconds instead of packaging three OSes.
# ---------------------------------------------------------------------------


def _desktop_inputs(repo: Path, tmp_path: Path) -> str:
    out = tmp_path / "desktop_output"
    out.write_text("")
    proc = _run(repo, "desktop-inputs", BASE_BRANCH="master", GITHUB_OUTPUT=str(out))
    assert proc.returncode == 0, proc.stderr
    return out.read_text()


def _commit(repo: Path, rel: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", rel)


@pytest.mark.parametrize(
    "rel",
    [
        "apps/desktop/src/main.ts",
        "libs/shared/ts/src/bots/x.ts",
        ".github/workflows/desktop-pr-build.yml",
    ],
)
def test_a_desktop_input_change_packages_the_app(repo: Path, tmp_path: Path, rel: str) -> None:
    _commit(repo, rel)
    assert "build=true" in _desktop_inputs(repo, tmp_path)


@pytest.mark.parametrize(
    "rel", ["apps/web/page.tsx", "libs/shared/ts/src/api/generated/schema.d.ts"]
)
def test_a_change_the_packaged_app_cannot_see_skips_it(
    repo: Path, tmp_path: Path, rel: str
) -> None:
    _commit(repo, rel)
    assert "build=false" in _desktop_inputs(repo, tmp_path)
