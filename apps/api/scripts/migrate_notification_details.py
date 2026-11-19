"""Expand migration: give each stored notification the typed details its free-form metadata stands for.

The previous release serves while the release step runs and still writes metadata, so metadata stays
and contract() drops it a release later, after re-running the expand over what that release wrote.
Metadata no current kind describes (a retired producer's shape) gets no details; the run prints those
shapes' key sets. A notification that already has details keeps them, so re-running is safe.

    cd apps/api && uv run python -m scripts.migrate_notification_details [--apply]
"""

import asyncio
from collections import Counter
from collections.abc import Mapping

from pydantic import TypeAdapter, ValidationError
from pymongo import UpdateOne

from app.constants.notifications import NotificationKind
from app.db.mongodb.collections import get_async_collection
from app.models.notification.details_models import NotificationDetails
from app.models.notification.notification_models import NotificationSourceEnum
from scripts._cli import apply_requested

_METADATA = "original_request.metadata"
_DETAILS = "original_request.details"
_UNMAPPED = {_DETAILS: {"$exists": False}}
_BATCH = 500
#: The label a notification whose metadata carries nothing gets in the counts.
NO_DETAILS = "none"
#: The label a notification whose metadata no current kind describes gets in the counts.
UNRECOGNISED = "unrecognised"

#: The kind each shape a current producer wrote stands for, by its key set.
_KIND_BY_KEYS: dict[frozenset[str], NotificationKind] = {
    frozenset({"todo_id"}): NotificationKind.TODO,
    frozenset({"todo_id", "retry_count"}): NotificationKind.TODO_FAILED,
    frozenset({"todo_id", "subscription_id"}): NotificationKind.TODO_TRIGGER_FIRED,
    frozenset({"todo_count"}): NotificationKind.DORMANT_TODOS,
    frozenset({"reminder_id", "created_at"}): NotificationKind.REMINDER,
    frozenset({"workflow_id", "conversation_id"}): NotificationKind.WORKFLOW_COMPLETED,
    frozenset({"workflow_id", "error_type"}): NotificationKind.WORKFLOW_FAILED,
    frozenset({"workflow_id", "missing_integrations"}): NotificationKind.WORKFLOW_PAUSED,
    frozenset({"integration_id", "paused_workflows"}): NotificationKind.INTEGRATION_EXPIRED,
    frozenset({"integration_display_name"}): NotificationKind.SYSTEM_WORKFLOWS_PROVISIONED,
}
#: The {"source": ...} tags two producers wrote in place of a kind.
_KIND_BY_SOURCE_TAG: dict[object, NotificationKind] = {
    "memory_backfill": NotificationKind.MEMORY_READY,
    "gmail_personalization": NotificationKind.GMAIL_PERSONALIZED,
}
#: The reminder's own copy of the notification's created_at, which its details do not repeat.
_DROPPED_KEYS = frozenset({"created_at"})

notifications_collection = get_async_collection("notifications")
_details_adapter: TypeAdapter[NotificationDetails] = TypeAdapter(NotificationDetails)


def _candidate(metadata: Mapping[str, object], source: object) -> dict[str, object] | None:
    """Return the raw details a stored metadata stands for, or None when no current producer wrote it."""
    if "kind" in metadata:
        return dict(metadata)
    if set(metadata) == {"source"}:
        tagged = _KIND_BY_SOURCE_TAG.get(metadata["source"])
        return None if tagged is None else {"kind": tagged}
    keys = frozenset(metadata)
    # The executor's failure notice alone wrote a bare workflow_id.
    if (
        keys == frozenset({"workflow_id"})
        and source == NotificationSourceEnum.WORKFLOW_FAILED.value
    ):
        return {"kind": NotificationKind.WORKFLOW_FAILED, **metadata}
    kind = _KIND_BY_KEYS.get(keys)
    if kind is None:
        return None
    candidate = {"kind": kind, **{k: v for k, v in metadata.items() if k not in _DROPPED_KEYS}}
    if kind is NotificationKind.WORKFLOW_PAUSED:
        candidate["missing_integrations"] = str(metadata["missing_integrations"]).split(",")
    return candidate


def classify(
    metadata: Mapping[str, object], source: object
) -> tuple[str, dict[str, object] | None]:
    """Return a stored metadata's count label and the details to store for it, None when it has none."""
    if not metadata:
        return NO_DETAILS, None
    candidate = _candidate(metadata, source)
    if candidate is None:
        return UNRECOGNISED, None
    try:
        details = _details_adapter.validate_python(candidate)
    except ValidationError:
        return UNRECOGNISED, None
    return details.kind.value, details.model_dump(mode="json")


async def migrate(apply: bool) -> int:
    """Store details on every notification without them; return how many notifications it touched."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Deriving notification details from metadata...\n")
    counts: Counter[str] = Counter()
    unrecognised: Counter[tuple[str, ...]] = Counter()
    batch: list[UpdateOne] = []
    projection = {_METADATA: 1, "original_request.source": 1}
    async for doc in notifications_collection.find(_UNMAPPED, projection):
        request = doc.get("original_request", {})
        metadata = request.get("metadata") or {}
        label, details = classify(metadata, request.get("source"))
        counts[label] += 1
        if label == UNRECOGNISED:
            unrecognised[tuple(sorted(metadata))] += 1
        batch.append(UpdateOne({"_id": doc["_id"], **_UNMAPPED}, {"$set": {_DETAILS: details}}))
        if apply and len(batch) >= _BATCH:
            await notifications_collection.bulk_write(batch, ordered=False)
            batch = []
    if apply and batch:
        await notifications_collection.bulk_write(batch, ordered=False)

    print(f"[{mode}] Done. " + " ".join(f"{label}={n}" for label, n in sorted(counts.items())))
    for keys, n in unrecognised.most_common():
        print(f"  unrecognised metadata keys {list(keys)}: {n}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return counts.total()


async def contract(apply: bool) -> int:
    """Derive what the previous release wrote since, then drop metadata; return how many notifications lose it."""
    await migrate(apply)
    mode = "APPLY" if apply else "DRY RUN"
    carrying = {_METADATA: {"$exists": True}}
    dropped = await notifications_collection.count_documents(carrying)
    if apply:
        await notifications_collection.update_many(carrying, {"$unset": {_METADATA: ""}})
    print(f"[{mode}] Dropped metadata from notifications={dropped}")
    return dropped


if __name__ == "__main__":
    asyncio.run(migrate(apply=apply_requested(__doc__)))
