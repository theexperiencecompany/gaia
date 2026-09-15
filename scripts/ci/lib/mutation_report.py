#!/usr/bin/env python3
"""mutation_report.py — the mutation gate's verdict, made triageable.

Reached only through `mutation.sh` (module/shard/replay); never an entrypoint
of its own. Three responsibilities, one per subcommand:

  module   One module's classified survivors + mutmut's own diffs become a
           per-module record — every survivor with its FULL diff, no cap — and
           a human report GROUPED BY SOURCE LINE, so 39 mutant names read as
           the ~12 lines they are.
  collect  Merges the shard's module records into `shard.verdict.json` beside
           the log, and reports each module to the gate through
           `verdict.py emit` — the contract's only producer.
  replay   Re-apply one survivor's diff to a scratch copy of apps/api and run
           that module's mapped tests. mutmut's `__mutmut_13` numbering depends
           on the diff scope and cannot be regenerated on a laptop, so without
           this the only way to verify a fix was to hand-edit the source to
           match a printed diff.

TWO artifacts, deliberately, because they answer different questions and only
one of them has a schema someone else owns:

  verify-logs/verdicts/mutation/<lane>.json — the shared lane contract, written
      ONLY by `verdict.py emit` (never by this file: `consolidate` reads every
      JSON under that tree and a foreign shape crashes the gate). One finding
      per surviving LINE, carrying that line's diffs as its detail.
  <shard>.verdict.json beside shard.log — this lane's own richer record: every
      survivor with its mutant id, resolved line, one-line change and full
      diff. It lives OUTSIDE verify-logs/verdicts for the reason above, and it
      is what `replay` reads back.

The `mutmut show` parser is shared on purpose: that command prints the same
block a shard log carries, so `replay` works against `shard.verdict.json`, a
directory of module records, or a raw `shard.log` artifact.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

# The replay's pytest invocation, kept local-friendly: one module's mapped test
# files, no xdist (every worker is a full API import), and a per-test timeout so
# a mutation that induces a hang fails fast instead of wedging the terminal.
REPLAY_PYTEST_ARGS = ("-p", "no:xdist")
REPLAY_ADDOPTS = "--strict-markers --timeout=120"

# What apps/api needs on disk for its tests to collect. `app` and `tests` are
# required; the rest are copied when present (a synthetic fixture tree has no
# pyproject.toml, and demanding one would only test the fixture's shape).
REPLAY_TREE_REQUIRED = ("app", "tests")
REPLAY_TREE_OPTIONAL = ("scripts", "pytest.ini", "pyproject.toml", "conftest.py")

# This lane reports to the gate through the contract's only producer. Nothing
# here writes under verify-logs/verdicts: `verdict.py consolidate` reads every
# JSON in that tree and indexes `doc["lane"]`, so a foreign shape there does not
# degrade — it crashes the gate.
VERDICT_SCRIPT = "scripts/ci/verdict.py"

# This lane's own outcomes, mapped onto the contract's five. `survivors` and
# `gap` are one contract status because they are one answer to the gate — the
# suite does not pin this code — and two different things to fix.
CONTRACT_STATUS = {
    "pass": "pass",
    "survivors": "fail",
    "gap": "fail",
    "skip": "skip",
    "timed_out": "timed_out",
    "error": "error",
}

_SHOW_HEADER = re.compile(r"^# (?P<name>[\w.ǁ]+): (?P<status>[a-z ]+)$")
_DIFF_BODY = re.compile(r"^(---|\+\+\+|@@|[ +-])")
_MODULE_MARKER = re.compile(r"^=== (?P<module>\S+\.py) ===$")
_MUTATING_LINE = re.compile(r"^mutating (?P<module>\S+) \(tests: (?P<tests>.*)\) \.\.\.$")
_MUTANT_SUFFIX = re.compile(r"__mutmut_\d+$")
_GAP_LINES = re.compile(r"^\s*line\(s\) (?P<lines>[\d ]+)$", re.MULTILINE)

# Why a survivor was taken off the verdict, in the words of someone who has
# never met mutmut. The keys are `mutation_classify.py`'s verdicts.
EXCLUSION_REASONS = {
    "LOGGING": "logging-only — the edit lands inside a log.debug/log.info call, "
    "the two levels that never reach the wide event",
    "EQUIV": "provably equivalent — the mutated program does the same thing at runtime",
    "UNCHANGED": "on a line this PR did not change (the gate is diff-driven)",
}


@dataclass(frozen=True)
class Survivor:
    """One mutant the suite failed to kill, with everything needed to act on it."""

    name: str
    function: str
    file: str
    line: int | None
    source: str
    change: str
    diff: str


@dataclass(frozen=True)
class Excluded:
    """One survivor the classifier took off the verdict, and why."""

    name: str
    reason: str


@dataclass
class ModuleVerdict:
    """One module's outcome, in this lane's own vocabulary.

    Round-trips through `to_dict`/`from_dict` into shard.verdict.json — the
    replay artifact. The contract's five-key shape is a PROJECTION of this,
    built by `emit_command`: that one carries one finding per line, this one
    carries every mutant, and only this one can drive a replay.
    """

    module: str
    status: str
    path: str = ""
    testfiles: list[str] = field(default_factory=list)
    survivors: list[Survivor] = field(default_factory=list)
    excluded: list[Excluded] = field(default_factory=list)
    gap_lines: list[int] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "module": self.module,
            "path": self.path,
            "status": self.status,
            "testfiles": list(self.testfiles),
            "survivors": [vars(survivor) for survivor in self.survivors],
            "excluded": [vars(entry) for entry in self.excluded],
            "gap_lines": list(self.gap_lines),
            "reason": self.reason,
        }


def module_slug(module: str) -> str:
    """`app/services/x.py` -> `app_services_x`, the verdict file's name."""
    return module.removesuffix(".py").replace("/", "_")


