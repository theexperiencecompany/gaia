"""deploy.sh verify-alert-rules: the running Grafana image carries exactly the rules the repo declares.

``docker`` is a fake on PATH: ``ps`` names a grafana container and ``exec``
prints the rules file that container was built with. The comparison is real.
Regression for the image that shipped 25 stale rules while the repo declared 37.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).parent.parent / "deploy.sh"

DOCKER_STUB = """\
#!/usr/bin/env bash
case "$*" in
  *" ps -q "*) echo cid1 ;;
  *" exec cid1 "*) cat "$STATE/shipped.yaml" ;;
  *) echo "unexpected docker call: $*" >&2; exit 1 ;;
esac
"""


def _rules_file(uids: list[str]) -> str:
    return "apiVersion: 1\ngroups:\n  - name: g\n    rules:\n" + "".join(
        f"      - uid: {uid}\n        datasourceUid: prometheus\n" for uid in uids
    )


def _verify(
    tmp_path: Path, declared: list[str], served: list[str]
) -> subprocess.CompletedProcess[str]:
    rules = tmp_path / "alert-rules.yaml"
    rules.write_text(_rules_file(declared))
    (tmp_path / "shipped.yaml").write_text(_rules_file(served))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), "verify-alert-rules"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "STATE": str(tmp_path),
            "ALERT_RULES_FILE": str(rules),
            "GRAFANA_VERIFY_TIMEOUT_SECS": "0",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_equal_sets_pass(tmp_path: Path) -> None:
    result = _verify(tmp_path, ["a", "b"], ["b", "a"])
    assert result.returncode == 0, result.stderr
    assert "exactly the 2 rules" in result.stdout


def test_uid_missing_from_grafana_fails(tmp_path: Path) -> None:
    result = _verify(tmp_path, ["a", "b", "c"], ["a"])
    assert result.returncode == 1
    assert "missing b, missing c" in result.stderr
    assert "extra" not in result.stderr.split("rules than")[-1]


def test_extra_uid_in_grafana_fails(tmp_path: Path) -> None:
    result = _verify(tmp_path, ["a"], ["a", "stale"])
    assert result.returncode == 1
    assert "extra stale" in result.stderr
