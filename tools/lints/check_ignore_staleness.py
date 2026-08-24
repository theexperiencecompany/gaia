#!/usr/bin/env python3
"""Staleness watchdog for per-file-ignores entries — RUF100, but for config.

Inline noqas clean themselves up: RUF100 fails the build the moment a
directive masks nothing. Config-file exemptions have no such watchdog — if a
framework contract disappears (a decorator stops requiring an argument, an
upstream ships types), the per-file-ignores entry just sits there masking
nothing, forever. This check closes that loop.

For every concrete entry in ``[tool.ruff.lint.per-file-ignores]`` it re-runs
the rule with ruff's ``--isolated`` mode (which drops pyproject.toml entirely,
so the exemption under test is not applied). Zero findings means the entry
masks nothing and must be deleted; removals always pass the why-check.

Pattern globs (``**/tests/**`` …) are skipped deliberately: they are category
policy ("tests may use asserts"), not per-file debt, and cannot be classified
by single-path reruns.

Requires ``uvx`` (uses the repo-pinned ruff). Stdlib otherwise.

Usage::

    python3 tools/lints/check_ignore_staleness.py
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from _common import Violation, report_rule

RULE = "ignore-staleness"
WHY = (
    "a per-file-ignores entry that masks nothing is silent rot \u2014 inline noqas "
    "are policed by RUF100; config exemptions are policed here"
)
DOC = "tools/lints/README.md#suppression-hygiene"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"

_RUFF = [
    "uvx",
    "--no-build",
    "ruff@0.14.13",
    "check",
    "--no-cache",
    "--output-format",
    "concise",
]
_KEY_RE = re.compile(r'^"([^"]+)"\s*=\s*\[([^\]]*)\]\s*(?:#.*?)?$')


@dataclass(frozen=True)
class Entry:
    glob: str
    rule: str


def concrete_entries() -> list[Entry]:
    """Every per-file-ignores entry on a literal file path (no wildcards)."""
    out: list[Entry] = []
    lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.strip() == "[tool.ruff.lint.per-file-ignores]"
    )
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("["):
            break
        m = _KEY_RE.match(lines[i].strip())
        if m and "*" not in m.group(1):
            for rule in m.group(2).split(","):
                rule = rule.strip().strip('"')
                if rule:
                    out.append(Entry(m.group(1), rule))
    return out


_FINDING_RE = re.compile(r"^\S+:\d+:\d+: [A-Z]+\d+")


def fires(entry: Entry) -> bool:
    """True when the rule still fires somewhere in the file WITHOUT the exemption.

    Runs against a temp copy of pyproject.toml with only THIS entry stripped,
    so every other setting (line-length, target-version, select, sibling
    entries) stays exactly as configured — config-faithful, unlike --isolated,
    which drops the repo config wholesale and misjudges settings-dependent rules.
    """
    path = REPO_ROOT / entry.glob
    if not path.exists():
        return True  # vanished files are reported as live so humans look at them
    source = PYPROJECT.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'^"{re.escape(entry.glob)}"\s*=\s*\[[^\]]*"{re.escape(entry.rule)}"[^\]]*\](?:\s*#.*)?$',
        re.MULTILINE,
    )
    stripped = pattern.sub("", source)
    if stripped == source:
        return True  # could not strip the entry — treat as live, never false-delete
    # Ruff treats a config file as pyproject-style ([tool.ruff] wrapped) ONLY
    # when it is literally named pyproject.toml — any other name must carry
    # bare settings. Name it right, then clean up the whole temp dir.
    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir) / "pyproject.toml"
    tmp_path.write_text(stripped, encoding="utf-8")
    try:
        r = subprocess.run(
            [*_RUFF, "--config", str(tmp_path), "--select", entry.rule, str(path)],
            capture_output=True,
            text=True,
            check=False,
        )  # nosec B603 -- argv is a constant list plus our own resolved paths; nothing user-controlled
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    # concise output: one "path:line:col: RULE msg" line per finding. Success
    # also prints to stdout ("All checks passed!"), so match finding shapes only.
    return any(_FINDING_RE.match(line) for line in r.stdout.splitlines())


def main(argv: list[str]) -> int:
    del argv
    entries = concrete_entries()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(zip(entries, ex.map(fires, entries)))

    stale = [e for e, live in results if not live]
    violations = [
        Violation(
            path=PYPROJECT,
            line=0,
            detail=f'"{e.glob}" = ["{e.rule}"] masks nothing anymore',
            fix="delete this entry — the rule no longer fires in the file",
        )
        for e in stale
    ]
    # locate real line numbers for clickable failures
    if stale:
        lines = PYPROJECT.read_text(encoding="utf-8").splitlines()
        located: list[Violation] = []
        for v in violations:
            needle = v.detail.split(" masks")[0].split(" =")[0]
            for i, ln in enumerate(lines):
                if ln.strip().startswith(needle):
                    located.append(Violation(v.path, i + 1, v.detail, v.fix))
                    break
            else:
                located.append(v)
        violations = located

    if violations:
        report_rule(RULE, WHY, DOC, violations)
        print(f"\n{len(violations)} stale escape hatch(es) — delete them.", file=sys.stderr)
        return 1

    print(f"{RULE}: OK — {len(entries)} per-file entr(ies), all still load-bearing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