def qualified_function(mutant_name: str) -> str:
    """`...bot.x__may_mint__mutmut_3` -> `_may_mint`; `xǁCǁm__mutmut_1` -> `C.m`.

    mutmut names a mutant after the function it rewrites, prefixed `x_` at
    module level and `xǁClassǁmethod` for a method. Recovering the real name is
    what turns a mutant id into something a reader recognises.
    """
    tail = mutant_name.rsplit(".", 1)[-1]
    base = _MUTANT_SUFFIX.sub("", tail)
    if "ǁ" in base:
        return ".".join(base.split("ǁ")[1:])
    return base.removeprefix("x_")


def parse_show_blocks(text: str) -> dict[str, str]:
    """Mutant name -> the unified diff `mutmut show` printed for it.

    Same format in a shard log and in a fresh `mutmut show` capture, so one
    parser serves the report and the replay.
    """
    diffs: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        header = _SHOW_HEADER.match(lines[index])
        if header is None:
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if _SHOW_HEADER.match(line) or (line and not _DIFF_BODY.match(line)):
                break
            body.append(line)
            index += 1
        while body and not body[-1].strip():
            body.pop()
        if body:
            diffs[header.group("name")] = "\n".join(body)
    return diffs


def diff_hunk(diff: str) -> tuple[list[str], list[str]]:
    """The diff's before/after line blocks, markers stripped.

    `before` is context + removed lines, `after` is context + added — the two
    texts that must swap for the mutation to be applied.
    """
    before: list[str] = []
    after: list[str] = []
    for line in diff.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("-"):
            before.append(line[1:])
        elif line.startswith("+"):
            after.append(line[1:])
        elif line.startswith(" "):
            before.append(line[1:])
            after.append(line[1:])
        elif not line:
            before.append("")
            after.append("")
    return before, after


def changed_lines(diff: str) -> tuple[list[str], list[str]]:
    """Just the removed and added lines of a diff, markers stripped."""
    removed = [line[1:] for line in diff.splitlines() if line.startswith("-") and line[:3] != "---"]
    added = [line[1:] for line in diff.splitlines() if line.startswith("+") and line[:3] != "+++"]
    return removed, added


_TOKEN_BREAK = " \t,()[]{}:"


def _widen(text: str, start: int, end: int, forward: bool) -> int:
    """Walk a split point out to the nearest token boundary.

    Character-level diffing alone yields `True → None`, which is true and
    useless; widening to the token gives `nx=True → nx=None`, which names the
    argument that went unnoticed.
    """
    if forward:
        while end < len(text) and text[end] not in _TOKEN_BREAK:
            end += 1
        return end
    while start > 0 and text[start - 1] not in _TOKEN_BREAK:
        start -= 1
    return start


def change_summary(removed: list[str], added: list[str]) -> str:
    """One line naming the edit: `"1" → None`, `nx=True → nx=None`, `dropped …`.

    Two shapes of answer, best first: the token that changed within one line,
    and — when the hunk spans lines, or the within-line difference is invisible
    once stripped — the lines themselves.
    """
    removed, added = _trim_common_lines(removed, added)
    if len(removed) == 1 and len(added) == 1:
        token = _token_change(removed[0], added[0])
        if token is not None:
            return token
    return _describe(
        " ".join(line.strip() for line in removed if line.strip()),
        " ".join(line.strip() for line in added if line.strip()),
    )


def _trim_common_lines(removed: list[str], added: list[str]) -> tuple[list[str], list[str]]:
    """Drop the lines a multi-line hunk carries unchanged — they are not the edit.

    This is what turns "return 1 x = 2 → return 1" into "dropped `x = 2`".
    """
    while removed and added and removed[0] == added[0]:
        removed, added = removed[1:], added[1:]
    while removed and added and removed[-1] == added[-1]:
        removed, added = removed[:-1], added[:-1]
    return removed, added


