#!/usr/bin/env python3
"""Reset the self-host admin account so a new one can be created.

Deletes every document in ``auth_credentials`` (the single-admin slot).
After running, visit ``/signup`` to create a new administrator.

Usage (on the host that runs GAIA)::

    docker exec gaia-backend python -m app.scripts.reset_admin_password
    docker compose exec api python -m app.scripts.reset_admin_password
    # or inside the API container
    python -m app.scripts.reset_admin_password

Alternative direct-Mongo form (no script)::

    docker exec mongo mongosh --eval 'db.getSiblingDB("GAIA").auth_credentials.deleteMany({})'

Then open ``/signup``. If signup says the email is already taken (the
``users`` row still exists from the previous admin), either sign up with a
different email or remove the old user row:

    docker exec mongo mongosh --eval 'db.getSiblingDB("GAIA").users.deleteMany({})'
"""

from __future__ import annotations

import argparse
import sys

from pymongo import MongoClient

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME


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

    client: MongoClient[dict] = MongoClient(settings.MONGO_DB)
    db = client[MONGO_DATABASE_NAME]
    count = db["auth_credentials"].count_documents({})

    if count == 0:
        print("No admin account found — you can already sign up at /signup")
        return

    if args.dry_run:
        print(f"Would delete {count} admin credential(s) from auth_credentials (dry-run)")
        print("Run without --dry-run to delete and then visit /signup to create a new admin.")
        return

    # Capture user_ids before deleting so we can clean up orphaned users
    # (otherwise signup with the same email is blocked by the existing-identity gate).
    user_ids = [
        doc.get("user_id")
        for doc in db["auth_credentials"].find({}, {"user_id": 1})
        if doc.get("user_id")
    ]

    result = db["auth_credentials"].delete_many({})
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
                deleted_users = db["users"].delete_many({"_id": {"$in": object_ids}}).deleted_count
                if deleted_users:
                    print(f"Also removed {deleted_users} associated user(s).")
        except Exception as exc:  # pragma: no cover
            print(f"Note: could not clean up users collection: {exc}", file=sys.stderr)

    print("Visit /signup to create a new admin account.")


if __name__ == "__main__":
    main()
