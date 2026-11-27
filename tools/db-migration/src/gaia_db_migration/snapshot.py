"""Copy prod into a local MongoDB with every non-structural string overwritten.

Reads the source read-only and writes only to a database on this machine. Every kept string
and object key passes the PII guard before its document is written; any failure drops the copy.
Each document is validated by every model it is stored with, before and after anonymising: a
document valid before and invalid after is an anonymiser defect and fails the run.
"""

import argparse
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
import yaml

from gaia_db_migration.anonymise import Anonymiser, schema_keys
from gaia_db_migration.model_policy import CollectionPolicy, collection_models, policy_for
from gaia_db_migration.pii import PiiGuard
from gaia_db_migration.source import RawDocument, connect_read_only

DECISIONS_PATH = Path(__file__).resolve().parents[2] / "decisions.yaml"
DEFAULT_INVENTORY = Path(".agents/db-migration/inventory.json")
SNAPSHOT_ACTIONS = frozenset({"migrate", "schema-only", "deferred"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
BATCH_SIZE = 500
#: Index options that would change the copy after it is written.
DROPPED_INDEX_OPTIONS = frozenset({"expireAfterSeconds", "v", "ns"})

#: A conversations head whose legacy messages still hash to its stored fingerprint.
FINGERPRINT_COLLECTION = "conversations"
FINGERPRINT_FIELD = "migrated_fingerprint"
FINGERPRINT_EXPRESSION = {"$toHashedIndexKey": {"$ifNull": ["$messages", []]}}
FINGERPRINT_MATCHED_FLAG = "__fingerprint_matched"


class UnsafeTargetError(RuntimeError):
    """The snapshot target is not a database on this machine."""


class AnonymiserDefectError(RuntimeError):
    """A document its model accepted before anonymising is rejected after."""


@dataclass
class CollectionResult:
    documents: int = 0
    invalid_before: Counter[str] = field(default_factory=Counter)
    broken_by_anonymising: Counter[str] = field(default_factory=Counter)
    fingerprint_matched: int | None = None
    fingerprint_unmatched: int | None = None


def snapshot_collections() -> list[str]:
    decisions = yaml.safe_load(DECISIONS_PATH.read_text())["collections"]
    return sorted(name for name, entry in decisions.items() if entry["action"] in SNAPSHOT_ACTIONS)


def connect_local_target(uri: str, database: str) -> Database[RawDocument]:
    hosts = {
        urlsplit(f"//{host}").hostname for host in urlsplit(uri).netloc.split("@")[-1].split(",")
    }
    if not hosts or not hosts <= LOCAL_HOSTS:
        raise UnsafeTargetError(f"snapshot target {sorted(map(str, hosts))} is not this machine")
    client: MongoClient[RawDocument] = MongoClient(uri)
    return client[database]


def _source_documents(source: Collection[RawDocument]) -> Iterator[RawDocument]:
    if source.name != FINGERPRINT_COLLECTION:
        yield from source.find({}, batch_size=BATCH_SIZE)
        return
    matched = {"$eq": [FINGERPRINT_EXPRESSION, f"${FINGERPRINT_FIELD}"]}
    yield from source.aggregate(
        [{"$addFields": {FINGERPRINT_MATCHED_FLAG: matched}}], batchSize=BATCH_SIZE
    )


def _invalid_paths(models: tuple[type[BaseModel], ...], document: RawDocument) -> list[str]:
    invalid: list[str] = []
    for model in models:
        try:
            model.model_validate({**document, "id": str(document["_id"])})
        except ValidationError as error:
            invalid += [
                f"{model.__name__}:{'.'.join(str(part) for part in issue['loc'])}"
                for issue in error.errors()
            ]
    return invalid


def copy_collection(
    source: Collection[RawDocument],
    target: Collection[RawDocument],
    models: tuple[type[BaseModel], ...],
    policy: CollectionPolicy,
    anonymiser: Anonymiser,
) -> CollectionResult:
    result = CollectionResult()
    target.drop()
    matched_ids: list[object] = []
    batch: list[RawDocument] = []
    for document in _source_documents(source):
        if document.pop(FINGERPRINT_MATCHED_FLAG, False):
            matched_ids.append(document["_id"])
        before = _invalid_paths(models, document)
        result.invalid_before.update(before)
        anonymised = anonymiser.document(document, policy)
        for path in set(_invalid_paths(models, anonymised)) - set(before):
            result.broken_by_anonymising[path] += 1
        batch.append(anonymised)
        result.documents += 1
        if len(batch) == BATCH_SIZE:
            target.insert_many(batch, ordered=False)
            batch = []
    if batch:
        target.insert_many(batch, ordered=False)
    if source.name == FINGERPRINT_COLLECTION:
        _recompute_fingerprints(target, matched_ids, result)
    _copy_indexes(source, target)
    return result


def _recompute_fingerprints(
    target: Collection[RawDocument], matched_ids: list[object], result: CollectionResult
) -> None:
    target.update_many(
        {"_id": {"$in": matched_ids}}, [{"$set": {FINGERPRINT_FIELD: FINGERPRINT_EXPRESSION}}]
    )
    now_matching = target.count_documents(
        {"$expr": {"$eq": [FINGERPRINT_EXPRESSION, f"${FINGERPRINT_FIELD}"]}}
    )
    if now_matching != len(matched_ids):
        raise AnonymiserDefectError(
            f"{now_matching} heads match their fingerprint after the copy; {len(matched_ids)} matched in the source"
        )
    result.fingerprint_matched = len(matched_ids)
    result.fingerprint_unmatched = result.documents - len(matched_ids)


def _copy_indexes(source: Collection[RawDocument], target: Collection[RawDocument]) -> None:
    for index in source.list_indexes():
        if index["name"] == "_id_":
            continue
        options = {k: v for k, v in index.items() if k not in DROPPED_INDEX_OPTIONS | {"key"}}
        target.create_index(list(index["key"].items()), **options)


def main() -> None:
    parser = argparse.ArgumentParser(prog="db-snapshot", description=__doc__)
    parser.add_argument("--target-uri", required=True)
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--collections", nargs="+", help="copy only these (default: every one)")
    args = parser.parse_args()
    names = snapshot_collections()
    if args.collections:
        unknown = set(args.collections) - set(names)
        if unknown:
            parser.error(f"not snapshotted by decisions.yaml: {sorted(unknown)}")
        names = sorted(args.collections)

    target = connect_local_target(args.target_uri, args.target_db)
    try:
        _run(target, names, args.report, args.inventory)
    except BaseException:
        target.client.drop_database(target.name)
        raise
    print(f"snapshot {args.target_db} complete; report {args.report}")


def _run(
    target: Database[RawDocument], names: list[str], report_path: Path, inventory_path: Path
) -> None:
    source = connect_read_only()
    models = collection_models()
    inventory = json.loads(inventory_path.read_text())
    anonymiser = Anonymiser(guard=PiiGuard(), schema=schema_keys(inventory))
    results: dict[str, CollectionResult] = {}
    for name in names:
        stored_models = models.get(name, ())
        anonymiser.collection = name
        results[name] = copy_collection(
            source[name], target[name], stored_models, policy_for(stored_models), anonymiser
        )
        print(f"{name}: {results[name].documents} documents", flush=True)

    report = {
        "target_db": target.name,
        "collections": {
            name: {
                "documents": r.documents,
                "invalid_before": dict(r.invalid_before),
                "broken_by_anonymising": dict(r.broken_by_anonymising),
                "fingerprint_matched": r.fingerprint_matched,
                "fingerprint_unmatched": r.fingerprint_unmatched,
            }
            for name, r in results.items()
        },
        "replaced_by_pii_guard": dict(anonymiser.replaced),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    broken = {
        name: dict(r.broken_by_anonymising)
        for name, r in results.items()
        if r.broken_by_anonymising
    }
    if broken:
        raise AnonymiserDefectError(f"anonymising broke valid documents: {broken}")