def _token_change(before: str, after: str) -> str | None:
    """The token that changed between two versions of ONE line.

    None when the difference vanishes once stripped (a whitespace-only edit):
    the caller then falls back to naming the lines, because "` → `" is not an
    answer.
    """
    head = 0
    while head < min(len(before), len(after)) and before[head] == after[head]:
        head += 1
    tail = 0
    while (
        tail < min(len(before), len(after)) - head
        and before[len(before) - 1 - tail] == after[len(after) - 1 - tail]
    ):
        tail += 1
    old, new = before[head : len(before) - tail], after[head : len(after) - tail]
    if not old.strip() and not new.strip():
        return None
    if old.strip() and new.strip():
        start = _widen(before, head, len(before) - tail, forward=False)
        end = _widen(before, head, len(before) - tail, forward=True)
        widened_old = before[start:end]
        widened_new = after[start : len(after) - (len(before) - end)]
        if widened_old.strip() and widened_new.strip():
            old, new = widened_old, widened_new
    return _describe(old, new)


def _describe(old: str, new: str) -> str:
    """`a → b`, or the one-sided form when the edit only removed or only added."""
    old, new = old.strip(), new.strip()
    if old and new:
        return f"{_clip(old)} → {_clip(new)}"
    if old:
        return f"dropped `{_clip(old)}`"
    return f"inserted `{_clip(new)}`"


