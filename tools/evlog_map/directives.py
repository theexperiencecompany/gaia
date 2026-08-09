"""Suppression comments — waive a finding with a visible, reasoned decision.

Same contract as evlog's ``evlog-map-disable`` comments: a suppressed check
reports ``n/a`` (never ``pass``) so the map still shows the entry point is not
covered, and the comment records who decided that and why.

    # evlog-map-disable-next-line audit -- covered by WorkOS audit log
    # evlog-map-disable-line audit -- same, on the flagged line itself
    # evlog-map-disable context, error-handling -- proxied request, no context
    # evlog-map-disable -- waive every check in this file

Omitting the check ids waives every check (upstream's bare form). A directive
naming an id no rule runs is surfaced as a warning — a typo must be loud, not
a silent no-op.

The ``--`` reason is mandatory. A directive without one used to waive its
check anyway under the placeholder reason "suppressed without a reason", which
is how a 40-point requirement gets dropped with nobody accountable for it.
Such a directive is now a warning that suppresses nothing, so the check keeps
failing until someone writes down why it should not.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

ALL_CHECKS = "*"

_DIRECTIVE = re.compile(
    r"#\s*evlog-map-disable(?P<scope>-next-line|-line)?"
    r"(?P<ids>[ \t]+[\w\-, \t]*?)?"
    r"(?:--(?P<reason>.*))?$"
)


@dataclass(frozen=True)
class Suppression:
    """One waived check: which, where, and the recorded reason."""

    check_id: str  # a rule id, or ALL_CHECKS for the bare form
    declared_at: int  # 1-indexed line of the comment
    reason: str  # empty when the directive omitted its ``--`` reason
    scope: str  # "file" | "next-line" | "line"


def _split_ids(raw: str | None) -> list[str]:
    ids = [part.strip() for part in re.split(r"[\s,]+", (raw or "").strip()) if part.strip()]
    return ids or [ALL_CHECKS]


def collect_suppressions(source: str) -> list[Suppression]:
    """Every suppression comment in the file, all three scopes."""
    suppressions: list[Suppression] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        match = _DIRECTIVE.search(line)
        if not match:
            continue
        scope = {None: "file", "-next-line": "next-line", "-line": "line"}[match.group("scope")]
        reason = (match.group("reason") or "").strip()
        for check_id in _split_ids(match.group("ids")):
            suppressions.append(
                Suppression(check_id=check_id, declared_at=lineno, reason=reason, scope=scope)
            )
    return suppressions


def find_suppression(
    suppressions: list[Suppression], check_id: str, finding_lines: tuple[int, ...]
) -> Suppression | None:
    """A file-level suppression, or a line-scoped one covering a finding line.

    ``finding_lines`` carries every line the finding may anchor to — the exact
    flagged line, the handler's ``def`` line, and its first decorator's line —
    so the natural lint-style placement above a decorator works too.

    Reasonless directives never match: they are reported by ``missing_reason``
    instead, so the check they name stays failed.
    """
    for suppression in suppressions:
        if not suppression.reason:
            continue
        if suppression.check_id not in (check_id, ALL_CHECKS):
            continue
        if suppression.scope == "file":
            return suppression
        anchored = (
            suppression.declared_at + 1 if suppression.scope == "next-line" else None,
            suppression.declared_at if suppression.scope == "line" else None,
        )
        if any(line in anchored for line in finding_lines):
            return suppression
    return None


def unknown_ids(suppressions: list[Suppression], known: frozenset[str]) -> list[Suppression]:
    """Suppressions naming a check no rule runs — typos that must be loud."""
    return [s for s in suppressions if s.check_id != ALL_CHECKS and s.check_id not in known]


def missing_reason(suppressions: list[Suppression]) -> list[Suppression]:
    """Directives with no ``--`` reason — rejected, one warning per line."""
    seen: set[int] = set()
    out: list[Suppression] = []
    for suppression in suppressions:
        if suppression.reason or suppression.declared_at in seen:
            continue
        seen.add(suppression.declared_at)
        out.append(suppression)
    return out
