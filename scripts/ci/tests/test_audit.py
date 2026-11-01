"""audit.sh: the standing dependency and pin gates.

`pnpm` allowlist and expiry handling, exercised with a stubbed pnpm; `pip`
with a stubbed uv and pip-audit. Both are also exercised at the `introduced`
scope a PR push and the merge queue run at, against a real throwaway git repo
whose base lockfile already ships some of the vulnerable versions.

The real registry is never contacted: a fake ``pnpm`` on PATH prints a canned
``pnpm audit --json`` report and exits 1 the way the real one does whenever it
found anything. What is under test is the gate logic: severity threshold,
CVE/GHSA matching, expiry, and that a broken audit is never a pass.

`uv-lock` runs the real uv offline against throwaway git repos holding a root
project and a standalone nested one, so discovery and staleness are both real.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap
from typing import Any

from doc_shape import mapping
import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "audit.sh"


def advisory(num: int, module: str, severity: str, cves: list[str]) -> dict:
    return {
        "github_advisory_id": f"GHSA-{num:04d}-aaaa-bbbb",
        "module_name": module,
        "severity": severity,
        "cves": cves,
        "vulnerable_versions": "<1.0.0",
        "patched_versions": ">=1.0.0",
        "url": f"https://github.com/advisories/GHSA-{num:04d}-aaaa-bbbb",
        "findings": [{"version": "0.9.0", "paths": [f"gaia>{module}"]}],
    }


REPORT = {
    "actions": [],
    "advisories": {
        "1": advisory(1, "undici", "high", ["CVE-2026-0001"]),
        "2": advisory(2, "axios", "moderate", []),
        "3": advisory(3, "sharp", "critical", []),
    },
    "metadata": {"vulnerabilities": {"high": 1, "moderate": 1, "critical": 1}},
}


def run(
    tmp_path: Path,
    *,
    allow: list[dict] | None,
    stdout: str | None = None,
    today: str = "2026-08-29",
    level: str = "high",
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    body = json.dumps(REPORT) if stdout is None else stdout
    (tmp_path / "audit.out").write_text(body)
    pnpm = stub / "pnpm"
    pnpm.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        cat "{tmp_path / "audit.out"}"
        exit 1
        """)
    )
    pnpm.chmod(0o755)
    allowlist = tmp_path / "allow.json"
    if allow is not None:
        allowlist.write_text(json.dumps({"allow": allow}))
    env = {
        "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "PNPM_AUDIT_ALLOWLIST": str(allowlist),
        "PNPM_AUDIT_TODAY": today,
        "PNPM_AUDIT_LEVEL": level,
        **extra_env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "pnpm"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def summary(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return mapping(json.loads(proc.stdout[: proc.stdout.rindex("}") + 1]))


def test_unallowlisted_findings_at_or_above_level_fail(tmp_path: Path) -> None:
    proc = run(tmp_path, allow=[])
    assert proc.returncode == 1, proc.stderr
    out = summary(proc)
    assert out["failing"] == 2  # high undici + critical sharp; moderate axios is below the bar
    assert {f["module"] for f in out["details"]["failing"]} == {"undici", "sharp"}
    assert "CVE-2026-0001" in proc.stderr


def test_level_is_a_threshold_not_an_exact_match(tmp_path: Path) -> None:
    proc = run(tmp_path, allow=[], level="critical")
    assert proc.returncode == 1
    assert {f["module"] for f in summary(proc)["details"]["failing"]} == {"sharp"}
    proc = run(tmp_path, allow=[], level="moderate")
    assert summary(proc)["failing"] == 3


def test_allowlisted_by_cve_and_by_ghsa_passes(tmp_path: Path) -> None:
    allow = [
        {
            "id": "CVE-2026-0001",
            "reason": "server-side only, not reachable",
            "expires": "2026-12-31",
        },
        {"id": "GHSA-0003-aaaa-bbbb", "reason": "build-time only", "expires": "2026-09-30"},
    ]
    proc = run(tmp_path, allow=allow)
    assert proc.returncode == 0, proc.stderr
    out = summary(proc)
    assert out["failing"] == 0
    assert out["suppressed"] == 2
    assert {s["allowlisted_by"] for s in out["details"]["suppressed"]} == {
        "CVE-2026-0001",
        "GHSA-0003-aaaa-bbbb",
    }
    assert "pnpm-audit: OK" in proc.stdout


def test_entry_expiring_today_is_still_valid(tmp_path: Path) -> None:
    allow = [
        {"id": "CVE-2026-0001", "reason": "r", "expires": "2026-08-29"},
        {"id": "GHSA-0003-aaaa-bbbb", "reason": "r", "expires": "2026-08-29"},
    ]
    assert run(tmp_path, allow=allow, today="2026-08-29").returncode == 0


def test_expired_entry_fails_even_when_it_still_matches(tmp_path: Path) -> None:
    allow = [
        {"id": "CVE-2026-0001", "reason": "r", "expires": "2026-08-01"},
        {"id": "GHSA-0003-aaaa-bbbb", "reason": "r", "expires": "2026-12-31"},
    ]
    proc = run(tmp_path, allow=allow, today="2026-08-29")
    assert proc.returncode == 1
    out = summary(proc)
    assert out["expired"] == 1
    assert out["failing"] == 1  # the expired entry no longer suppresses undici
    assert "expired on 2026-08-01" in proc.stderr


def test_unused_entry_only_warns(tmp_path: Path) -> None:
    allow = [
        {"id": "CVE-2026-0001", "reason": "r", "expires": "2026-12-31"},
        {"id": "GHSA-0003-aaaa-bbbb", "reason": "r", "expires": "2026-12-31"},
        {"id": "CVE-2020-9999", "reason": "long fixed", "expires": "2026-12-31"},
    ]
    proc = run(tmp_path, allow=allow)
    assert proc.returncode == 0, proc.stderr
    assert summary(proc)["unused_allowlist"] == ["CVE-2020-9999"]
    assert "::warning::" in proc.stderr


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "CVE-2026-0001", "expires": "2026-12-31"},  # no reason
        {"id": "CVE-2026-0001", "reason": "r"},  # no expiry
        {"id": "CVE-2026-0001", "reason": "r", "expires": "someday"},
        {"id": "undici", "reason": "r", "expires": "2026-12-31"},  # not a CVE/GHSA id
    ],
)
def test_malformed_allowlist_is_a_hard_error(tmp_path: Path, entry: dict) -> None:
    proc = run(tmp_path, allow=[entry])
    assert proc.returncode == 2
    assert "malformed allowlist" in proc.stderr