def _clip(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def locate_hunk(source: list[str], before: list[str], hint: int | None) -> int:
    """Index in `source` where this diff's before-block starts.

    mutmut's `@@ -15,7 +15,7 @@` counts lines of its own per-function rewrite,
    not of the real file, so the hunk header cannot be trusted for a line
    number — the text is the only honest anchor. `hint` (the classifier's real
    line number) breaks ties when the block appears more than once.
    """
    stripped = [line.rstrip() for line in before]
    matches = [
        index
        for index in range(len(source) - len(stripped) + 1)
        if [line.rstrip() for line in source[index : index + len(stripped)]] == stripped
    ]
    if not matches:
        raise SystemExit(
            "mutation replay: this survivor's diff does not match the file on disk — "
            "the module changed since the run that produced it. Re-run the gate."
        )
    if len(matches) == 1:
        return matches[0]
    if hint is None:
        raise SystemExit(
            f"mutation replay: the diff matches {len(matches)} places in the file and the "
            "verdict carries no line number to disambiguate. Select the survivor by name."
        )
    return min(matches, key=lambda index: abs(index + 1 - hint))


def apply_hunk(source: list[str], diff: str, hint: int | None) -> tuple[list[str], int]:
    """The file's lines with this mutation applied, and the mutated line number."""
    before, after = diff_hunk(diff)
    start = locate_hunk(source, before, hint)
    patched = source[:start] + after + source[start + len(before) :]
    removed, _ = changed_lines(diff)
    offset = 0
    if removed:
        offset = next(
            (i for i, line in enumerate(before) if line.rstrip() == removed[0].rstrip()), 0
        )
    return patched, start + offset + 1


def _survivor(
    name: str, line: int | None, diff: str, module: str, module_lines: list[str]
) -> Survivor:
    removed, added = changed_lines(diff)
    source = ""
    if line is not None and 0 < line <= len(module_lines):
        source = module_lines[line - 1].strip()
    return Survivor(
        name=name,
        function=qualified_function(name),
        file=module,
        line=line,
        source=source,
        change=change_summary(removed, added),
        diff=diff,
    )


def group_by_line(survivors: list[Survivor]) -> list[tuple[int | None, list[Survivor]]]:
    """Survivors bucketed by the source line they mutate, in file order."""
    buckets: dict[int | None, list[Survivor]] = {}
    for survivor in survivors:
        buckets.setdefault(survivor.line, []).append(survivor)
    return sorted(buckets.items(), key=lambda item: (item[0] is None, item[0] or 0))


# --- the contract ------------------------------------------------------------


def summary_line(verdict: ModuleVerdict) -> str:
    """The one line a human reads first, and the only one the gate table shows."""
    if verdict.status == "survivors":
        groups = len(group_by_line(verdict.survivors))
        text = (
            f"{len(verdict.survivors)} surviving mutant(s) on {groups} changed line(s) "
            f"in {verdict.module} — the suite would not notice this code being wrong"
        )
        if verdict.excluded:
            # The exclusions have no field of their own in the contract, and an
            # invisible exclusion is how a lane quietly stops proving anything.
            text += f" ({len(verdict.excluded)} survivor(s) excluded as equivalent/logging-only)"
        return text
    if verdict.status == "gap":
        return f"{len(verdict.gap_lines)} changed line(s) no test reaches in {verdict.module}"
    if verdict.status == "pass":
        return f"every mutant on the changed lines of {verdict.module} was killed"
    return verdict.reason or f"{verdict.module}: {verdict.status}"


def advice(verdict: ModuleVerdict) -> list[str]:
    """What to actually do, one sentence each — never a restatement of the status."""
    if verdict.status == "survivors":
        out = [
            f"Assert what {verdict.path}:{line} does — {len(group)} mutant(s) survive there "
            f"({_clip(_change_list(group), 100)})."
            for line, group in group_by_line(verdict.survivors)
            if line is not None
        ]
        out.append(
            "Reproduce any of them without a lane run: bash scripts/ci/mutation.sh replay "
            f"shard.verdict.json {verdict.path}:{first_surviving_line(verdict)}"
        )
        return out
    if verdict.status == "gap":
        return [
            f"Write a test that executes {verdict.path}:{line} and asserts what it does."
            for line in verdict.gap_lines
        ] + [
            "If those lines are only reachable through the contract tier, say so on the PR — "
            "that tier does not run in this lane."
        ]
    if verdict.status in ("error", "timed_out"):
        return [
            f"Re-run this module alone before trusting anything about it: "
            f"bash scripts/ci/mutation.sh module {verdict.module}"
        ]
    return []


def first_surviving_line(verdict: ModuleVerdict) -> int | None:
    """The first line the replay advice should point at."""
    for line, _group in group_by_line(verdict.survivors):
        if line is not None:
            return line
    return None


def emit_command(
    verdict: ModuleVerdict, repo_root: Path, detail_dir: Path, out_dir: Path
) -> list[str]:
    """The `verdict.py emit` call that reports this module to the gate.

    One finding per surviving LINE, not per mutant: the gate's table and the
    PR's diff view each get one entry per thing to fix, and the line's mutants
    ride in the message with their diffs in the detail. The mutant-level record
    stays in shard.verdict.json, where `replay` reads it.
    """
    command = [
        sys.executable,
        str(repo_root / VERDICT_SCRIPT),
        "emit",
        "--lane",
        f"mutation/{verdict.module}",
        "--status",
        CONTRACT_STATUS[verdict.status],
        "--summary",
        summary_line(verdict),
    ]
    for index, (line, group) in enumerate(group_by_line(verdict.survivors)):
        if line is None:
            # Recovered from the shard log, which records a survivor's diff but
            # not the line the classifier resolved it to. A finding needs a real
            # line; the summary still carries the count, and the status is still
            # a failure, so nothing is lost but the anchor.
            continue
        message = f"{len(group)} mutant(s) survive: {_clip(_change_list(group), 180)}"
        detail = detail_dir / f"{index}.diff"
        detail.write_text("\n\n".join(survivor.diff for survivor in group) + "\n")
        command += ["--finding", f"{verdict.path}:{line}:{message}", "--detail-file", str(detail)]
    for line in verdict.gap_lines:
        command += [
            "--finding",
            f"{verdict.path}:{line}:no mapped test executes this changed line, so no mutant "
            "on it could ever be killed",
        ]
    for item in advice(verdict):
        command += ["--advice", item]
    # The directory is passed through, never computed here: mutation.sh gets it
    # from `verdict.py dir`, so both ends of this call agree by construction.
    return [*command, "--out", str(out_dir)]


def emit_shared_verdict(verdict: ModuleVerdict, repo_root: Path, out_dir: Path) -> None:
    """Report one module to the gate. `verdict.py emit` is the only producer."""
    with tempfile.TemporaryDirectory(prefix="mutation-detail-") as detail_dir:
        command = emit_command(verdict, repo_root, Path(detail_dir), out_dir)
        result = subprocess.run(command, check=False)
    if result.returncode != 0:
        # Loud and named, not a traceback: `emit` needs python >= 3.11 (it uses
        # StrEnum), and a lane invoked under an older interpreter fails here
        # with nothing pointing at the interpreter. A shard whose verdict did
        # not reach the gate must say exactly which call did not land.
        raise SystemExit(
            f"mutation: reporting {verdict.module} to the gate failed (exit "
            f"{result.returncode}) — the module's verdict never reached the gate.\n"
            f"  {' '.join(command)}"
        )


def _as_list(value: object) -> list[dict[str, object]]:
    """A JSON field that must be a list, or a loud failure — never a silent empty."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SystemExit(f"mutation report: expected a list in the verdict, got {type(value)}")
    return value


def write_record(path: Path, verdict: ModuleVerdict) -> None:
    """Write one module's record — this lane's own schema, never the contract's."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False) + "\n")


def from_dict(data: dict[str, object]) -> ModuleVerdict:
    """Read one module record back — every field `replay` needs, none inferred."""
    return ModuleVerdict(
        module=str(data["module"]),
        status=str(data["status"]),
        path=str(data.get("path", "")),
        testfiles=[str(item) for item in _as_list(data.get("testfiles"))],
        survivors=[_survivor_from_dict(item) for item in _as_list(data.get("survivors"))],
        excluded=[
            Excluded(name=str(item["name"]), reason=str(item["reason"]))
            for item in _as_list(data.get("excluded"))
        ],
        gap_lines=[int(str(line)) for line in _as_list(data.get("gap_lines"))],
        reason=str(data["reason"]) if data.get("reason") else None,
    )


def _survivor_from_dict(item: dict[str, object]) -> Survivor:
    line = item.get("line")
    return Survivor(
        name=str(item["name"]),
        function=str(item["function"]),
        file=str(item["file"]),
        line=int(line) if isinstance(line, int) else None,
        source=str(item.get("source", "")),
        change=str(item.get("change", "")),
        diff=str(item.get("diff", "")),
    )


# --- human output ------------------------------------------------------------


def render_report(verdict: ModuleVerdict) -> str:
    """The human verdict: one heading per surviving source line, not a name list."""
    lines: list[str] = []
    groups = group_by_line(verdict.survivors)
    lines.append(
        f"MUTATION FAILED — {len(verdict.survivors)} surviving mutant(s) on "
        f"{len(groups)} changed line(s) in {verdict.module}."
    )
    lines.append(
        "  The suite passes with each edit below applied, so it would not notice "
        "the code being wrong there."
    )
    for line_no, group in groups:
        where = f"{verdict.path}:{line_no}" if line_no else f"{verdict.path} (line unknown)"
        lines.append("")
        lines.append(f"  {where}")
        if group[0].source:
            lines.append(f"      {group[0].source}")
        lines.append(f"    {len(group)} mutant(s) survive on this line:")
        for survivor in group:
            lines.append(f"      {survivor.change}   [{survivor.name.rsplit('.', 1)[-1]}]")
    if verdict.excluded:
        lines.append("")
        lines.append(f"  {len(verdict.excluded)} survivor(s) excluded from the verdict:")
        for entry in verdict.excluded:
            lines.append(f"      {entry.name.rsplit('.', 1)[-1]} — {entry.reason}")
    lines.append("")
    lines.append("  The bracketed id is mutmut's name for that one edit. Reproduce it with:")
    lines.append("      bash scripts/ci/mutation.sh replay shard.verdict.json <id>")
    lines.append(
        "  Every survivor's full diff is in shard.verdict.json, beside this log in the "
        "shard's artifact (no cap)."
    )
    return "\n".join(lines)


def _change_list(group: list[Survivor]) -> str:
    """The distinct one-line changes on one source line, in the order found."""
    return "; ".join(dict.fromkeys(survivor.change for survivor in group))


def step_summary(verdicts: list[ModuleVerdict]) -> str:
    """The shard's own block: which modules it ran and how they came out.

    Counts only. Every finding already has a step-summary block of its own,
    written by `verdict.py emit` per module — repeating them here would put the
    same survivor on the page twice.
    """
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    lines = ["### Mutation shard", "", "| status | modules |", "| --- | --- |"]
    for status in ("pass", "survivors", "gap", "skip", "timed_out", "error"):
        if counts.get(status):
            lines.append(f"| {status} | {counts[status]} |")
    unusable = [verdict.module for verdict in verdicts if verdict.status in ("error", "timed_out")]
    if unusable:
        lines += [
            "",
            "Module(s) that reached NO verdict: " + ", ".join(f"`{m}`" for m in unusable),
        ]
    return "\n".join(lines) + "\n"


# --- subcommands -------------------------------------------------------------


def _read_records(path: Path) -> list[tuple[str, str, str]]:
    """`name<TAB>mutmut-status<TAB>classifier-verdict` rows, as mutation.sh writes them."""
    rows: list[tuple[str, str, str]] = []
    if not path.exists():
        return rows
    for raw in path.read_text().splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) != 3:
            raise SystemExit(f"mutation report: malformed record line: {raw!r}")
        rows.append((parts[0], parts[1], parts[2]))
    return rows


