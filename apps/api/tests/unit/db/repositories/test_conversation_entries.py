"""A stored entry reads back as a row carrying its owner, conversation and commit time."""

from datetime import UTC, datetime
import hashlib
import json

from app.db.repositories.conversation_entries import content_hash, stored_row


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


def test_content_hash_ignores_key_order() -> None:
    assert content_hash({"id": "m1", "response": "hi"}) == content_hash(
        {"response": "hi", "id": "m1"}
    )


def test_content_hash_hashes_a_datetime_by_its_text() -> None:
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    expected = hashlib.sha256(json.dumps({"at": str(at), "id": "m1"}).encode()).hexdigest()

    assert content_hash({"id": "m1", "at": at}) == expected
