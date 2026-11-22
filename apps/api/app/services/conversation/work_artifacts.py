"""Reconcile a conversation's artifacts/ files with the cards it shows, once per finished work.

The coding tools card what they write, but a file a background process made, or one changed or
deleted after its run ended, reaches no tool. When work finishes, the session's artifacts/ tree is
listed against the conversation's artifact registry: a new or changed file the work's own cards
do not name gets an upsert card, a file gone from the tree gets a remove card, and the registry
becomes the listing.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.constants.chat import ARTIFACT_CARD
from app.db.repositories.conversations import conversation_repository
from app.models.artifact_models import ArtifactCard, ArtifactRegistryEntry
from app.services.artifact_events import remove_event, upsert_event
from app.services.storage import ArtifactInfo, JuiceFSUnavailable, list_artifacts
from shared.py.conversation_wire import ToolDataEntry
from shared.py.wide_events import log


async def reconcile_artifacts(
    user_id: str, conversation_id: str, cards: Sequence[ToolDataEntry]
) -> tuple[ToolDataEntry, ...]:
    """Return the artifact cards the work's own cards miss: files made or changed outside the tools, and files deleted."""
    try:
        listed = await list_artifacts(user_id, conversation_id)
    except JuiceFSUnavailable as error:
        # The result still reaches the user; the next finished work reconciles what this one missed.
        log.warning(
            "workspace storage offline; artifacts not reconciled",
            conversation_id=conversation_id,
            error_type=type(error).__name__,
        )
        return ()
    entries: list[ArtifactRegistryEntry] = await conversation_repository.list_artifacts(
        conversation_id, user_id=user_id
    )
    registry = {entry["path"]: entry for entry in entries}
    carded = {
        ArtifactCard.model_validate(card["data"]).path
        for card in cards
        if card["tool_name"] == ARTIFACT_CARD
    }
    on_disk = {info.path for info in listed}
    added = [
        upsert_event(conversation_id, info)
        for info in listed
        if info.path not in carded and _changed(registry.get(info.path), info)
    ]
    removed = [remove_event(conversation_id, path) for path in registry if path not in on_disk]
    kept = [_registered(registry.get(info.path), info) for info in listed]
    if kept != list(registry.values()):
        await conversation_repository.set_artifacts(conversation_id, user_id=user_id, entries=kept)
    return tuple(
        ToolDataEntry(tool_name=ARTIFACT_CARD, data=dict(event)) for event in [*added, *removed]
    )


def _changed(registered: ArtifactRegistryEntry | None, info: ArtifactInfo) -> bool:
    return registered is None or registered["mtime"] != info.mtime


def _registered(
    registered: ArtifactRegistryEntry | None, info: ArtifactInfo
) -> ArtifactRegistryEntry:
    """Return the registry entry for a listed file: the stored one while unchanged, so its inline body stays."""
    if registered is not None and not _changed(registered, info):
        return registered
    return ArtifactRegistryEntry(
        path=info.path,
        size_bytes=info.size_bytes,
        mtime=info.mtime,
        content_type=info.content_type,
        updated_at=datetime.now(UTC).isoformat(),
    )