def cmd_module(args: argparse.Namespace) -> int:
    """Write one module's record and print the grouped human report.

    The gate is reported to by `collect`, not here: `emit` prints the
    annotations, and a module's stdout is redirected into the shard log where
    GitHub never sees them.
    """
    module_file = Path(args.module_file)
    module_lines = module_file.read_text().splitlines() if module_file.exists() else []
    diffs = parse_show_blocks(Path(args.diffs).read_text()) if args.diffs else {}
    verdict = ModuleVerdict(
        module=args.module,
        path=args.path,
        status=args.status,
        testfiles=json.loads(args.testfiles) if args.testfiles else [],
        reason=args.reason or None,
    )
    for name, _status, classifier_verdict in _read_records(Path(args.records)):
        kind, _, line_text = classifier_verdict.partition(":")
        if kind == "CHANGED":
            line = int(line_text) if line_text.isdigit() else None
            verdict.survivors.append(
                _survivor(name, line, diffs.get(name, ""), args.module, module_lines)
            )
        else:
            verdict.excluded.append(Excluded(name=name, reason=EXCLUSION_REASONS[kind]))
    write_record(Path(args.out), verdict)
    if verdict.survivors:
        print(render_report(verdict))
    return 0


def _section_status(section: str) -> tuple[str, str | None, list[int]]:
    """A module's log section -> (status, reason, unreachable line numbers)."""
    if "MUTATION FAILED — changed code no test reaches" in section:
        match = _GAP_LINES.search(section)
        lines = [int(part) for part in match.group("lines").split()] if match else []
        return "gap", None, lines
    for marker in ("SKIP: ", "MUTATION SKIPPED"):
        if marker in section:
            start = section.index(marker)
            reason = section[start : start + 400].splitlines()
            return "skip", " ".join(part.strip() for part in reason).strip(), []
    if "MUTATION FAILED" in section:
        return "survivors", None, []
    if "Mutation: OK" in section:
        return "pass", None, []
    return "error", None, []


