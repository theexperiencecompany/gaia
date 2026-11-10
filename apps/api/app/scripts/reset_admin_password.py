#!/usr/bin/env python3
"""Give the self-host administrator a new password when they are locked out.

Only the administrator's auth_credentials row changes: a new password hash,
and a bumped token_version that signs out every existing session. The account,
its data and every member are untouched. The new password is printed once;
sign in with it, then change it in Settings.

Usage (on the host that runs GAIA)::

    docker compose -p gaia-selfhost exec gaia-backend python -m app.scripts.reset_admin_password
"""

from __future__ import annotations

import argparse
import secrets
import sys
from typing import Protocol

from pymongo import MongoClient

from app.config.settings import settings
from app.constants.auth import RESET_PASSWORD_TOKEN_BYTES
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.db.repositories.local_credentials import LocalCredentialsRepository
from app.models.auth_models import ADMIN_CREDENTIAL_SLOT
from app.utils.password_hashing import hash_password

_ADMIN_FILTER: dict[str, object] = {"slot": ADMIN_CREDENTIAL_SLOT}


class CredentialCollection(Protocol):
    """The two auth_credentials calls the reset makes."""

    def find_one(self, filter_: dict[str, object], /) -> object | None: ...

    def update_one(self, filter_: dict[str, object], update: dict[str, object], /) -> object: ...


def reset_admin_credential(credentials: CredentialCollection) -> str | None:
    """Set a new random admin password and revoke every admin session; None without an admin."""
    if credentials.find_one(_ADMIN_FILTER) is None:
        return None
    password = secrets.token_urlsafe(RESET_PASSWORD_TOKEN_BYTES)
    password_hash = hash_password(password)
    credentials.update_one(
        _ADMIN_FILTER,
        {"$set": {"password_hash": password_hash}, "$inc": {"token_version": 1}},
    )
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    if not settings.MONGO_DB:
        print("MONGO_DB is not configured", file=sys.stderr)
        sys.exit(1)

    client: MongoClient[dict[str, object]] = MongoClient(settings.MONGO_DB)
    password = reset_admin_credential(
        client[MONGO_DATABASE_NAME].get_collection(LocalCredentialsRepository.collection_name)
    )
    if password is None:
        print("No admin account found — create one at /signup")
        return
    print(f"New admin password: {password}")
    print("Every admin session was signed out. Sign in with it, then change it in Settings.")


if __name__ == "__main__":
    main()
