"""Unit tests for the conversation artifact registry writes.

The registry element is mirrored verbatim to the client, so what this module
writes is what the user's artifact card shows. Both numeric fields are
``| None`` on purpose — "we don't know this file's size/mtime" is not the same
claim as "this file is empty and dates from 1970" — and the update path and the
insert path must write one shape, not two.
"""

from unittest.mock import AsyncMock, patch

from app.services.chat.artifacts_registry import upsert_conversation_artifact

MODULE = "app.services.chat.artifacts_registry"


def _written_fields(repository: AsyncMock) -> dict[str, object]:
    """The patch the registry handed the repository."""
    return repository.update_artifact.await_args.kwargs["fields"]


class TestUpsertConversationArtifact:
    async def test_an_unknown_size_and_mtime_are_written_as_unknown_not_as_zero(self) -> None:
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=True)
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact(
                "user-1", "conv-1", {"path": "report.pdf", "content_type": "application/pdf"}
            )

        fields = _written_fields(repository)
        assert fields["size_bytes"] is None
        assert fields["mtime"] is None

    async def test_the_real_size_and_mtime_are_written_through(self) -> None:
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=True)
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact(
                "user-1",
                "conv-1",
                {"path": "report.pdf", "size_bytes": 2048, "mtime": 1700.5},
            )

        fields = _written_fields(repository)
        assert fields["size_bytes"] == 2048
        assert fields["mtime"] == 1700.5
