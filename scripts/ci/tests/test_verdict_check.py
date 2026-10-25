"""A red check names what broke, at file:line, the moment it fails.

425 `mise ci:remote` reads of a red lane said "no failing verdict" or only
"<tool> failed": the grouped jobs' rollup listed which step failed and nothing
it printed (run 40195714233: file-size, tool-pins and harness-tests, zero
findings between them). `verdict.py check` is the shell every check step runs
under, and lib/output_findings.py reads what the tool printed. The fixtures
below are cut from that run's real logs.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from lib import output_findings
import pytest
import verdict

HARNESS_OUTPUT = """\
_____________________ test_a_version_the_registry_shows_late _____________________
scripts/ci/tests/test_release_cli_publish.py:85: in test_a_version_the_registry_shows_late
    assert result.returncode == 0
E   AssertionError: release.sh: line 228: SHA: SHA is required (the release commit)
E   assert 1 == 0
=========================== short test summary info ============================
FAILED scripts/ci/tests/test_release_cli_publish.py::test_a_version_the_registry_shows_late - AssertionError: release.sh: line 228: SHA: SHA is required
FAILED tools/lints/test_check_tool_pins.py::test_real_tree_is_consistent - AssertionError:
9 failed, 1154 passed in 91.40s (0:01:31)
"""

TOOL_PINS_OUTPUT = """\
✗ tool-pins — 1 violation(s)
  why:  local hooks and CI must run the same tool versions
  apps/api/app/services/sandbox/local_sandbox.Dockerfile:1  hardcodes a python version: 'python:3.12'
      fix: declare it once and mirror it
"""

FILE_SIZE_OUTPUT = """\
Files over their line cap:
   1169 / 700  packages/cli/__tests__/commands/doctor.test.ts
    780 / 400  packages/cli/src/commands/up/flow.ts
"""

VITEST_OUTPUT = """\
 FAIL  |web| src/features/chat/x.test.tsx > ChatBubble > renders the tool card
AssertionError: expected 'a' to be 'b' // Object.is equality
- Expected  "b"
+ Received  "a"
 ❯ src/features/chat/x.test.tsx:42:17
⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯
"""

PLAYWRIGHT_OUTPUT = """\
  1) [chromium] › e2e/selfhost/setup.spec.ts:18:3 › setup › creates the owner ─────────────

    Error: expect(locator).toBeVisible() failed
    Locator: getByRole('heading', { name: 'Welcome' })
    Expected: visible

      16 |   await page.goto('/setup');
    > 18 |   await expect(heading).toBeVisible();