def split_shard_log(text: str) -> list[tuple[str, str]]:
    """A shard log -> [(module, its section)], split on the `=== module ===` markers."""
    sections: list[tuple[str, str]] = []
    current: str | None = None
    body: list[str] = []
    for line in text.splitlines():
        marker = _MODULE_MARKER.match(line)
        if marker:
            if current is not None:
                sections.append((current, "\n".join(body)))
            current = marker.group("module")
            body = []
            continue
        body.append(line)
    if current is not None:
        sections.append((current, "\n".join(body)))
    return sections


def _testfiles_from_section(section: str) -> list[str]:
    for line in section.splitlines():
        match = _MUTATING_LINE.match(line)
        if match:
            return match.group("tests").split()
    return []


def verdict_from_section(module: str, section: str, api_prefix: str) -> ModuleVerdict:
    """Reconstruct a module verdict from its log alone (it wrote no verdict file)."""
    status, reason, gap_lines = _section_status(section)
    verdict = ModuleVerdict(
        module=module,
        status=status,
        path=f"{api_prefix}/{module}",
        testfiles=_testfiles_from_section(section),
        gap_lines=gap_lines,
        reason=reason,
    )
    for name, diff in parse_show_blocks(section).items():
        verdict.survivors.append(_survivor(name, None, diff, module, []))
    return verdict


# A module killed by timeout(1): SIGKILL through the shard's watchdog, or
# timeout's own exit code. Neither is a test weakness and neither is a pass.
TIMEOUT_EXIT_CODES = {"124", "137"}


def cmd_collect(args: argparse.Namespace) -> int:
    """Merge the shard's module records, then report each module to the gate.

    Two outputs, one pass: `shard.verdict.json` beside the log (this lane's own
    record, what `replay` reads) and one `verdict.py emit` call per module (the
    shared contract, what the quality gate consolidates). The annotations and
    the per-lane step-summary block come from `emit` — printing them here too
    would put every finding on the page twice.
    """
    sections = dict(split_shard_log(Path(args.log).read_text()))
    record_dir = Path(args.dir)
    repo_root = Path(args.repo_root)
    verdict_out = Path(args.verdict_out)
    verdicts: list[ModuleVerdict] = []
    for raw in Path(args.rcs).read_text().splitlines():
        if not raw.strip():
            continue
        module, _, rc_text = raw.partition("\t")
        rc = rc_text.strip()
        record = record_dir / f"{module_slug(module)}.json"
        if record.exists():
            # The module wrote its own, and it is strictly better than anything
            # reconstructable here: it carries the classifier's REAL line
            # numbers, which is what puts a finding on the PR's diff.
            # Reconstruction is the fallback, never the default.
            verdicts.append(from_dict(json.loads(record.read_text())))
            continue
        verdict = verdict_from_section(module, sections.get(module, ""), args.api_prefix)
        if rc in TIMEOUT_EXIT_CODES:
            verdict.status = "timed_out"
            verdict.reason = f"killed at its timeout (exit {rc}) — nothing was proven here"
        elif rc not in ("", "0") and verdict.status in ("pass", "skip", "error"):
            # The log said nothing conclusive but the module exited non-zero: an
            # inconclusive section read as `pass` is the false green this gate
            # exists to stop, so the exit code wins. `error` is included so that
            # the summary names the exit code instead of restating the status.
            verdict.status = "error"
            verdict.reason = f"{module} exited {rc} without reaching a verdict — see shard.log"
        verdicts.append(verdict)
    for verdict in verdicts:
        emit_shared_verdict(verdict, repo_root, verdict_out)
    write_record_set(Path(args.out), verdicts)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as handle:
            handle.write(step_summary(verdicts))
    print(f"mutation: {len(verdicts)} module(s) reported; replay artifact {args.out}")
    return 0


