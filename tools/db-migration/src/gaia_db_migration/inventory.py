"""Profile the source database's real shape: every field path, its observed types and sizes, every index.

The report holds shapes and counts only. No field value is ever recorded.
"""

import argparse
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
import datetime as dt
import json
from pathlib import Path

from bson import Binary, Decimal128, Int64, ObjectId, Regex, Timestamp, json_util
from pymongo.database import Database

from gaia_db_migration.paths import walk
from gaia_db_migration.source import RawDocument, connect_read_only

#: Paths left unread: the legacy embedded conversation messages are retired before migration.
EXCLUDED_PATHS: Mapping[str, tuple[str, ...]] = {"conversations": ("messages",)}
#: Top-level fields whose newest value marks a collection's last write.
WRITE_TIME_FIELDS = ("updated_at", "updatedAt", "created_at", "createdAt")
SCAN_BATCH_SIZE = 1000


#: Decoded Python types and their BSON names, most specific first (bool and Int64 subclass int).
BSON_TYPE_NAMES: tuple[tuple[type, str], ...] = (
    (type(None), "null"),
    (bool, "bool"),
    (Int64, "long"),
    (int, "int"),
    (float, "double"),
    (str, "string"),
    (ObjectId, "objectId"),
    (dt.datetime, "date"),
    (Mapping, "object"),
    (list, "array"),
    (Binary, "binData"),
    (bytes, "binData"),
    (Decimal128, "decimal"),
    (Regex, "regex"),
    (Timestamp, "timestamp"),
)


def bson_type(value: object) -> str:
    """Name a decoded value by its BSON type."""
    for python_type, name in BSON_TYPE_NAMES:
        if isinstance(value, python_type):
            return name
    raise TypeError(f"unmapped BSON value type {type(value).__name__}")


@dataclass
class PathProfile:
    """What one field path holds across a collection."""

    types: Counter[str] = field(default_factory=Counter)
    max_string_length: int = 0
    max_array_length: int = 0
    empty_arrays: int = 0

    def observe(self, value: object) -> None:
        self.types[bson_type(value)] += 1
        if isinstance(value, str):
            self.max_string_length = max(self.max_string_length, len(value))
        elif isinstance(value, list):
            self.max_array_length = max(self.max_array_length, len(value))
            self.empty_arrays += not value


@dataclass
class CollectionProfile:
    """One collection's document count, field paths, size extremes and last write."""

    documents: int = 0
    paths: dict[str, PathProfile] = field(default_factory=dict)
    max_document_fields: int = 0
    last_write: dt.datetime | None = None

    def observe(self, document: RawDocument) -> None:
        self.documents += 1
        self.max_document_fields = max(self.max_document_fields, len(document))
        for path, value in walk(document):
            self.paths.setdefault(path, PathProfile()).observe(value)
        for name in WRITE_TIME_FIELDS:
            stamp = document.get(name)
            if isinstance(stamp, dt.datetime) and (
                self.last_write is None or stamp > self.last_write
            ):
                self.last_write = stamp


def profile_collection(db: Database[RawDocument], name: str) -> CollectionProfile:
    """Scan every document of one collection, skipping its excluded paths."""
    projection = dict.fromkeys(EXCLUDED_PATHS.get(name, ()), 0) or None
    profile = CollectionProfile()
    for document in db[name].find({}, projection, batch_size=SCAN_BATCH_SIZE):
        profile.observe(document)
    return profile


def index_specs(db: Database[RawDocument], name: str) -> list[RawDocument]:
    """Return the collection's live index definitions, as the server reports them."""
    return [dict(index) for index in db[name].list_indexes()]


def report(db: Database[RawDocument]) -> RawDocument:
    """Profile every collection of the database into one JSON-ready report."""
    collections: RawDocument = {}
    for name in sorted(db.list_collection_names()):
        profile = profile_collection(db, name)
        collections[name] = {
            "documents": profile.documents,
            "last_write": profile.last_write.isoformat() if profile.last_write else None,
            "max_document_fields": profile.max_document_fields,
            "excluded_paths": list(EXCLUDED_PATHS.get(name, ())),
            "indexes": index_specs(db, name),
            "paths": {
                path: {
                    "present": sum(p.types.values()),
                    "types": dict(p.types),
                    "mixed": len(p.types.keys() - {"null"}) > 1,
                    "max_string_length": p.max_string_length,
                    "max_array_length": p.max_array_length,
                    "empty_arrays": p.empty_arrays,
                }
                for path, p in sorted(profile.paths.items())
            },
        }
    return {
        "database": db.name,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "collections": collections,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="db-inventory", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    out = parser.parse_args().out
    out.parent.mkdir(parents=True, exist_ok=True)
    result = report(connect_read_only())
    out.write_text(json.dumps(json.loads(json_util.dumps(result)), indent=2, sort_keys=True))
    print(f"wrote {out}: {len(result['collections'])} collections")
