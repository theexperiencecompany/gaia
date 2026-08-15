"""A persisted note must survive a vector-store outage — visibly, not silently.

Indexing runs after the Mongo write commits. Before the ChromaDB client was
repointed at the real server (`chromadb.Client` built a process-local in-memory
store), that call could not fail, so the ordering was unreachable. Making the
client real made it reachable: a Chroma outage would have 500'd note creation
with the note already saved, telling the user their note was lost when it was
not. Failing the request is wrong — but so is swallowing it, because an
unindexed note is invisible to search forever. Hence: succeed, flag, repair.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.models.notes_models import NoteDocument, NoteModel
from app.utils.notes_utils import insert_note, reindex_note

USER_ID = "user-notes-1"
NOTE_ID = "note-1"


def _created_note() -> NoteDocument:
    return NoteDocument(
        id=NOTE_ID,
        user_id=USER_ID,
        content="<p>buy oat milk</p>",
        plaintext="buy oat milk",
    )


@pytest.mark.unit
class TestInsertNoteIndexingFailure:
    async def test_note_survives_an_indexing_outage_and_is_flagged(self):
        update = AsyncMock()
        with (
            patch(
                "app.utils.notes_utils.note_repository.create",
                AsyncMock(return_value=_created_note()),
            ),
            patch("app.utils.notes_utils.note_repository.update", update),
            patch(
                "app.utils.notes_utils.index_note",
                AsyncMock(side_effect=RuntimeError("chroma unreachable")),
            ),
        ):
            response = await insert_note(
                NoteModel(content="<p>buy oat milk</p>", plaintext="buy oat milk"),
                USER_ID,
            )

        # The request succeeds: the note is committed, so reporting failure lies.
        assert response.plaintext == "buy oat milk"
        # …and the failure is recorded, so it can be repaired rather than lost.
        update.assert_awaited_once()
        assert update.await_args.kwargs["update"].needs_reindex is True
        assert update.await_args.kwargs["user_id"] == USER_ID

    async def test_successful_indexing_does_not_flag_the_note(self):
        update = AsyncMock()
        with (
            patch(
                "app.utils.notes_utils.note_repository.create",
                AsyncMock(return_value=_created_note()),
            ),
            patch("app.utils.notes_utils.note_repository.update", update),
            patch("app.utils.notes_utils.index_note", AsyncMock()),
        ):
            await insert_note(
                NoteModel(content="<p>buy oat milk</p>", plaintext="buy oat milk"),
                USER_ID,
            )

        update.assert_not_awaited()

    async def test_reindex_clears_the_flag(self):
        update = AsyncMock()
        with (
            patch("app.utils.notes_utils.note_repository.update", update),
            patch("app.utils.notes_utils.index_note", AsyncMock()) as index,
        ):
            await reindex_note(NOTE_ID, USER_ID, "buy oat milk")

        index.assert_awaited_once_with(NOTE_ID, USER_ID, "buy oat milk")
        assert update.await_args.kwargs["update"].needs_reindex is False

    async def test_reindex_propagates_a_still_broken_vector_store(self):
        """A repair pass must see which notes are still broken, not swallow them."""
        with (
            patch("app.utils.notes_utils.note_repository.update", AsyncMock()),
            patch(
                "app.utils.notes_utils.index_note",
                AsyncMock(side_effect=RuntimeError("still down")),
            ),
            pytest.raises(RuntimeError, match="still down"),
        ):
            await reindex_note(NOTE_ID, USER_ID, "buy oat milk")