def test_missing_allowlist_is_a_hard_error(tmp_path: Path) -> None:
    proc = run(tmp_path, allow=None)
    assert proc.returncode == 2
    assert "allowlist not found" in proc.stderr


def test_registry_failure_is_never_a_pass(tmp_path: Path) -> None:
    proc = run(tmp_path, allow=[], stdout="ERR_PNPM_AUDIT_ENDPOINT_NOT_EXISTS\n")
    assert proc.returncode == 2
    assert "no usable report" in proc.stderr


# ---------------------------------------------------------------------------
# AUDIT_SCOPE=introduced — a PR fails only on what it put in the lockfile.
#
# 38% of the red PR rounds sampled over 30 days were infra or external, and six
# of those were an advisory published overnight against a version master
# already shipped: the PR could not have caused it and could not fix it without
# a dependency bump that does not belong in it. Master still fails on it.
# ---------------------------------------------------------------------------

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


def _repo(tmp_path: Path, name: str, base: str, head: str) -> tuple[Path, str]:
    """Return a repo whose base commit has lockfile `base` and HEAD has `head`, and the base sha."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / name).write_text(base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    sha = _git(repo, "rev-parse", "HEAD")
    (repo / name).write_text(head)
    _git(repo, "commit", "-qam", "the change", "--allow-empty")
    return repo, sha


def _pnpm_lock(*packages: str) -> str:
    # The overrides section uses the same indent; it must not count as packages.
    return "lockfileVersion: '9.0'\n\noverrides:\n  sharp@<1.0.0: 1.0.0\n\npackages:\n\n" + "".join(
        f"  {pkg}:\n    resolution: {{}}\n\n" for pkg in packages
    )


def test_introduced_scope_fails_only_on_a_version_the_change_added(tmp_path: Path) -> None:
    # undici@0.9.0 shipped on the base already; sharp@0.9.0 is new in this change.
    repo, base = _repo(
        tmp_path,
        "pnpm-lock.yaml",
        _pnpm_lock("undici@0.9.0", "axios@0.9.0"),
        _pnpm_lock("undici@0.9.0", "axios@0.9.0", "sharp@0.9.0"),
    )

    proc = run(
        tmp_path, allow=[], AUDIT_SCOPE="introduced", PNPM_AUDIT_ROOT=str(repo), GAIA_PR_BASE=base
    )

    assert proc.returncode == 1, proc.stderr
    out = summary(proc)
    assert out["scope"] == "introduced"
    assert [f["module"] for f in out["details"]["failing"]] == ["sharp"]
    assert [f["module"] for f in out["details"]["preexisting"]] == ["undici"]
    assert "::warning::pnpm-audit: high undici" in proc.stderr


def test_introduced_scope_passes_when_every_advisory_predates_the_change(tmp_path: Path) -> None:
    lock = _pnpm_lock("undici@0.9.0", "sharp@0.9.0")
    repo, base = _repo(tmp_path, "pnpm-lock.yaml", lock, lock + "\n")

    proc = run(
        tmp_path, allow=[], AUDIT_SCOPE="introduced", PNPM_AUDIT_ROOT=str(repo), GAIA_PR_BASE=base
    )

    assert proc.returncode == 0, proc.stderr
    assert summary(proc)["preexisting"] == 2


def test_the_default_scope_still_fails_on_every_advisory(tmp_path: Path) -> None:
    # Master and dispatch runs set no scope: a pre-existing advisory reds them.
    lock = _pnpm_lock("undici@0.9.0", "sharp@0.9.0")
    repo, base = _repo(tmp_path, "pnpm-lock.yaml", lock, lock)

    proc = run(tmp_path, allow=[], PNPM_AUDIT_ROOT=str(repo), GAIA_PR_BASE=base)

    assert proc.returncode == 1
    assert summary(proc)["failing"] == 2


def test_an_unknown_scope_is_a_hard_error(tmp_path: Path) -> None:
    assert run(tmp_path, allow=[], AUDIT_SCOPE="introduce").returncode == 2


def test_an_unresolvable_base_is_a_hard_error_not_a_pass(tmp_path: Path) -> None:
    lock = _pnpm_lock("sharp@0.9.0")
    repo, _ = _repo(tmp_path, "pnpm-lock.yaml", lock, lock)

    proc = run(
        tmp_path,
        allow=[],
        AUDIT_SCOPE="introduced",
        PNPM_AUDIT_ROOT=str(repo),
        GAIA_PR_BASE="no-such-branch",
    )

    assert proc.returncode == 2


# --- pip --------------------------------------------------------------------


def _uv_lock(*packages: tuple[str, str]) -> str:
    return "version = 1\n\n" + "".join(
        f'[[package]]\nname = "{name}"\nversion = "{version}"\n\n' for name, version in packages
    )


def _pip(
    tmp_path: Path, report: dict | None, *, exit_code: int = 1, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run `audit.sh pip` with uv stubbed: its pip-audit run writes `report` where -o points."""
    stub = tmp_path / "pipbin"
    stub.mkdir(exist_ok=True)
    (tmp_path / "pip-report.json").write_text("" if report is None else json.dumps(report))
    # One uv for both calls: `uv export -o` gets an empty lock export, `uv run … pip-audit -o` the report.
    (stub / "uv").write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        case " $* " in *" pip-audit "*) audit=1 ;; *) audit=0 ;; esac
        while [ "$#" -gt 0 ]; do
          if [ "$1" = -o ]; then
            if [ "$audit" = 1 ]; then cp "{tmp_path / "pip-report.json"}" "$2"; else : > "$2"; fi
          fi
          shift
        done
        [ "$audit" = 1 ] && exit {exit_code}
        exit 0
        """)
    )
    (stub / "uv").chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), "pip"],
        env={
            "PATH": f"{stub}{os.pathsep}{os.environ['PATH']}",
            "HOME": os.environ.get("HOME", "/tmp"),
            "RUNNER_TEMP": str(tmp_path),
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


PIP_REPORT = {
    "dependencies": [
        {
            "name": "aiohttp",
            "version": "3.9.0",
            "vulns": [{"id": "PYSEC-1", "fix_versions": ["3.9.4"]}],
        },
        {"name": "Pillow", "version": "10.0.0", "vulns": [{"id": "GHSA-2", "fix_versions": []}]},
        {"name": "six", "version": "1.16.0", "vulns": []},
    ]
}


def test_pip_fails_on_any_advisory_by_default(tmp_path: Path) -> None:
    proc = _pip(tmp_path, PIP_REPORT, PIP_AUDIT_ROOT=str(tmp_path))

    assert proc.returncode == 1
    assert "aiohttp 3.9.0 PYSEC-1" in proc.stdout
    assert "Pillow 10.0.0 GHSA-2" in proc.stdout


def test_pip_introduced_scope_warns_on_what_the_base_already_ships(tmp_path: Path) -> None:
    # pillow is the base's (spelled differently in the lock: names normalise);
    # aiohttp 3.9.0 is this change's downgrade.
    repo, base = _repo(
        tmp_path,
        "uv.lock",
        _uv_lock(("aiohttp", "3.9.5"), ("pillow", "10.0.0")),
        _uv_lock(("aiohttp", "3.9.0"), ("pillow", "10.0.0")),
    )

    proc = _pip(
        tmp_path, PIP_REPORT, AUDIT_SCOPE="introduced", PIP_AUDIT_ROOT=str(repo), GAIA_PR_BASE=base
    )

    assert proc.returncode == 1, proc.stderr
    assert "::error::pip-audit: aiohttp 3.9.0 PYSEC-1" in proc.stdout
    assert "::warning::pip-audit: Pillow 10.0.0 GHSA-2" in proc.stdout


def test_pip_introduced_scope_passes_when_nothing_is_new(tmp_path: Path) -> None:
    lock = _uv_lock(("aiohttp", "3.9.0"), ("pillow", "10.0.0"))
    repo, base = _repo(tmp_path, "uv.lock", lock, lock + "\n")

    proc = _pip(
        tmp_path, PIP_REPORT, AUDIT_SCOPE="introduced", PIP_AUDIT_ROOT=str(repo), GAIA_PR_BASE=base
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("::warning::") == 2


def test_pip_with_no_report_is_never_a_pass(tmp_path: Path) -> None:
    proc = _pip(tmp_path, None, PIP_AUDIT_ROOT=str(tmp_path))

    assert proc.returncode == 2
    assert "no usable report" in proc.stderr


def test_pip_failing_with_nothing_to_show_is_an_error(tmp_path: Path) -> None:
    # --strict exits 1 when a dependency could not be audited, with no vulns at all.
    proc = _pip(tmp_path, {"dependencies": []}, PIP_AUDIT_ROOT=str(tmp_path))

    assert proc.returncode == 2


def test_pip_clean_report_passes(tmp_path: Path) -> None:
    proc = _pip(tmp_path, {"dependencies": []}, exit_code=0, PIP_AUDIT_ROOT=str(tmp_path))

    assert proc.returncode == 0, proc.stderr


def write_project(directory: Path, name: str, dependencies: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").write_text(
        textwrap.dedent(f"""\
        [project]
        name = "{name}"
        version = "0.1.0"
        requires-python = ">=3.12"
        dependencies = {json.dumps(dependencies)}
        """)
    )


@pytest.fixture
def uv_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    write_project(repo, "root-project", [])
    write_project(repo / "libs" / "standalone", "standalone-project", [])
    env = {**os.environ, "UV_OFFLINE": "1"}
    for directory in (repo, repo / "libs" / "standalone"):
        subprocess.run(["uv", "lock", "--project", str(directory)], env=env, check=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def run_uv_lock(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "uv-lock"],
        env={**os.environ, "UV_LOCK_ROOT": str(repo), "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_uv_lock_passes_when_every_lockfile_is_current(uv_repo: Path) -> None:
    proc = run_uv_lock(uv_repo)
    assert proc.returncode == 0, proc.stderr
    assert "uv-lock: OK (2 lockfiles current)" in proc.stdout


def test_uv_lock_fails_on_a_nested_project_that_no_longer_resolves(uv_repo: Path) -> None:
    write_project(uv_repo / "libs" / "standalone", "standalone-project", ["no-such-dist-gaia"])
    proc = run_uv_lock(uv_repo)
    assert proc.returncode == 1
    assert "uv-lock: libs/standalone:" in proc.stderr


def test_uv_lock_fails_when_the_root_lock_is_stale(uv_repo: Path) -> None:
    pyproject = uv_repo / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace("0.1.0", "0.2.0"))
    proc = run_uv_lock(uv_repo)
    assert proc.returncode == 1
    assert "uv-lock: .:" in proc.stderr


def test_uv_lock_with_no_tracked_lockfile_is_an_error(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = run_uv_lock(tmp_path)
    assert proc.returncode == 1
    assert "no tracked uv.lock" in proc.stderr
