"""audit.sh: the standing dependency and pin gates.

`pnpm` allowlist and expiry handling, exercised with a stubbed pnpm.

The real registry is never contacted: a fake ``pnpm`` on PATH prints a canned
``pnpm audit --json`` report and exits 1 the way the real one does whenever it
found anything. What is under test is the gate logic: severity threshold,
CVE/GHSA matching, expiry, and that a broken audit is never a pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap

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
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "pnpm"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def summary(proc: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(proc.stdout[: proc.stdout.rindex("}") + 1])


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
