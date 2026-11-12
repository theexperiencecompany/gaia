"""A stored entry hands back its message and its document without Mongo's _id or unread defaults."""

from bson import ObjectId

from app.models.conversation_models import StoredEntry

_KEYS: dict[str, object] = {"conversation_id": "c1", "user_id": "u1", "seq": 3, "id": "m1"}


def test_a_stored_entry_returns_its_message_and_document_as_read_without_mongos_id() -> None:
    stored = StoredEntry.model_validate(
        {"_id": ObjectId(), **_KEYS, "type": "user", "response": "hi"}
    )

    assert stored.message_fields() == {"type": "user", "response": "hi"}
    assert stored.document() == {**_KEYS, "type": "user", "response": "hi"}
