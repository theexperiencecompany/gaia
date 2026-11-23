#!/usr/bin/env python3
"""baselines.py — the ratchet baselines, which only ever shrink.

A ratchet baseline records the violations that predate a gate. Every one of
them documents the same contract: fixing an entry deletes its line, and adding
one is a founder's decision, not an author's. Nothing enforced the second half,
so a baseline could grow inside any PR that also touched the code (the brief
stack added api-shape-twins lines that way). This script is that half.

Subcommands:
    growth [--base REV]
        Fail when this change adds an entry to a ratchet baseline, or loosens a
        bound one records, unless the comment block directly above the entry
        (or above the run of entries it opens) carries an approval written in
        this same change:

            # growth approved by <github-login> on YYYY-MM-DD: <reason>

        The baselines: every scripts/ci/baselines/*.txt, tools/lints/*_baseline.txt
        and apps/api/tests/meta/*_baseline.txt, and every module-level *ALLOWLIST*
        literal in tools/lints/*.py. An entry is a non-blank, non-comment line (a
        deferred-until= field is not part of it, since renewing a deferral is the
        documented process). Two entry shapes carry a bound rather than a fact:
        squirrel's `score:<category>=<n>` is a floor (lowering it loosens), and an
        allowlist dict's int value is a ceiling (raising it loosens). A baseline
        file or allowlist that did not exist at the base is a new gate's seed and
        is not growth.

Env contract: GAIA_PR_BASE or GITHUB_BASE_REF (through `changes.sh base-rev`,
which falls back to master locally); --base overrides it. Needs the base
commit in the clone (fetch-depth: 0 on CI). Exit: 0 nothing grew unapproved,
1 an entry grew without an approval, 2 usage.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGES_SCRIPT = REPO_ROOT / "scripts" / "ci" / "changes.sh"

LINE_BASELINE_GLOBS = (
    "scripts/ci/baselines/*.txt",
    "tools/lints/*_baseline.txt",
    "apps/api/tests/meta/*_baseline.txt",
)
ALLOWLIST_MODULE_GLOB = "tools/lints/*.py"
ALLOWLIST_NAME_MARKER = "ALLOWLIST"
DEFERRAL_PREFIX = "deferred-until="
SCORE_FLOOR = re.compile(r"^(?P<key>score:[^=]+)=(?P<score>\d+)$")
APPROVAL = re.compile(
    r"^#:?\s*growth approved by (?P<approver>[A-Za-z0-9-]+) on (?P<date>\d{4}-\d{2}-\d{2}): (?P<reason>\S.*)$"
)
APPROVAL_FORMAT = "# growth approved by <github-login> on YYYY-MM-DD: <reason>"


@dataclass(frozen=True)
class Entry:
    """One baseline entry; slack grows as the entry loosens (0 for a plain fact)."""

    key: str
    line: int
    slack: int
    shown: str


@dataclass(frozen=True)
class Growth:
    path: str
    entry: Entry
    was: Entry | None

    def message(self) -> str:
        if self.was is None:
            return f"new baseline entry `{self.entry.shown}`"
        return f"baseline bound loosened: `{self.was.shown}` -> `{self.entry.shown}`"


def _is_entry_line(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith("#")


def _line_entry(text: str, line: int) -> Entry:
    fields = [field for field in text.strip().split("\t") if not field.startswith(DEFERRAL_PREFIX)]
    key = "\t".join(fields)
    floor = SCORE_FLOOR.match(key)
    if floor:
        return Entry(floor["key"], line, -int(floor["score"]), key)
    return Entry(key, line, 0, key)


def line_entries(source: str) -> list[Entry]:
    """Read a line baseline: one entry per non-blank, non-comment line."""
    return [
        _line_entry(text, number)
        for number, text in enumerate(source.splitlines(), start=1)
        if _is_entry_line(text)
    ]


def _literal(node: ast.expr, path: str) -> object:
    try:
        return ast.literal_eval(node)
    except ValueError as err:
        raise SystemExit(
            f"baselines.py: {path}:{node.lineno} is not a literal ({err}); "
            "an allowlist must be one so its growth can be read"
        ) from err


def _allowlist_values(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    for statement in tree.body:
        target: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
        elif isinstance(statement, ast.AnnAssign):
            target = statement.target
        value = statement.value if isinstance(statement, ast.Assign | ast.AnnAssign) else None
        if (
            not isinstance(target, ast.Name)
            or ALLOWLIST_NAME_MARKER not in target.id
            or value is None
        ):
            continue
        if isinstance(value, ast.Call) and len(value.args) == 1 and not value.keywords:
            value = value.args[0]
        yield target.id, value


def allowlist_entries(source: str, path: str) -> dict[str, list[Entry]]:
    """Read every module-level *ALLOWLIST* literal, by name; a dict's int value is a ceiling."""
    allowlists: dict[str, list[Entry]] = {}
    for name, value in _allowlist_values(ast.parse(source, filename=path)):
        entries: list[Entry] = []
        if isinstance(value, ast.Dict):
            for key_node, value_node in zip(value.keys, value.values, strict=True):
                if key_node is None:
                    raise SystemExit(
                        f"baselines.py: {path}:{value.lineno} {name} unpacks a mapping"
                    )
                key = repr(_literal(key_node, path))
                bound = _literal(value_node, path)
                if isinstance(bound, int) and not isinstance(bound, bool):
                    entries.append(
                        Entry(f"{name}[{key}]", key_node.lineno, bound, f"{key}: {bound}")
                    )
                else:
                    shown = f"{key}: {bound!r}"
                    entries.append(Entry(f"{name}[{shown}]", key_node.lineno, 0, shown))
        elif isinstance(value, ast.Set | ast.List | ast.Tuple):
            for element in value.elts:
                shown = repr(_literal(element, path))
                entries.append(Entry(f"{name}[{shown}]", element.lineno, 0, shown))
        else:
            raise SystemExit(
                f"baselines.py: {path}:{value.lineno} {name} is not a set, list, tuple or dict"
            )
        allowlists[name] = entries
    return allowlists


