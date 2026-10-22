#!/usr/bin/env python3
"""Clear (or preview clearing) user names that signup guessed from the email address.

From 2026-09-17 a signup without a name stored one derived from the email's
local part (aryan.randeriya@x.com became "Aryan Randeriya"), and GAIA then
greeted people by it. Signup no longer guesses, so a user without a name has
none; this one-off clears the guesses already stored. A name is cleared only
when it is exactly the derivation of that user's email, and only while it still
is at write time, so a name the user set in settings survives. A user whose real
name happens to equal the derivation gets it back on their next login that
carries one.

Run from the api directory (or /app inside the container):

    python scripts/clear_email_derived_names.py --dry-run
    python scripts/clear_email_derived_names.py --apply

Flags:
--dry-run  Report the users whose name would be cleared. Default.
--apply    Actually clear them. Required to write anything.
--limit N  Only list the first N users in the report (the totals stay complete).
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.repositories.users import user_repository

# The derivation signup used: . _ - separate words, trailing digits ("john.doe83") are dropped.
_LOCAL_PART_WORD_SPLIT = re.compile(r"[._\-]+")
_TRAILING_DIGITS = re.compile(r"\d+$")


def derive_name_from_email(email: str) -> str:
    """Return the name signup derived from an email's local part, plus-tag dropped.

    When nothing presentable survives (all digits, empty local part) it was the
    raw local part.
    """
    local_part = email.partition("@")[0].strip()
    words = [
        stripped.capitalize()
        for word in _LOCAL_PART_WORD_SPLIT.split(local_part.partition("+")[0])
        if (stripped := _TRAILING_DIGITS.sub("", word))
    ]
    return " ".join(words) if words else local_part


@dataclass(frozen=True)
class DerivedName:
    """One user whose stored name is the guess from their email."""

    user_id: str
    name: str


@dataclass
class CleanupResult:
    """What one run found and, when applied, changed."""

    dry_run: bool
    scanned: int = 0
    candidates: list[DerivedName] = field(default_factory=list)
    cleared: int = 0
    changed_since_scan: int = 0


async def clear_email_derived_names(*, dry_run: bool) -> CleanupResult:
    """Find every name equal to its email's derivation and, unless dry_run, clear it."""
    users = await user_repository.find_named_with_email()
    result = CleanupResult(dry_run=dry_run, scanned=len(users))
    result.candidates = [
        DerivedName(user_id=user.id, name=user.name)
        for user in users
        if user.name and user.email and user.name == derive_name_from_email(user.email)
    ]
    if dry_run:
        return result
    for candidate in result.candidates:
        if await user_repository.clear_name_if_unchanged(candidate.user_id, candidate.name):
            result.cleared += 1
        else:
            result.changed_since_scan += 1
    return result


def _render(result: CleanupResult, limit: int) -> None:
    print(f"\n{'DRY RUN — nothing was written' if result.dry_run else 'APPLIED'}")
    print(f"users with a name and an email:  {result.scanned}")
    print(f"names derived from the email:    {len(result.candidates)}")
    if not result.dry_run:
        print(f"names cleared:                   {result.cleared}")
        print(f"changed since the scan, kept:    {result.changed_since_scan}")
    if not result.candidates:
        print("\nNothing to do.")
        return
    print(f"\n{'user_id':<28}name")
    for candidate in result.candidates[:limit]:
        print(f"{candidate.user_id:<28}{candidate.name}")
    if len(result.candidates) > limit:
        print(f"... and {len(result.candidates) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so `--apply --dry-run` is rejected instead of silently applying.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="actually clear the names")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--limit", type=int, default=25, help="users to list in the report")
    args = parser.parse_args()

    result = await clear_email_derived_names(dry_run=not args.apply)
    _render(result, args.limit)

    if not args.apply:
        print("\nRe-run with --apply to clear these names.")


if __name__ == "__main__":
    asyncio.run(main())