"""


def test_a_failed_pytest_test_is_a_finding_at_its_line_with_its_error_lines_first() -> None:
    found = output_findings.read(HARNESS_OUTPUT)
    first = found[0]
    assert (first["file"], first["line"]) == ("scripts/ci/tests/test_release_cli_publish.py", 85)
    assert "test_a_version_the_registry_shows_late" in first["message"]
    assert first["detail"].splitlines()[:2] == [
        "AssertionError: release.sh: line 228: SHA: SHA is required (the release commit)",
        "assert 1 == 0",
    ]
    # Every failed test, not only the first.
    assert [f["file"] for f in found] == [
        "scripts/ci/tests/test_release_cli_publish.py",
        "tools/lints/test_check_tool_pins.py",
    ]


def test_a_lint_violation_is_a_finding_at_its_file_and_line() -> None:
    (found,) = output_findings.read(TOOL_PINS_OUTPUT)
    assert (found["file"], found["line"]) == (
        "apps/api/app/services/sandbox/local_sandbox.Dockerfile",
        1,
    )
    assert found["message"] == "hardcodes a python version: 'python:3.12'"


def test_an_oversized_file_is_a_finding_naming_its_size_and_cap() -> None:
    found = output_findings.read(FILE_SIZE_OUTPUT)
    assert [(f["file"], f["message"]) for f in found] == [
        ("packages/cli/__tests__/commands/doctor.test.ts", "1169 lines, over its 700-line cap"),
        ("packages/cli/src/commands/up/flow.ts", "780 lines, over its 400-line cap"),
    ]


def test_a_vitest_failure_lands_on_its_frame_with_the_assertion_first() -> None:
    (found,) = output_findings.read(VITEST_OUTPUT)
    assert (found["file"], found["line"]) == ("src/features/chat/x.test.tsx", 42)
    assert "renders the tool card" in found["message"]
    assert found["detail"].splitlines()[0].startswith("AssertionError: expected 'a' to be 'b'")


def test_a_playwright_failure_lands_on_its_test_with_the_error_first() -> None:
    (found,) = output_findings.read(PLAYWRIGHT_OUTPUT)
    assert (found["file"], found["line"]) == ("e2e/selfhost/setup.spec.ts", 18)
    assert found["detail"].splitlines()[0] == "Error: expect(locator).toBeVisible() failed"


def test_ruffs_default_output_is_one_finding_per_rule_at_its_arrow() -> None:
    # Cut from run 40215362768, where the first cut of the reader knew only
    # ruff's concise format and this read as "names no file:line".
    text = (
        "F401 [*] `os` imported but unused\n"
        " --> scripts/dev/agent_bench.py:461:8\n"
        "    |\n"
        "461 | import os\n"
        "E402 Module level import not at top of file\n"
        " --> scripts/dev/agent_bench.py:461:1\n"
        "Found 2 errors.\n"
    )
    found = output_findings.read(text)
    assert [(f["file"], f["line"], f["message"]) for f in found] == [
        ("scripts/dev/agent_bench.py", 461, "F401 `os` imported but unused"),
        ("scripts/dev/agent_bench.py", 461, "E402 Module level import not at top of file"),
    ]


def test_a_bandit_issue_lands_on_its_location_line() -> None:
    text = (
        ">> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'x'\n"
        "   Severity: Low   Confidence: Medium\n"
        "   Location: ./apps/api/app/x.py:12:4\n"
    )
    (found,) = output_findings.read(text)
    assert (found["file"], found["line"]) == ("apps/api/app/x.py", 12)
    assert found["message"].startswith("[B105:hardcoded_password_string]")


def test_a_workflow_annotation_the_tool_printed_is_read_back() -> None:
    (found,) = output_findings.read("::error file=apps/web/a.ts,line=7::doc-comments: restates")
    assert (found["file"], found["line"], found["message"]) == (
        "apps/web/a.ts",
        7,
        "doc-comments: restates",
    )


def test_output_with_no_location_still_carries_its_first_error_lines() -> None:
    text = "Resolving packages...\nnpm ERR! code ERESOLVE\nnpm ERR! peer react@19.1.0\ndone\n"
    (found,) = output_findings.read(text)
    assert (found["file"], found["line"]) == ("", 0)
    assert found["message"] == "npm ERR! code ERESOLVE"
    assert found["detail"].splitlines() == ["npm ERR! code ERESOLVE", "npm ERR! peer react@19.1.0"]


def test_a_fallback_pins_a_location_less_result_to_the_manifest() -> None:
    (found,) = output_findings.read("x react 19.1.0 -> 19.2.3 failed\n", fallback="package.json")
    assert (found["file"], found["line"]) == ("package.json", 1)


def test_a_path_prefix_makes_a_relative_finding_repo_relative() -> None:
    (found,) = output_findings.read("tests/x.py:3: error: bad\n", path_prefix="apps/api/")
    assert found["file"] == "apps/api/tests/x.py"


# --- verdict.py check ---------------------------------------------------------------


def _check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, script: str) -> tuple[int, Path, Path]:
    out, job_env = tmp_path / "verdicts", tmp_path / "github_env"
    monkeypatch.setenv("GITHUB_JOB", "lint-python")
    monkeypatch.setenv("GITHUB_ACTION", "tool-pins")
    monkeypatch.setenv("GITHUB_ENV", str(job_env))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    rc = verdict.cmd_check(["--out", str(out), "--", sys.executable, "-c", script])
    return rc, out / "lint-python" / "tool-pins.json", job_env


def test_a_failing_check_writes_its_own_verdict_and_keeps_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = f"import sys; print({TOOL_PINS_OUTPUT!r}); sys.exit(3)"
    rc, path, job_env = _check(tmp_path, monkeypatch, script)
    assert rc == 3
    doc = json.loads(path.read_text())
    assert doc["status"] == "fail"
    assert doc["findings"][0]["file"] == "apps/api/app/services/sandbox/local_sandbox.Dockerfile"
    assert f"{verdict.PENDING_UPLOAD_ENV}=1" in job_env.read_text()


def test_a_passing_check_writes_nothing_and_asks_for_no_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, path, job_env = _check(tmp_path, monkeypatch, "print('all good')")
    assert rc == 0
    assert not path.exists()
    assert not job_env.exists()


def test_a_check_that_reported_itself_keeps_its_own_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "verdicts"
    verdict.report("lint-python/tool-pins", verdict.Status.FAIL, "its own words", out_dir=out)
    rc, path, job_env = _check(tmp_path, monkeypatch, "import sys; sys.exit(1)")
    assert rc == 1
    assert json.loads(path.read_text())["summary"] == "its own words"
    assert f"{verdict.PENDING_UPLOAD_ENV}=1" in job_env.read_text()


# --- sarif and the gate's own verdict ---------------------------------------------------


def test_a_sarif_report_becomes_one_finding_per_result(tmp_path: Path) -> None:
    sarif = tmp_path / "results.sarif"
    sarif.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "results": [
                            {
                                "ruleId": "generic-api-key",
                                "message": {"text": "Detected a Generic API Key"},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "apps/api/.env.example"},
                                            "region": {"startLine": 12},
                                        }
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        )
    )
    out = tmp_path / "v"
    verdict.cmd_sarif([str(sarif), "--lane", "lint-mixed/gitleaks", "--out", str(out)])
    doc = json.loads((out / "lint-mixed" / "gitleaks.json").read_text())
    assert doc["status"] == "fail"
    assert doc["findings"] == [
        {
            "file": "apps/api/.env.example",
            "line": 12,
            "message": "generic-api-key: Detected a Generic API Key",
        }
    ]


def test_a_scanner_that_wrote_no_sarif_is_an_error_not_a_pass(tmp_path: Path) -> None:
    out = tmp_path / "v"
    verdict.cmd_sarif(
        [str(tmp_path / "missing.sarif"), "--lane", "scan/semgrep", "--out", str(out)]
    )
    assert json.loads((out / "scan" / "semgrep.json").read_text())["status"] == "error"


def test_the_gate_writes_which_lanes_failed_and_ignores_its_own_earlier_verdict(
    tmp_path: Path,
) -> None:
    lanes, gate = tmp_path / "lanes", tmp_path / "gate"
    verdict.report("lint-node", verdict.Status.FAIL, "1 of 11 tool(s) did not pass", out_dir=lanes)
    verdict.report("detect", verdict.Status.PASS, "passed", out_dir=lanes)
    # A re-run attempt downloads the gate's own verdict from the first attempt.
    verdict.report(verdict.GATE_LANE, verdict.Status.FAIL, "stale", out_dir=lanes)

    rc = verdict.cmd_consolidate(
        [str(lanes), "--expect", "detect=success,lint-node=failure", "--out", str(gate)]
    )

    assert rc == 1
    doc = json.loads((gate / f"{verdict.GATE_LANE}.json").read_text())
    assert [f["message"] for f in doc["findings"]] == [
        "lint-node: FAIL — 1 of 11 tool(s) did not pass"
    ]
