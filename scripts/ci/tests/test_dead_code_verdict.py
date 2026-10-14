"""dead-code reports what it found, not that it failed.

The lane had `upload-verdict` but emitted nothing of its own, so a red
dead-code check reached `mise ci:remote` as "the lane failed and has not
adopted the verdict contract — its reason is only in this job's log", with
none of the file:line vulture and knip had just printed.

The real scan needs vulture, pnpm and the whole workspace, so the tools are
stubbed on PATH here: what is under test is the script's reporting, which is
the part that was missing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "dead-code-check.sh"

VULTURE_FINDINGS = (
    "apps/api/app/services/x.py:41: unused function 'never_called' (60% confidence)\n"
    "apps/api/app/utils/y.py:7: unreachable code after 'return' (100% confidence)\n"
)
KNIP_FINDINGS = "Unused files (1)\napps/web/src/dead.tsx\n\nUnused exports (1)\nfoo  apps/web/src/live.ts:12:3\n"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def run_scan(tmp_path: Path):
    """Drive the real script with stubbed vulture/pnpm and a private verdict dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    verdicts = tmp_path / "verdicts"

    def run(*, vulture: str, knip: str) -> tuple[subprocess.CompletedProcess[str], Path]:
        _stub(bin_dir, "vulture", f"cat <<'EOF'\n{vulture}EOF")
        # The script calls `pnpm exec knip …`; the stub ignores the argv and
        # exits 1 when it has findings, exactly as knip does.
        _stub(
            bin_dir, "pnpm", f"cat <<'EOF'\n{knip}EOF\n[ -n \"{knip.strip()}\" ] && exit 1\nexit 0"
        )
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": os.environ.get("HOME", "/tmp"),
            "GAIA_VERDICT_DIR": str(verdicts),
        }
        proc = subprocess.run(
            ["bash", str(SCRIPT), "--strict", "--verbose"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return proc, verdicts / "dead-code.json"

    return run


def test_a_red_scan_names_every_item_at_its_own_line(run_scan) -> None:
    proc, path = run_scan(vulture=VULTURE_FINDINGS, knip=KNIP_FINDINGS)

    assert proc.returncode == 1, proc.stdout
    doc = json.loads(path.read_text())
    assert doc["lane"] == "dead-code"
    assert doc["status"] == "fail"
    assert "unused item(s)" in doc["summary"]
    located = {(f["file"], f["line"]) for f in doc["findings"]}
    assert ("apps/api/app/services/x.py", 41) in located
    assert ("apps/api/app/utils/y.py", 7) in located
    # knip's bare path rows get line 1; its `path:line:col` rows keep the line.
    assert ("apps/web/src/dead.tsx", 1) in located
    assert ("apps/web/src/live.ts", 12) in located
    assert any("never_called" in f["message"] for f in doc["findings"])
    assert doc["advice"], "a failing lane with no remediation is a log to go read"


def test_a_clean_scan_reports_a_pass_rather_than_nothing(run_scan) -> None:
    """Silence is how a lane stops running without anybody noticing."""
    proc, path = run_scan(vulture="", knip="")

    assert proc.returncode == 0, proc.stdout
    doc = json.loads(path.read_text())
    assert doc["status"] == "pass"
    assert doc["findings"] == []


def test_the_annotation_count_is_capped_so_the_summary_survives(run_scan) -> None:
    many = "".join(
        f"apps/api/app/f{i}.py:{i + 1}: unused function 'g{i}' (60% confidence)\n"
        for i in range(80)
    )
    proc, path = run_scan(vulture=many, knip="")

    assert proc.returncode == 1
    doc = json.loads(path.read_text())
    assert len(doc["findings"]) == 50
    assert "80 unused item(s)" in doc["summary"], "the cap must not falsify the count"
