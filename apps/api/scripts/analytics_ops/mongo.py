"""Mongo ground truth for analytics_ops, through a URI the caller exports; nothing here writes."""

from __future__ import annotations

import os

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.uri_parser import split_hosts

from app.db.mongodb.mongodb import MONGO_DATABASE_NAME

from .posthog_api import TargetName

MONGO_URI_ENV = "ANALYTICS_MONGO_URI"
# The hosts a local stack's Mongo answers on: the shell, and the compose service name.
LOCAL_MONGO_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "mongo", "mongodb"})
APP_NAME = "gaia-analytics-ops"

# Mongo documents are untyped BSON; each reader projects only the fields it names.
Document = dict[str, object]


def mongo_uri() -> str:
    """Return ANALYTICS_MONGO_URI; exit 1 naming the variable when it is unset."""
    uri = os.environ.get(MONGO_URI_ENV)
    if not uri:
        raise SystemExit(
            f"{MONGO_URI_ENV} is not set. Export a read-only Mongo URI: local is "
            "mongodb://localhost:27017; for prod, take the password from the Keychain item "
            "gaia-prod-mongo-ro (security find-generic-password -s gaia-prod-mongo-ro -w)."
        )
    return uri


def ground_truth_db() -> Database[Document]:
    """Return the app database at ANALYTICS_MONGO_URI.

    Prod reads use the read-only user whose credentials live in the macOS
    Keychain item gaia-prod-mongo-ro: build the URI in the shell, never in a file.
    """
    client: MongoClient[Document] = MongoClient(mongo_uri(), appname=APP_NAME, tz_aware=True)
    return client[MONGO_DATABASE_NAME]


def require_mongo_for(target: TargetName, uri: str) -> None:
    """Exit 1 unless the Mongo at uri is the deployment target's PostHog project tracks.

    The e2e project tracks the local stack and prod tracks the remote cluster;
    a mismatch matches one deployment's users to the other's persons.
    """
    # Read from the URI text alone: resolving a mongodb+srv record would dial DNS.
    seeds = uri.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].rsplit("@", 1)[-1]
    hosts = {host for host, _port in split_hosts(seeds)}
    local = hosts <= LOCAL_MONGO_HOSTS
    if (target is TargetName.PROD) == local:
        expected = "a remote prod" if target is TargetName.PROD else "a local"
        raise SystemExit(
            f"refusing to write to the {target.value} project from Mongo at {sorted(hosts)}: "
            f"{MONGO_URI_ENV} must point at {expected} Mongo"
        )
