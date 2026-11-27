"""Read-only access to the source MongoDB: a login that can write is refused before any read."""

import os
from typing import Any, TypeAlias

from pymongo import MongoClient
from pymongo.database import Database

SOURCE_URI_ENV = "MIGRATION_SOURCE_MONGO_URI"
SOURCE_DB_ENV = "MIGRATION_SOURCE_DB"
DEFAULT_SOURCE_DB = "GAIA"
READ_ONLY_ROLES = frozenset({"read", "readAnyDatabase"})
APP_NAME = "gaia-db-migration"

RawDocument: TypeAlias = dict[str, Any]


class SourceConfigError(RuntimeError):
    """The source connection is not configured."""


class WritableSourceError(RuntimeError):
    """The source login holds a role that can write."""


def connect_read_only() -> Database[RawDocument]:
    """Open the source database, refusing any login whose roles go beyond read."""
    uri = os.environ.get(SOURCE_URI_ENV)
    if not uri:
        raise SourceConfigError(f"{SOURCE_URI_ENV} is not set")
    client: MongoClient[RawDocument] = MongoClient(
        uri, appname=APP_NAME, readPreference="secondaryPreferred"
    )
    status = client.admin.command("connectionStatus")
    roles = {role["role"] for role in status["authInfo"]["authenticatedUserRoles"]}
    if not roles or not roles <= READ_ONLY_ROLES:
        client.close()
        raise WritableSourceError(
            f"source login has roles {sorted(roles) or ['<none>']}; only {sorted(READ_ONLY_ROLES)} allowed"
        )
    return client[os.environ.get(SOURCE_DB_ENV, DEFAULT_SOURCE_DB)]
