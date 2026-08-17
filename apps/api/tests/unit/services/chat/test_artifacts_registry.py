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

    async def test_the_path_key_is_read_and_flows_to_the_repository_write(self) -> None:
        """A mutated "path" key (or a dropped read) would upsert under the wrong
        path or None, silently splitting one file's history across two registry
        rows instead of keying by the payload's actual path."""
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=True)
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact("user-1", "conv-1", {"path": "notes/report.pdf"})

        assert repository.update_artifact.await_args.kwargs["path"] == "notes/report.pdf"

    async def test_content_type_is_read_under_its_own_key_and_written_through(self) -> None:
        """Renaming the "content_type" key (read or write side) would either read
        nothing (write None) or write under a key the client's card never reads,
        silently losing the file's MIME type."""
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=True)
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact(
                "user-1", "conv-1", {"path": "a.txt", "content_type": "text/plain"}
            )

        fields = _written_fields(repository)
        assert set(fields.keys()) == {"size_bytes", "mtime", "content_type", "updated_at"}
        assert fields["content_type"] == "text/plain"

    async def test_body_is_read_under_its_own_key_and_written_through_on_update(self) -> None:
        """``body`` is only written when the payload carries one — this pins both
        that the guard passes for a real body and that the value read is the
        payload's actual body, not a key/argument that got mutated away."""
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=True)
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact(
                "user-1", "conv-1", {"path": "a.txt", "body": "hello world"}
            )

        fields = _written_fields(repository)
        assert set(fields.keys()) == {"size_bytes", "mtime", "content_type", "updated_at", "body"}
        assert fields["body"] == "hello world"

    async def test_element_pushed_on_insert_reads_each_declared_field_by_name(self) -> None:
        """When no existing element matches ``path``, the insert path rebuilds the
        element from ARTIFACT_ELEMENT_FIELDS by reading each field's own key out
        of the payload; a mutated key lookup would silently push None instead of
        the payload's actual value for that field."""
        repository = AsyncMock()
        repository.update_artifact = AsyncMock(return_value=False)
        repository.push_artifact = AsyncMock()
        with patch(f"{MODULE}.conversation_repository", repository):
            await upsert_conversation_artifact(
                "user-1",
                "conv-1",
                {
                    "path": "new.txt",
                    "size_bytes": 10,
                    "mtime": 5.0,
                    "content_type": "text/plain",
                },
            )

        element = repository.push_artifact.await_args.kwargs["element"]
        assert element["path"] == "new.txt"
        assert element["size_bytes"] == 10
        assert element["mtime"] == 5.0
        assert element["content_type"] == "text/plain"
