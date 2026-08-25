#!/usr/bin/env python3
"""Fault-injection tests for scripts/dev/ci_remote.py via a stubbed `gh`.

Run: python3 scripts/dev/tests/test_ci_remote.py   (stdlib only)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

SCRIPT = Path(__file__).resolve().parent.parent / "ci_remote.py"

PR_META_GREEN = {
    "headRefOid": "abc123",
    "url": "https://github.com/o/r/pull/7",
    "isDraft": False,
    "mergeable": "MERGEABLE",
    "reviewDecision": "APPROVED",
    "reviewThreads": {
        "totalCount": 3,
        "nodes": [{"isResolved": True}, {"isResolved": True}, {"isResolved": True}],
    },
}
PR_META_CONFLICT = dict(PR_META_GREEN, mergeable="CONFLICTING")
PR_META_UNRESOLVED = {
    "headRefOid": "abc123",
    "url": "u",
    "isDraft": False,
    "mergeable": "MERGEABLE",
    "reviewDecision": None,
    "reviewThreads": {"totalCount": 2, "nodes": [{"isResolved": False}, {"isResolved": True}]},
}


def _meta(meta: dict) -> str:
    return json.dumps({"data": {"repository": {"pullRequest": meta}}})


def _checks(*specs: tuple[str, str]) -> str:
    return json.dumps(
        {
            "check_runs": [
                {
                    "name": n,
                    "status": st,
                    "conclusion": cc,
                    "html_url": f"https://x/{n}",
                    "app": {"slug": "gaia"},
                    "started_at": None,
                    "completed_at": None,
                }
                for (n, st, cc) in specs
            ]
        }
    )


GH_SHIM = r"""#!/usr/bin/env bash
SC="${STUB_SCENARIO:-green}"
ARGS=("$@")
if [[ "${ARGS[0]:-}" == "pr" && "${ARGS[1]:-}" == "view" ]]; then
  if [[ "$SC" == "auth_fail" ]]; then echo "gh: Bad credentials" >&2; exit 4; fi
  echo '{"number":7,"url":"https://github.com/o/r/pull/7","headRefOid":"abc123"}'
  exit 0
fi
if [[ "${ARGS[0]:-}" == "api" && "${ARGS[1]:-}" == "graphql" ]]; then
  case "$SC" in
    graphql_error) echo '{"errors":[{"message":"nope"}]}'; exit 0 ;;
    timeout) sleep 30 ;;
    unresolved) echo "$STUB_META_UNRESOLVED" ;;
    conflicting) echo "$STUB_META_CONFLICT" ;;
    *) echo "$STUB_META_GREEN" ;;
  esac
  exit 0
fi
if [[ "${ARGS[0]:-}" == "api" && "${ARGS[1]}" == repos/*"/check-runs"* ]]; then
  case "$SC" in
    has_failure) echo "${STUB_CHECKS_MIXED}" ;;
    pending) echo "${STUB_CHECKS_PENDING}" ;;
    *) echo "${STUB_CHECKS_PASS}" ;;
  esac
  exit 0
fi
echo "stub-gh: unexpected invocation: ${ARGS[*]}" >&2
exit 64
"""


MIN_PY = (3, 11)  # indirect: UP036 flags literal comparisons vs ruff's target version


def _tool_python() -> list[str]:
    """The tools target >=3.11 (datetime.UTC etc.). Prefer current interpreter
    when new enough, else fall back to mise-managed python."""
    if sys.version_info >= MIN_PY:
        return [sys.executable]
    probe = subprocess.run(
        ["mise", "exec", "--", "python3", "-c", "import datetime; datetime.UTC"],
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        return ["mise", "exec", "--", "python3"]
    print("SKIP: need python >=3.11 (system python too old, mise unavailable)")
    sys.exit(0)


PY = _tool_python()

FAILURES: list[str] = []


def run_scenario(scenario: str, extra_args: list[str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as td:
        shim_dir = Path(td) / "bin"
        shim_dir.mkdir()
        shim = shim_dir / "gh"
        shim.write_text(GH_SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ)
        env["PATH"] = f"{shim_dir}:{env['PATH']}"
        env["STUB_SCENARIO"] = scenario
        env["STUB_META_GREEN"] = _meta(PR_META_GREEN)
        env["STUB_META_CONFLICT"] = _meta(PR_META_CONFLICT)
        env["STUB_META_UNRESOLVED"] = _meta(PR_META_UNRESOLVED)
        env["STUB_CHECKS_PASS"] = _checks(
            ("lint", "completed", "success"), ("gate", "completed", "skipped")
        )
        env["STUB_CHECKS_MIXED"] = _checks(
            ("lint", "completed", "success"),
            ("test-python", "completed", "failure"),
            ("coderabbit", "in_progress", None),
        )
        env["STUB_CHECKS_PENDING"] = _checks(
            ("lint", "completed", "success"), ("coderabbit", "queued", None)
        )
        proc = subprocess.run(
            [*PY, str(SCRIPT), *extra_args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        return proc.returncode, proc.stdout


def check(label: str, cond: bool, detail: str = "") -> None:
    print(
        f"  [{'PASS' if cond else 'FAIL'}] {label}"
        + (f" — {detail}" if detail and not cond else "")
    )
    if not cond:
        FAILURES.append(label)


def main() -> int:
    print("ci_remote fault-injection fixtures:")

    rc, out = run_scenario("green", ["--json"])
    d = json.loads(out)
    check("green: exit 0", rc == 0)
    check(
        "green: counts",
        d["counts"]
        == {"passed": 1, "failed": 0, "pending": 0, "skipped": 1, "error": 0, "timeout": 0},
    )
    check(
        "green: unresolved 0 / total 3",
        d["unresolved_thread_count"] == 0 and d["thread_count_total"] == 3,
    )
    check(
        "green: mergeable surface",
        d["pr"]["mergeable"] == "MERGEABLE" and d["pr"]["review_decision"] == "APPROVED",
    )

    rc, out = run_scenario("has_failure", ["--json"])
    d = json.loads(out)
    check("mixed: failed check counted", d["counts"]["failed"] == 1)
    check("mixed: pending counted separately", d["counts"]["pending"] == 1)
    check("mixed: exit 1", rc == 1)
    check("mixed: failed check sorted first", d["checks"][0]["status"] == "failed")

    rc, out = run_scenario("conflicting", ["--json"])
    check("conflicting: exit 1 even with green checks", rc == 1)

    rc, out = run_scenario("unresolved", ["--json"])
    d = json.loads(out)
    check("unresolved: counted", d["unresolved_thread_count"] == 1)

    rc, out = run_scenario("auth_fail", [])
    check("auth_fail: exit 1", rc == 1, f"got {rc}")

    rc, out = run_scenario("graphql_error", ["--json"])
    check("graphql_error: exit 2", rc == 2, f"got {rc}")

    rc, out = run_scenario("timeout", ["--timeout", "1"])
    check("timeout: exit 1 (network-class)", rc == 1, f"got {rc}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all fixtures passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
