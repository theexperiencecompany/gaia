"""Carrying a tool's own findings into the one verdict it is allowed to emit.

Four gated lanes had adopted nothing: biome, deps, dead-code and build. Three
of them run a single tool, so `step-outcomes` — which exists to fold several
`continue-on-error` steps together — had nowhere to put their file:line, and
`collect` could only read tools that print one. syncpack, manypkg and nx name
a PACKAGE, so a lane wired through them adopted the contract and still said
nothing a reader could open.

`emit --findings` and `collect --fallback` are the two halves that close that.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "verdict", REPO_ROOT / "scripts" / "ci" / "verdict.py"
)
assert _SPEC is not None and _SPEC.loader is not None
verdict = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(verdict)

BIOME_OUTPUT = """\
apps/web/src/a.tsx:12:3 lint/suspicious/noExplicitAny  FIXABLE
  x The any type disables type checking.
apps/web/src/b.ts:4:1 lint/style/useConst
Checked 210 files. Found 2 errors.
"""

SYNCPACK_OUTPUT = """\
= Default Version Group ===============================
x react 19.1.0 -> 19.2.3 apps/web
x react 19.2.3 apps/mobile
Found 1 dependency with mismatched versions.
"""


def _collect(text: str, into: Path, monkeypatch: pytest.MonkeyPatch, *args: str) -> list[dict]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    assert verdict.cmd_collect(["--into", str(into), *args]) == 0
    return [json.loads(line) for line in into.read_text().splitlines() if line]


def test_a_tool_that_prints_file_line_needs_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _collect(BIOME_OUTPUT, tmp_path / "f.jsonl", monkeypatch, "--fallback", "package.json")
    assert [(f["file"], f["line"]) for f in found] == [
        ("apps/web/src/a.tsx", 12),
        ("apps/web/src/b.ts", 4),
    ]
    assert "lint/suspicious/noExplicitAny" in found[0]["message"]
    assert not any(f["file"] == "package.json" for f in found), "fallback fired over real findings"


def test_a_tool_that_names_a_package_lands_on_the_manifest_with_its_output_attached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = _collect(
        SYNCPACK_OUTPUT, tmp_path / "f.jsonl", monkeypatch, "--fallback", "package.json"
    )
    assert len(found) == 1
    assert found[0]["file"] == "package.json"
    assert found[0]["line"] == 1
    assert found[0]["message"].startswith("= Default Version Group")
    assert "react 19.1.0 -> 19.2.3 apps/web" in found[0]["detail"]
    assert "Found 1 dependency with mismatched versions." in found[0]["detail"]


def test_a_clean_tool_produces_no_fallback_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty stdin must not become a finding that reds a passing lane."""
    assert (
        _collect("   \n\n", tmp_path / "f.jsonl", monkeypatch, "--fallback", "package.json") == []
    )


def test_without_a_fallback_an_unparseable_tool_still_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _collect(SYNCPACK_OUTPUT, tmp_path / "f.jsonl", monkeypatch) == []


def test_emit_carries_a_collected_findings_file_into_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = tmp_path / "f.jsonl"
    _collect(BIOME_OUTPUT, findings, monkeypatch)
    out = tmp_path / "verdicts"

    assert (
        verdict.cmd_emit(
            [
                "--lane",
                "biome",
                "--status",
                "fail",
                "--summary",
                "biome reported 2 diagnostic(s)",
                "--findings",
                str(findings),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    doc = json.loads((out / "biome.json").read_text())
    assert doc["status"] == "fail"
    assert [f["file"] for f in doc["findings"]] == ["apps/web/src/a.tsx", "apps/web/src/b.ts"]


def test_emit_appends_the_file_to_any_finding_given_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    findings = tmp_path / "f.jsonl"
    _collect(BIOME_OUTPUT, findings, monkeypatch)
    out = tmp_path / "verdicts"

    verdict.cmd_emit(
        [
            "--lane",
            "biome",
            "--status",
            "fail",
            "--summary",
            "s",
            "--finding",
            "biome.json:1:config is wrong",
            "--findings",
            str(findings),
            "--out",
            str(out),
        ]
    )
    doc = json.loads((out / "biome.json").read_text())
    assert [f["file"] for f in doc["findings"]] == [
        "biome.json",
        "apps/web/src/a.tsx",
        "apps/web/src/b.ts",
    ]


def test_a_findings_file_the_lane_never_wrote_is_not_an_error(tmp_path: Path) -> None:
    """A tool that passed writes no JSONL; the pass verdict must still emit."""
    out = tmp_path / "verdicts"
    assert (
        verdict.cmd_emit(
            [
                "--lane",
                "biome",
                "--status",
                "pass",
                "--summary",
                "biome: 0 errors",
                "--findings",
                str(tmp_path / "never-written.jsonl"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert json.loads((out / "biome.json").read_text())["findings"] == []