def write_record_set(path: Path, verdicts: list[ModuleVerdict]) -> None:
    """The shard's replay artifact: every module's record in one file.

    Beside shard.log and NOT under verify-logs/verdicts: `consolidate` reads
    every JSON in that tree as a lane verdict, and this is not one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"modules": [verdict.to_dict() for verdict in verdicts]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def load_verdicts(source: Path, api_prefix: str) -> list[ModuleVerdict]:
    """Read records from shard.verdict.json, a directory of them, or a shard log."""
    if source.is_dir():
        return [from_dict(json.loads(path.read_text())) for path in sorted(source.glob("*.json"))]
    if source.suffix == ".json":
        data = json.loads(source.read_text())
        if not isinstance(data, dict):
            raise SystemExit(f"mutation replay: {source} is not a mutation record")
        if "modules" in data:
            return [from_dict(item) for item in _as_list(data["modules"])]
        return [from_dict(data)]
    return [
        verdict_from_section(module, section, api_prefix)
        for module, section in split_shard_log(source.read_text())
    ]


def select_survivors(
    verdicts: list[ModuleVerdict], selector: str
) -> list[tuple[ModuleVerdict, Survivor]]:
    """Everything the selector names: one mutant id, or every mutant on a file:line."""
    chosen: list[tuple[ModuleVerdict, Survivor]] = []
    file_part, _, line_part = selector.rpartition(":")
    want_line = int(line_part) if file_part and line_part.isdigit() else None
    for verdict in verdicts:
        for survivor in verdict.survivors:
            if want_line is not None:
                if survivor.line == want_line and verdict.path.endswith(file_part.lstrip("./")):
                    chosen.append((verdict, survivor))
            elif survivor.name == selector or survivor.name.endswith(f".{selector}"):
                chosen.append((verdict, survivor))
    return chosen


def _copy_api_tree(api_root: Path, destination: Path) -> None:
    for name in REPLAY_TREE_REQUIRED:
        source = api_root / name
        if not source.is_dir():
            raise SystemExit(f"mutation replay: {source} does not exist — wrong --api-root?")
        shutil.copytree(source, destination / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in REPLAY_TREE_OPTIONAL:
        source = api_root / name
        if source.is_dir():
            shutil.copytree(
                source, destination / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        elif source.is_file():
            shutil.copy(source, destination / name)


def _run_tests(python: str, cwd: Path, testfiles: list[str], addopts: str, pycache: Path) -> int:
    """One pytest run over the scratch tree, with its bytecode cache under ``pycache``.

    The mutated and the reverted source can share a size and a whole-second
    mtime — the two things a ``.pyc`` header is validated against — so a
    cache written by the mutated run would serve the mutated bytecode to the
    baseline run and report INCONCLUSIVE. Each run therefore gets its own
    ``PYTHONPYCACHEPREFIX`` tree instead of the in-tree ``__pycache__``.
    """
    command = [
        python,
        "-m",
        "pytest",
        *testfiles,
        *REPLAY_PYTEST_ARGS,
        "-o",
        f"addopts={addopts}",
        "-q",
    ]
    print(f"  $ {' '.join(command)}")
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(pycache)}
    return subprocess.run(command, cwd=cwd, env=env, check=False).returncode


def _replay_one(
    verdict: ModuleVerdict, survivor: Survivor, args: argparse.Namespace
) -> tuple[str, str]:
    """Apply one survivor's diff to a scratch copy and run the module's tests."""
    api_root = Path(args.api_root)
    testfiles = verdict.testfiles or _fallback_testfiles(Path(args.repo_root), verdict.module)
    if not testfiles:
        raise SystemExit(
            f"mutation replay: no test files known for {verdict.module} — the verdict "
            "carries none and mutation_matrix.py maps none."
        )
    with tempfile.TemporaryDirectory(prefix="mutation-replay-") as scratch:
        workdir = Path(scratch) / "api"
        workdir.mkdir()
        _copy_api_tree(api_root, workdir)
        target = workdir / verdict.module
        original = target.read_text().splitlines()
        patched, line = apply_hunk(original, survivor.diff, survivor.line)
        target.write_text("\n".join(patched) + "\n")
        print(f"  applied {survivor.change} at {verdict.module}:{line} (scratch copy only)")
        rc = _run_tests(
            args.python, workdir, testfiles, args.addopts, Path(scratch) / "pycache-mutated"
        )
        if rc == 0:
            return "SURVIVED", "the tests pass with the mutation applied — the gap is real"
        target.write_text("\n".join(original) + "\n")
        print("  tests failed with the mutation — re-running unpatched to prove they are green")
        baseline = _run_tests(
            args.python, workdir, testfiles, args.addopts, Path(scratch) / "pycache-baseline"
        )
    if baseline == 0:
        return "KILLED", "the tests fail with the mutation and pass without it"
    return "INCONCLUSIVE", "the tests fail WITHOUT the mutation too — fix the suite first"


def _fallback_testfiles(repo_root: Path, module: str) -> list[str]:
    """The lane's own module -> test-file mapping, for a verdict that carries none."""
    matrix = repo_root / "scripts" / "ci" / "lib" / "mutation_matrix.py"
    if not matrix.exists():
        return []
    result = subprocess.run(
        [sys.executable, str(matrix)],
        input=f"apps/api/{module}\n",
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=True,
    )
    for entry in json.loads(result.stdout):
        if entry["module"] == module:
            return [str(item) for item in entry["testfiles"]]
    return []