def _approvals_above(lines: list[str], index: int, base_comments: set[str]) -> bool:
    """Whether the comment block ending at lines[index] holds an approval new to this change."""
    while index >= 0 and lines[index].strip().startswith("#"):
        comment = lines[index].strip()
        match = APPROVAL.match(comment)
        if match and comment not in base_comments:
            try:
                date.fromisoformat(match["date"])
            except ValueError as err:
                raise SystemExit(
                    f"baselines.py: approval {comment!r} has no valid date ({err})"
                ) from err
            return True
        index -= 1
    return False


def approved(
    lines: list[str], entry: Entry, base_comments: set[str], *, skip_entry_run: bool
) -> bool:
    """Whether an approval sits above the entry, or above the run of entry lines it belongs to."""
    index = entry.line - 2
    if skip_entry_run:
        while index >= 0 and _is_entry_line(lines[index]):
            index -= 1
    return _approvals_above(lines, index, base_comments)


def grown(base: list[Entry], head: list[Entry]) -> Iterator[tuple[Entry, Entry | None]]:
    """Yield each head entry that is new, or looser than its base entry, with that base entry."""
    before = {entry.key: entry for entry in base}
    for entry in head:
        was = before.get(entry.key)
        if was is None:
            yield entry, None
        elif entry.slack > was.slack:
            yield entry, was


def _comments(source: str) -> set[str]:
    return {text.strip() for text in source.splitlines() if text.strip().startswith("#")}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed git argv, no shell
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def resolve_base(root: Path, rev: str | None) -> str:
    """Return the commit to compare against: rev, else the merge-base with changes.sh base-rev."""
    if rev:
        return _git(root, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()
    base_rev = subprocess.run(  # nosec B603 B607 - fixed repo script argv, no shell
        ["bash", str(CHANGES_SCRIPT), "base-rev"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return _git(root, "merge-base", base_rev, "HEAD").strip()


def _growth_in(
    path: str,
    head_source: str,
    base_source: str,
    read: Callable[[str, str], dict[str, list[Entry]]],
    *,
    skip_entry_run: bool,
) -> list[Growth]:
    head_lines = head_source.splitlines()
    base_comments = _comments(base_source)
    base_groups = read(base_source, path)
    found: list[Growth] = []
    for name, head_entries in read(head_source, path).items():
        if name not in base_groups:
            continue
        for entry, was in grown(base_groups[name], head_entries):
            if not approved(head_lines, entry, base_comments, skip_entry_run=skip_entry_run):
                found.append(Growth(path, entry, was))
    return found


def _read_lines(source: str, _path: str) -> dict[str, list[Entry]]:
    return {"": line_entries(source)}


def find_growth(root: Path, base: str) -> list[Growth]:
    """Return every unapproved growth in the working tree's baselines against base."""
    at_base = set(_git(root, "ls-tree", "-r", "--name-only", base).splitlines())
    found: list[Growth] = []
    kinds: list[tuple[tuple[str, ...], Callable[[str, str], dict[str, list[Entry]]], bool]] = [
        (LINE_BASELINE_GLOBS, _read_lines, True),
        ((ALLOWLIST_MODULE_GLOB,), allowlist_entries, False),
    ]
    for globs, read, skip_entry_run in kinds:
        for pattern in globs:
            for file in sorted(root.glob(pattern)):
                path = file.relative_to(root).as_posix()
                if path not in at_base:
                    continue
                base_source = _git(root, "show", f"{base}:{path}")
                found += _growth_in(
                    path,
                    file.read_text(encoding="utf-8"),
                    base_source,
                    read,
                    skip_entry_run=skip_entry_run,
                )
    return found


def cmd_growth(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="baselines.py growth")
    parser.add_argument("--base", help="revision to compare against (default: the PR's merge-base)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    base = resolve_base(args.root, args.base)
    found = find_growth(args.root, base)
    for growth in found:
        print(
            f"::error file={growth.path},line={growth.entry.line}::{growth.message()} "
            f"-- fix the violation instead; only on the founder's explicit approval, "
            f"write `{APPROVAL_FORMAT}` directly above it"
        )
    if found:
        print(f"baseline-growth: {len(found)} unapproved baseline growth(s) against {base[:12]}")
        return 1
    print(f"baseline-growth: no baseline grew against {base[:12]}")
    return 0


COMMANDS: dict[str, Callable[[list[str]], int]] = {"growth": cmd_growth}


def main(argv: list[str]) -> int:
    """Dispatch to a subcommand; exit 2 with the usage on an unknown one."""
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: baselines.py {{{'|'.join(COMMANDS)}}} [args]", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
