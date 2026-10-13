#!/usr/bin/env python3
"""Reset the self-host admin account so a new one can be created.

Deletes the administrator's ``auth_credentials`` row (slot=admin) and its user
row; member accounts are untouched. After running, visit ``/signup`` to create
a new administrator.

Usage (on the host that runs GAIA)::

    docker exec gaia-backend python -m app.scripts.reset_admin_password
    docker compose exec api python -m app.scripts.reset_admin_password
    # or inside the API container
    python -m app.scripts.reset_admin_password
"""

from __future__ import annotations

import argparse
import sys
from typing import TypedDict

from pymongo import MongoClient

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.models.auth_models import ADMIN_CREDENTIAL_SLOT


class StoredCredential(TypedDict):
    """One ``auth_credentials`` row, narrowed to the field this script reads.

    The projection below asks Mongo for ``user_id`` alone, and that field is the
    only one every row carries (``LocalCredentialsRepository`` writes it), so
    the raw BSON mapping is named here rather than read key-by-key with no
    declared shape.
    """

    user_id: str


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting",
    )
    args = parser.parse_args()

    if not settings.MONGO_DB:
        print("MONGO_DB is not configured", file=sys.stderr)
        sys.exit(1)

    client: MongoClient[dict[str, object]] = MongoClient(settings.MONGO_DB)
    db = client[MONGO_DATABASE_NAME]
    credentials = db.get_collection("auth_credentials")
    admin_filter = {"slot": ADMIN_CREDENTIAL_SLOT}
    count = credentials.count_documents(admin_filter)

    if count == 0:
        print("No admin account found — you can already sign up at /signup")
        return

    if args.dry_run:
        print(f"Would delete {count} admin credential(s) from auth_credentials (dry-run)")
        print("Run without --dry-run to delete and then visit /signup to create a new admin.")
        return

    # Capture user_ids before deleting so we can clean up orphaned users
    # (otherwise signup with the same email is blocked by the existing-identity gate).
    # Materialised before the delete, exactly as the lazy cursor was.
    rows: list[StoredCredential] = [*credentials.find(admin_filter, {"user_id": 1})]
    user_ids = [row["user_id"] for row in rows if row.get("user_id")]

    result = credentials.delete_many(admin_filter)
    print(f"Deleted {result.deleted_count} admin credential(s).")

    if user_ids:
        # The users collection uses ObjectId _ids; user_ids from auth_credentials
        # are string ObjectIds — convert best-effort. A failure here is non-fatal;
        # the credential slot is already free and signup with a different email works.
        try:
            from bson import ObjectId

            object_ids = []
            for uid in user_ids:
                try:
                    object_ids.append(ObjectId(uid))
                except Exception:
                    continue
            if object_ids:
                deleted_users = (
                    db.get_collection("users")
                    .delete_many({"_id": {"$in": object_ids}})
                    .deleted_count
                )
                if deleted_users:
                    print(f"Also removed {deleted_users} associated user(s).")
        except Exception as exc:  # pragma: no cover
            print(f"Note: could not clean up users collection: {exc}", file=sys.stderr)

    print("Visit /signup to create a new admin account.")


if __name__ == "__main__":
    main()
