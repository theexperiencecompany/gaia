"""Mongo ground truth for analytics_ops, through a URI the caller exports; nothing here writes."""

from __future__ import annotations

import os

from pymongo import MongoClient
from pymongo.database import Database

from app.db.mongodb.mongodb import MONGO_DATABASE_NAME

MONGO_URI_ENV = "ANALYTICS_MONGO_URI"
APP_NAME = "gaia-analytics-ops"

# Mongo documents are untyped BSON; each reader projects only the fields it names.
Document = dict[str, object]


def ground_truth_db() -> Database[Document]:
    """Return the app database at ANALYTICS_MONGO_URI; exit 1 naming the variable when it is unset.

    Prod reads use the read-only user whose credentials live in the macOS
    Keychain item gaia-prod-mongo-ro: build the URI in the shell, never in a file.
    """
    uri = os.environ.get(MONGO_URI_ENV)
    if not uri:
        raise SystemExit(
            f"{MONGO_URI_ENV} is not set. Export a read-only Mongo URI: local is "
            "mongodb://localhost:27017; for prod, take the password from the Keychain item "
            "gaia-prod-mongo-ro (security find-generic-password -s gaia-prod-mongo-ro -w)."
        )
    client: MongoClient[Document] = MongoClient(uri, appname=APP_NAME, tz_aware=True)
    return client[MONGO_DATABASE_NAME]
