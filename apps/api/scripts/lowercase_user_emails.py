#!/usr/bin/env python3
"""One-time migration: store every user's email in its canonical lowercase form.

Sign-in, billing and last-active lookups now lowercase the address before reading
(app.utils.email_utils.canonical_email), so a row stored as "Aryan@X.com" is no
longer found. This rewrites such rows to lowercase. Two rows whose emails differ
only in case are one person with two accounts: they are reported and left alone,
since merging accounts is a decision for a human, not a script.

Run from the api directory (or /app inside the container), BEFORE deploying the
change that lowercases lookups:

    python scripts/lowercase_user_emails.py            # dry run, prints the plan
    python scripts/lowercase_user_emails.py --apply    # lowercases the safe rows

Safely re-runnable: a row already in lowercase is skipped. The write goes straight
to the collection; cached user documents are unaffected because UserDocument already
lowercases the address it reads.
"""

import argparse
import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import sys

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.utils.email_utils import canonical_email

USERS_COLLECTION = "users"


@dataclass(frozen=True)
class StoredEmail:
    """One user row's id and email exactly as stored."""

    user_id: str
    email: str


@dataclass(frozen=True)
class Plan:
    """Rows safe to lowercase, and groups of rows that are one address in different cases."""

    lowercase: list[StoredEmail]
    collisions: dict[str, list[StoredEmail]]


def build_plan(rows: Iterable[StoredEmail]) -> Plan:
    """Split stored emails into safe rewrites and case-insensitive duplicates; writes nothing."""
    by_canonical: dict[str, list[StoredEmail]] = defaultdict(list)
    for row in rows:
        by_canonical[canonical_email(row.email)].append(row)
    lowercase: list[StoredEmail] = []
    collisions: dict[str, list[StoredEmail]] = {}
    for address, group in sorted(by_canonical.items()):
        if len(group) > 1:
            collisions[address] = group
        elif group[0].email != address:
            lowercase.append(group[0])
    return Plan(lowercase=lowercase, collisions=collisions)


async def read_stored_emails() -> list[StoredEmail]:
    """Return every user row that has a string email."""
    cursor = get_async_collection(USERS_COLLECTION).find(
        {"email": {"$type": "string"}}, {"email": 1}
    )
    return [StoredEmail(user_id=str(doc["_id"]), email=doc["email"]) async for doc in cursor]


async def apply_plan(plan: Plan) -> int:
    """Lowercase each safe row, only if it still holds the email the plan read; return rows written."""
    collection = get_async_collection(USERS_COLLECTION)
    written = 0
    for row in plan.lowercase:
        result = await collection.update_one(
            {"_id": ObjectId(row.user_id), "email": row.email},
            {"$set": {"email": canonical_email(row.email)}},
        )
        written += result.modified_count
    return written


def _render(plan: Plan, *, written: int | None) -> None:
    print("\nDRY RUN, nothing was written" if written is None else f"\nAPPLIED, {written} rows")
    print(f"mixed-case emails safe to lowercase: {len(plan.lowercase)}")
    for row in plan.lowercase:
        print(f"  {row.user_id:<26}{row.email}")
    print(f"addresses held by more than one account (left alone): {len(plan.collisions)}")
    for address, group in plan.collisions.items():
        print(f"  {address}")
        for row in group:
            print(f"    {row.user_id:<26}{row.email}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="lowercase the non-colliding rows")
    args = parser.parse_args()

    plan = build_plan(await read_stored_emails())
    written = await apply_plan(plan) if args.apply else None
    _render(plan, written=written)
    if written is None:
        print("\nRe-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
