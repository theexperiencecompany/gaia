"""A stored entry reads back as a row carrying its owner, conversation and commit time."""

from datetime import UTC, datetime

from app.db.repositories.conversation_entries import stored_row


def test_a_stored_row_carries_its_commit_time() -> None:
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    row = stored_row(
        {
            "conversation_id": "c1",
            "user_id": "u1",
            "seq": 4,
            "id": "m1",
            "type": "user",
            "response": "hi",
            "at": at,
        }
    )

    assert (row.user_id, row.conversation_id, row.at) == ("u1", "c1", at)
    assert (row.entry.seq, row.entry.message_id) == (4, "m1")
