"""The ratchet on response fields that generate unknown in the TypeScript.

The route-level check only saw the outermost annotation, so a typed response
model could still hand every consumer a dict[str, Any] field to cast. This walks
the whole tree; fields already loose when the walk was added are listed, each
with a dated deferral, in untyped_response_fields_baseline.txt. A new one is
never grandfathered: type the field, or argue for a line in that file.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.routing import APIRoute, RouteContext
import pytest

from tests.meta.response_types import walk_response

BASELINE = Path(__file__).with_name("untyped_response_fields_baseline.txt")
DEFERRAL_PREFIX = "deferred-until="


@dataclass(frozen=True)
class Deferral:
    """A reviewed, dated exemption carried on one baseline line."""

    until: date
    reason: str


def _parse_deferral(field: str, line: str) -> Deferral:
    if not field.startswith(DEFERRAL_PREFIX) or "; " not in field:
        raise AssertionError(
            f"malformed deferral in {BASELINE.name}: {line!r} "
            f"(expected '{DEFERRAL_PREFIX}YYYY-MM-DD; <reason>')"
        )
    until, reason = field.removeprefix(DEFERRAL_PREFIX).split("; ", 1)
    return Deferral(date.fromisoformat(until), reason)


@pytest.fixture(scope="module")
def baseline() -> dict[str, Deferral | None]:
    entries: dict[str, Deferral | None] = {}
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, *rest = line.split("\t")
        entries[path] = _parse_deferral(rest[0], line) if rest else None
    return entries


@pytest.fixture(scope="module")
def untyped(routes: list[RouteContext]) -> set[str]:
    found: set[str] = set()
    for ctx in routes:
        route = ctx.original_route
        assert isinstance(route, APIRoute)
        if route.response_model is not None:
            found |= walk_response(route.response_model, _label(ctx)).untyped
    return found


def _label(ctx: RouteContext) -> str:
    route = ctx.original_route
    assert isinstance(route, APIRoute)
    return f"{','.join(sorted(route.methods))} {ctx.path} ({route.name})"


def test_no_new_untyped_response_field(
    untyped: set[str], baseline: dict[str, Deferral | None]
) -> None:
    """A field the baseline does not already carry may not export as unknown."""
    new = sorted(untyped - baseline.keys())
    assert new == [], (
        "response fields that generate `unknown` for every TypeScript consumer — give the "
        "field a real type (a model, an enum, dict[str, <type>]):\n  " + "\n  ".join(new)
    )


def test_every_grandfathered_field_is_still_untyped(
    untyped: set[str], baseline: dict[str, Deferral | None]
) -> None:
    """A fixed field leaves the baseline, so the list can only shrink."""
    stale = sorted(baseline.keys() - untyped)
    assert stale == [], (
        f"these fields are typed now — delete their lines from {BASELINE.name} so the "
        "ratchet keeps them typed:\n  " + "\n  ".join(stale)
    )


def test_no_deferral_has_expired(baseline: dict[str, Deferral | None]) -> None:
    """A deferral is a dated promise; past its date the debt is due."""
    today = datetime.now(tz=UTC).date()
    expired = sorted(
        f"{path} (expired {deferral.until.isoformat()}): {deferral.reason}"
        for path, deferral in baseline.items()
        if deferral is not None and deferral.until <= today
    )
    assert expired == [], (
        f"expired deferrals in {BASELINE.name} — type the field, or renew the line with a "
        "fresh date and the reason it is still open:\n  " + "\n  ".join(expired)
    )


def test_every_baseline_entry_carries_a_deferral(baseline: dict[str, Deferral | None]) -> None:
    """An undated entry is a permanent exemption, which is what this file exists to prevent."""
    undated = sorted(path for path, deferral in baseline.items() if deferral is None)
    assert undated == [], (
        f"baseline lines with no '{DEFERRAL_PREFIX}YYYY-MM-DD; <reason>' field:\n  "
        + "\n  ".join(undated)
    )
