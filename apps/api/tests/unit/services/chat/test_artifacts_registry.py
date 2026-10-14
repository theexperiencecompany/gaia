"""The conversation artifact registry never stores a file's heygaia.link.

A stored copy goes stale the moment the owner stops sharing, and a reloaded card
would show a dead link; the short_links collection is the one source of truth.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.services.artifact_events import ArtifactEventMessage
from app.services.chat import artifacts_registry

_REPO = "app.services.chat.artifacts_registry.conversation_repository"

EVENT: ArtifactEventMessage = {
    "event": "upsert",
    "session_id": "conv-1",
    "path": "report.html",
    "user_id": "507f1f77bcf86cd799439011",
    "ts": 1.0,
    "size_bytes": 12,
    "mtime": 2.0,
    "content_type": "text/html",
    "short_url": "https://heygaia.link/abcdefghijk",
}


async def _upsert(update_matched: bool) -> AsyncMock:
    with patch(_REPO) as repo:
        repo.update_artifact = AsyncMock(return_value=update_matched)
        repo.push_artifact = AsyncMock()
        await artifacts_registry.upsert_conversation_artifact.__wrapped__(
            "507f1f77bcf86cd799439011", "conv-1", EVENT
        )
        return repo


class TestRegistryNeverStoresTheLink:
    async def test_a_new_file_is_stored_without_its_link(self) -> None:
        repo = await _upsert(update_matched=False)

        element = dict(repo.push_artifact.await_args.kwargs["element"])
        assert datetime.fromisoformat(element.pop("updated_at")).tzinfo == UTC
        assert element == {
            "path": "report.html",
            "size_bytes": 12,
            "mtime": 2.0,
            "content_type": "text/html",
        }

    async def test_a_re_emit_writes_no_link_onto_the_existing_entry(self) -> None:
        repo = await _upsert(update_matched=True)

        assert "short_url" not in repo.update_artifact.await_args.kwargs["fields"]
        repo.push_artifact.assert_not_awaited()