def cmd_replay(args: argparse.Namespace) -> int:
    """Reproduce one survivor locally: patch a scratch copy, run its tests, restore."""
    repo_root = Path(args.repo_root)
    before = _git_status(repo_root)
    verdicts = load_verdicts(Path(args.source), args.api_prefix)
    chosen = select_survivors(verdicts, args.selector)
    if not chosen:
        names = [survivor.name for verdict in verdicts for survivor in verdict.survivors]
        raise SystemExit(
            f"mutation replay: nothing in {args.source} matches {args.selector!r}.\n"
            "  Known survivors:\n    " + "\n    ".join(names[:40] or ["(none)"])
        )
    results: list[tuple[str, str, str]] = []
    for verdict, survivor in chosen:
        print(f"\n=== {survivor.name} ({verdict.module}) ===")
        outcome, why = _replay_one(verdict, survivor, args)
        print(f"  {outcome}: {why}")
        results.append((survivor.name, outcome, why))
    _assert_tree_untouched(before, _git_status(repo_root), repo_root, Path(args.api_root))
    print("\nreplay summary (working tree unchanged):")
    for name, outcome, _why in results:
        print(f"  {outcome:13} {name}")
    return 0 if all(outcome != "INCONCLUSIVE" for _n, outcome, _w in results) else 1


def _assert_tree_untouched(before: str, after: str, repo_root: Path, api_root: Path) -> None:
    """Fail loudly if the replay left anything behind under the app it mutated.

    Scoped to the api tree rather than the whole checkout on purpose: this repo
    is routinely worked in by several processes at once, and failing on a file
    somebody else wrote three directories away would be a false alarm that
    teaches people to ignore the real one. Anything under api_root IS ours.
    """
    changed = set(after.splitlines()) ^ set(before.splitlines())
    if not changed:
        return
    try:
        scope = f"{api_root.resolve().relative_to(repo_root.resolve())}/"
    except ValueError:
        scope = ""
    ours = [entry for entry in sorted(changed) if scope and scope in entry]
    if ours:
        raise SystemExit(
            "mutation replay: it modified the working tree. It must not — the mutation is "
            "applied to a scratch copy only.\n  " + "\n  ".join(ours)
        )
    print(
        f"\nnote: {len(changed)} unrelated working-tree change(s) appeared during the replay "
        f"(nothing under {scope or repo_root}); another process is writing in this checkout."
    )


def _git_status(repo_root: Path) -> str:
    """The working tree's dirt, snapshotted so the replay can prove it added none."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"mutation replay: --repo-root {repo_root} is not a git checkout, so the "
            "'working tree untouched' guarantee cannot be checked.\n"
            f"  git said: {result.stderr.strip()}"
        )
    return result.stdout


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    module = subparsers.add_parser("module", help="write one module's record")
    module.add_argument("--module", required=True, help="app/... path of the mutated module")
    module.add_argument("--path", required=True, help="repo-relative path (apps/api/app/...)")
    module.add_argument("--module-file", required=True, help="the real module file to read")
    module.add_argument("--records", required=True, help="classifier records TSV")
    module.add_argument("--diffs", default="", help="concatenated `mutmut show` output")
    module.add_argument("--testfiles", default="", help="JSON array of test files")
    module.add_argument("--status", required=True, choices=sorted(CONTRACT_STATUS))
    module.add_argument("--reason", default="", help="summary for a skip/error verdict")
    module.add_argument("--out", required=True, help="module record to write")

    collect = subparsers.add_parser("collect", help="merge the records, report to the gate")
    collect.add_argument("--log", required=True, help="the shard log")
    collect.add_argument("--dir", required=True, help="where the module records live")
    collect.add_argument("--rcs", required=True, help="module<TAB>exit-code rows")
    collect.add_argument("--out", required=True, help="shard.verdict.json (the replay artifact)")
    collect.add_argument("--repo-root", required=True, help="where scripts/ci/verdict.py lives")
    collect.add_argument(
        "--verdict-out",
        required=True,
        help="the verdict tree, as `verdict.py dir` reports it — never derived here",
    )
    collect.add_argument("--api-prefix", default="apps/api")

    replay = subparsers.add_parser("replay", help="reproduce one survivor locally")
    replay.add_argument("source", help="shard.verdict.json, a record dir, or shard.log")
    replay.add_argument("selector", help="a mutant id, or file.py:LINE")
    replay.add_argument("--repo-root", required=True)
    replay.add_argument("--api-root", required=True)
    replay.add_argument("--python", default=sys.executable)
    replay.add_argument("--addopts", default=REPLAY_ADDOPTS)
    replay.add_argument("--api-prefix", default="apps/api")

    args = parser.parse_args(argv)
    handlers = {"module": cmd_module, "collect": cmd_collect, "replay": cmd_replay}
    return handlers[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
