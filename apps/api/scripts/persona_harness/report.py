"""Per-run timeline + assertion bookkeeping for the persona thrash harness.

Every step a persona script takes appends a verbatim timeline entry (sim-day,
actor, surface, content); every check goes through ``Report.expect`` so a
failure carries a readable expected-vs-found diff instead of a bare
``AssertionError``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPORT_DIR = Path("/Users/aryan/Downloads/gaia-week-reports")


class AssertionFailure(AssertionError):
    """An assertion failure carrying an expected/found diff for the report."""

    def __init__(self, description: str, *, expected: object, found: object) -> None:
        self.description = description
        self.expected = expected
        self.found = found
        super().__init__(f"{description}\n  expected: {expected!r}\n  found:    {found!r}")


@dataclass
class TimelineEntry:
    sim_day: int
    actor: str
    surface: str
    content: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Report:
    """Accumulates one persona run's timeline and assertion results."""

    persona: str
    timeline: list[TimelineEntry] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def record(self, *, sim_day: int, actor: str, surface: str, content: str) -> None:
        entry = TimelineEntry(sim_day=sim_day, actor=actor, surface=surface, content=content)
        self.timeline.append(entry)

    def expect(
        self, cond: bool, description: str, *, expected: object = None, found: object = None
    ) -> None:
        """Assert ``cond``. Records the outcome either way; raises on failure."""
        if cond:
            self.passed.append(description)
            return
        self.failed.append(description)
        raise AssertionFailure(description, expected=expected, found=found)

    def observe(self, cond: bool, description: str) -> bool:
        """Like ``expect`` but never raises — for a capstone run that must
        keep going (and still show the miss in the report) past a step
        already covered by a dedicated persona's hard assertion elsewhere.
        Returns ``cond`` so the caller can still branch on it."""
        (self.passed if cond else self.failed).append(description)
        return cond

    @property
    def status(self) -> str:
        """PASS / FAIL / INCONCLUSIVE.

        A run that asserted nothing cannot have proven anything — reporting it
        as PASS is how a silently-skipped scenario hides forever. It is called
        out as INCONCLUSIVE and treated as a failure by the runner's exit code.
        """
        if self.failed:
            return "FAIL"
        return "PASS" if self.passed else "INCONCLUSIVE"

    def render_markdown(self) -> str:
        status = self.status
        lines = [
            f"# {self.persona} — persona thrash report",
            "",
            f"**Result: {status}** — {len(self.passed)} assertion(s) passed"
            + (f", {len(self.failed)} failed" if self.failed else ""),
            "",
            "## Timeline",
            "",
        ]
        for entry in self.timeline:
            ts = entry.at.strftime("%H:%M:%S")
            lines.append(f"- **day {entry.sim_day}** `{ts}` `{entry.actor}` via `{entry.surface}`")
            for line in entry.content.splitlines() or [""]:
                lines.append(f"  > {line}")
        lines += ["", "## Assertions", ""]
        for description in self.passed:
            lines.append(f"- [x] {description}")
        for description in self.failed:
            lines.append(f"- [ ] **FAILED** — {description}")
        return "\n".join(lines) + "\n"

    def write(self, filename: str | None = None) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / (filename or f"{self.persona}_report.md")
        path.write_text(self.render_markdown())
        return path
