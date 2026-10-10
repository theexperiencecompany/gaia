"""The touch-to-fix ratchet the baseline-carrying lints share.

A violation is allowed only if it is (a) already in the rule's checked-in
baseline AND (b) its file is not touched by the current PR. Touch a
grandfathered file and its known violations stop being free -- fix them in the
same PR, same as any other lint failure. A genuinely new violation (new file,
or a rule the file didn't already have) is never grandfathered, touched or not.

The one escape hatch is explicit, reviewed and expiring: a baseline line may
carry a third field, ``deferred-until=YYYY-MM-DD; <reason>``. While the date
is in the future, touching that file emits a ``::warning`` annotation naming
the deferral instead of failing; once it has passed, the touched file fails
with "deferral expired" until the violation is fixed or the deferral renewed
with a fresh reason. ``--update`` preserves deferral fields.

Each rule supplies its own scan (``current`` -- every (file, rule) violation
right now, mapped to its first line), its baseline path and header, and the
wording of its "new violation" remediation. Stdlib only, like the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
import subprocess

from _common import Violation, report_rule

FULL_SENTINEL = "__FULL__"
DEFERRAL_PREFIX = "deferred-until="

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
CHANGES_SCRIPT = REPO_ROOT / "scripts" / "ci" / "changes.sh"


@dataclass(frozen=True)
class Deferral:
    """A reviewed, dated exemption carried on one baseline line."""

    until: date
    reason: str

    @classmethod
    def parse(cls, rule: str, baseline: Path, field: str, line: str) -> Deferral:
        if not field.startswith(DEFERRAL_PREFIX) or "; " not in field:
            raise SystemExit(
                f"{rule}: malformed deferral in {baseline.name}: {line!r} "
                f"(expected '{DEFERRAL_PREFIX}YYYY-MM-DD; <reason>')"
            )
        until, reason = field.removeprefix(DEFERRAL_PREFIX).split("; ", 1)
        return cls(date.fromisoformat(until), reason)

    def __str__(self) -> str:
        return f"{DEFERRAL_PREFIX}{self.until.isoformat()}; {self.reason}"


Baseline = dict[tuple[str, str], Deferral | None]
Current = dict[tuple[str, str], int]


def touched_files() -> set[str] | None:
    """Files this PR changed, or ``None`` on a full/push scan (no diff to check)."""
    proc = subprocess.run(  # nosec B603 - fixed repo script argv, no shell
        [str(CHANGES_SCRIPT), "files", "py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line for line in proc.stdout.splitlines() if line]
    if lines == [FULL_SENTINEL]:
        return None
    return set(lines)


def read_baseline(rule: str, baseline: Path) -> Baseline:
    if not baseline.exists():
        return {}
    entries: Baseline = {}
    for raw in baseline.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, name, *rest = line.split("\t")
        entries[(path, name)] = Deferral.parse(rule, baseline, rest[0], line) if rest else None
    return entries


def write_baseline(baseline: Path, header: str, entries: Baseline) -> None:
    lines = []
    for (path, name), deferral in sorted(entries.items()):
        lines.append(f"{path}\t{name}" + (f"\t{deferral}" if deferral else ""))
    baseline.write_text(f"{header}{chr(10).join(lines)}\n", encoding="utf-8")


def _touched_debt(baseline: Baseline, touched: set[str], current: Current) -> set[tuple[str, str]]:
    """Grandfathered violations the PR touched and must fix now.

    A live deferral keeps its entry out of the result and surfaces it as a
    workflow warning instead, so the debt stays visible on every run.
    """
    today = datetime.now(tz=UTC).date()
    must_fix_now: set[tuple[str, str]] = set()
    for (path, name), deferral in baseline.items():
        if path not in touched or (path, name) not in current:
            continue
        if deferral is not None and deferral.until > today:
            print(
                f"::warning file={path},line={current[(path, name)]}::"
                f"{name} deferred until {deferral.until.isoformat()} -- {deferral.reason}"
            )
            continue
        must_fix_now.add((path, name))
    return must_fix_now


def _remediation(
    baseline: Path, *, is_new: bool, deferral: Deferral | None, fix_new: str
) -> tuple[str, str]:
    """Return the label and fix text for one failure, by how it came to fail."""
    relative = baseline.relative_to(REPO_ROOT).as_posix()
    if is_new:
        return "new", (
            f"{fix_new}, or if it's a genuine one-off, justify it in review "
            f"and add it to {relative} with --update"
        )
    if deferral is not None:
        return f"touched, deferral expired {deferral.until.isoformat()}", (
            "deferral expired -- fix or renew with a reason: update the "
            f"deferred-until field on this line of {relative}"
        )
    return "touched, grandfathered", (
        "this file is grandfathered for this rule, but this PR touches it -- "
        f"fix the violation now and delete its line from {relative}"
    )


@dataclass(frozen=True)
class RatchetRule:
    """What one baseline-carrying lint contributes to the shared mechanics."""

    name: str
    why: str
    doc: str
    baseline: Path
    header: str
    script: str  # how to invoke it, for the --update hint
    fix_new: str  # the remediation for a violation the baseline never knew


def run_ratchet(rule: RatchetRule, current: Current, argv: list[str]) -> int:
    """Check ``current`` against the baseline (or rewrite it with ``--update``)."""
    current_keys = set(current)

    if "--update" in argv:
        previous = read_baseline(rule.name, rule.baseline)
        write_baseline(rule.baseline, rule.header, {key: previous.get(key) for key in current_keys})
        print(
            f"{rule.name}: baseline updated -- {len(current_keys)} known violation(s) "
            f"(+{len(current_keys - previous.keys())} / -{len(previous.keys() - current_keys)}). "
            "Commit the diff so the change is reviewable."
        )
        return 0

    baseline = read_baseline(rule.name, rule.baseline)
    touched = touched_files()

    unexpected = current_keys - baseline.keys()
    must_fix_now = _touched_debt(baseline, touched, current) if touched is not None else set()

    failures = unexpected | must_fix_now
    if failures:
        violations = []
        for path, name in sorted(failures):
            label, fix = _remediation(
                rule.baseline,
                is_new=(path, name) in unexpected,
                deferral=baseline.get((path, name)),
                fix_new=rule.fix_new,
            )
            violations.append(
                Violation(
                    path=Path(path),
                    line=current.get((path, name), 0),
                    detail=f"{name} ({label})",
                    fix=fix,
                )
            )
        report_rule(rule.name, rule.why, rule.doc, violations)
        return 1

    fixed = baseline.keys() - current_keys
    if fixed:
        print(f"{rule.name}: {len(fixed)} grandfathered violation(s) no longer present -- nice.")
        for path, name in sorted(fixed):
            print(f"  - {path} ({name})")
        print(f"  Lock the win in with: python3 {rule.script} --update")

    print(f"{rule.name}: {len(current_keys)} current violation(s), all grandfathered and untouched")
    return 0
