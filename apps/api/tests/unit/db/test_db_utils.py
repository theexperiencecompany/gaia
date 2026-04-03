"""Tests for database utility functions.

Covers:
- serialize_document: ObjectId conversion, _id -> id, nested dicts, lists, edge cases
- Roundtrip consistency and data integrity
"""

from typing import Any

import pytest
from bson import ObjectId

from app.db.utils import serialize_document


# ---------------------------------------------------------------------------
# serialize_document — basic behavior
# ---------------------------------------------------------------------------


class TestSerializeDocumentBasic:
    """Tests for core serialize_document behavior."""

    def test_empty_dict_returns_empty(self) -> None:
        """Empty dict should return empty dict."""
        result = serialize_document({})
        assert result == {}

    def test_none_returns_none(self) -> None:
        """None input should return None (falsy passthrough)."""
        result = serialize_document(None)  # type: ignore[arg-type]
        assert result is None

    def test_empty_string_returns_falsy(self) -> None:
        """Empty string (falsy) should be returned as-is."""
        result = serialize_document("")  # type: ignore[arg-type]
        assert result == ""

    def test_zero_returns_falsy(self) -> None:
        """Zero (falsy) should be returned as-is."""
        result = serialize_document(0)  # type: ignore[arg-type]
        assert result == 0


# ---------------------------------------------------------------------------
# serialize_document — _id to id conversion
# ---------------------------------------------------------------------------


class TestSerializeDocumentIdConversion:
    """Tests for _id -> id field conversion."""

    def test_converts_objectid_to_string_id(self) -> None:
        """ObjectId in _id should become a string 'id' field."""
        oid = ObjectId()
        doc = {"_id": oid, "name": "test"}

        result = serialize_document(doc)

        assert "id" in result
        assert "_id" not in result
        assert result["id"] == str(oid)
        assert result["name"] == "test"

    def test_converts_string_id(self) -> None:
        """String _id should also be converted to 'id'."""
        doc = {"_id": "custom_string_id", "name": "test"}

        result = serialize_document(doc)

        assert result["id"] == "custom_string_id"
        assert "_id" not in result

    def test_document_without_id(self) -> None:
        """Document without _id should not have 'id' in result."""
        doc = {"name": "test", "value": 42}

        result = serialize_document(doc)

        assert "id" not in result
        assert result["name"] == "test"
        assert result["value"] == 42

    def test_id_pop_modifies_original(self) -> None:
        """serialize_document pops _id from the original document (mutation)."""
        oid = ObjectId()
        doc = {"_id": oid, "name": "test"}

        serialize_document(doc)

        # Original document should have _id popped
        assert "_id" not in doc


# ---------------------------------------------------------------------------
# serialize_document — ObjectId values in fields
# ---------------------------------------------------------------------------


class TestSerializeDocumentObjectIdFields:
    """Tests for ObjectId conversion in various field positions."""

    def test_objectid_field_value(self) -> None:
        """ObjectId as a field value should be converted to string."""
        ref_id = ObjectId()
        doc = {"user_ref": ref_id}

        result = serialize_document(doc)

        assert result["user_ref"] == str(ref_id)
        assert isinstance(result["user_ref"], str)

    def test_multiple_objectid_fields(self) -> None:
        """Multiple ObjectId fields should all be converted."""
        id1 = ObjectId()
        id2 = ObjectId()
        doc = {"_id": ObjectId(), "author_id": id1, "project_id": id2}

        result = serialize_document(doc)

        assert result["author_id"] == str(id1)
        assert result["project_id"] == str(id2)

    def test_non_objectid_values_preserved(self) -> None:
        """Non-ObjectId values should be kept as-is."""
        doc = {
            "name": "test",
            "count": 42,
            "active": True,
            "score": 3.14,
            "tags": None,
        }

        result = serialize_document(doc)

        assert result["name"] == "test"
        assert result["count"] == 42
        assert result["active"] is True
        assert result["score"] == pytest.approx(3.14)
        assert result["tags"] is None


# ---------------------------------------------------------------------------
# serialize_document — nested dictionaries
# ---------------------------------------------------------------------------


class TestSerializeDocumentNestedDicts:
    """Tests for recursive handling of nested dictionaries."""

    def test_nested_dict_with_objectid(self) -> None:
        """Nested dict containing ObjectId should be recursively serialized."""
        inner_id = ObjectId()
        doc = {"metadata": {"author_id": inner_id, "title": "hello"}}

        result = serialize_document(doc)

        assert result["metadata"]["author_id"] == str(inner_id)
        assert result["metadata"]["title"] == "hello"

    def test_deeply_nested_dict(self) -> None:
        """Multiple levels of nesting should be handled."""
        deep_id = ObjectId()
        doc = {"level1": {"level2": {"level3": {"ref": deep_id}}}}

        result = serialize_document(doc)

        assert result["level1"]["level2"]["level3"]["ref"] == str(deep_id)

    def test_nested_dict_with_id_field(self) -> None:
        """Nested dicts with _id should have it converted to 'id'."""
        inner_oid = ObjectId()
        doc = {"child": {"_id": inner_oid, "name": "child_doc"}}

        result = serialize_document(doc)

        assert result["child"]["id"] == str(inner_oid)
        assert "_id" not in result["child"]

    def test_empty_nested_dict(self) -> None:
        """Empty nested dict should remain empty."""
        doc: dict[str, Any] = {"metadata": {}}

        result = serialize_document(doc)

        assert result["metadata"] == {}


# ---------------------------------------------------------------------------
# serialize_document — lists
# ---------------------------------------------------------------------------


class TestSerializeDocumentLists:
    """Tests for list handling in serialize_document."""

    def test_list_of_objectids(self) -> None:
        """List containing ObjectIds should have each converted to string."""
        id1 = ObjectId()
        id2 = ObjectId()
        doc = {"member_ids": [id1, id2]}

        result = serialize_document(doc)

        assert result["member_ids"] == [str(id1), str(id2)]

    def test_list_of_dicts(self) -> None:
        """List of dicts should have each dict recursively serialized."""
        ref = ObjectId()
        doc = {
            "items": [
                {"_id": ObjectId(), "name": "item1"},
                {"ref": ref, "name": "item2"},
            ]
        }

        result = serialize_document(doc)

        assert "id" in result["items"][0]
        assert result["items"][1]["ref"] == str(ref)
        assert result["items"][1]["name"] == "item2"

    def test_list_of_primitives(self) -> None:
        """List of primitives should be kept as-is."""
        doc = {"tags": ["python", "mongo", "api"]}

        result = serialize_document(doc)

        assert result["tags"] == ["python", "mongo", "api"]

    def test_mixed_list(self) -> None:
        """List with mixed types (ObjectId, dict, primitive) should all be handled."""
        oid = ObjectId()
        doc = {
            "mixed": [
                oid,
                {"nested_id": ObjectId(), "val": 1},
                "plain_string",
                42,
                None,
            ]
        }

        result = serialize_document(doc)

        assert result["mixed"][0] == str(oid)
        assert isinstance(result["mixed"][1], dict)
        assert result["mixed"][2] == "plain_string"
        assert result["mixed"][3] == 42
        assert result["mixed"][4] is None

    def test_empty_list(self) -> None:
        """Empty list should remain empty."""
        doc: dict[str, Any] = {"items": []}

        result = serialize_document(doc)

        assert result["items"] == []

    def test_list_of_nested_dicts_with_lists(self) -> None:
        """Nested dicts within lists that themselves contain lists."""
        oid = ObjectId()
        doc = {
            "groups": [
                {"members": [oid, ObjectId()], "name": "group1"},
            ]
        }

        result = serialize_document(doc)

        assert result["groups"][0]["members"][0] == str(oid)
        assert isinstance(result["groups"][0]["members"][1], str)


# ---------------------------------------------------------------------------
# serialize_document — complex real-world-like documents
# ---------------------------------------------------------------------------


class TestSerializeDocumentRealWorld:
    """Tests with realistic MongoDB document structures."""

    def test_conversation_document(self) -> None:
        """Simulate a conversation document with messages array."""
        conv_id = ObjectId()
        msg_id = ObjectId()
        doc = {
            "_id": conv_id,
            "user_id": "user123",
            "messages": [
                {
                    "_id": msg_id,
                    "content": "Hello",
                    "pinned": False,
                }
            ],
            "created_at": "2024-01-01T00:00:00Z",
        }

        result = serialize_document(doc)

        assert result["id"] == str(conv_id)
        assert result["user_id"] == "user123"
        assert result["messages"][0]["id"] == str(msg_id)
        assert result["messages"][0]["content"] == "Hello"
        assert result["messages"][0]["pinned"] is False

    def test_todo_document(self) -> None:
        """Simulate a todo document with subtasks."""
        todo_id = ObjectId()
        project_ref = ObjectId()
        doc = {
            "_id": todo_id,
            "title": "Buy groceries",
            "project_id": project_ref,
            "subtasks": [
                {"id": "sub1", "title": "Milk", "completed": False},
                {"id": "sub2", "title": "Bread", "completed": True},
            ],
            "labels": ["personal", "errands"],
            "completed": False,
        }

        result = serialize_document(doc)

        assert result["id"] == str(todo_id)
        assert result["project_id"] == str(project_ref)
        assert len(result["subtasks"]) == 2
        assert result["labels"] == ["personal", "errands"]

    def test_user_with_nested_integrations(self) -> None:
        """Simulate a user document with nested platform links."""
        user_id = ObjectId()
        doc = {
            "_id": user_id,
            "email": "test@example.com",
            "platform_links": {
                "discord": {"id": "disc123", "username": "user#1234"},
                "slack": {"id": "slack456"},
            },
            "onboarding": {"completed": True, "step": 5},
        }

        result = serialize_document(doc)

        assert result["id"] == str(user_id)
        assert result["platform_links"]["discord"]["id"] == "disc123"
        assert result["onboarding"]["completed"] is True


# ---------------------------------------------------------------------------
# serialize_document — edge cases
# ---------------------------------------------------------------------------


class TestSerializeDocumentEdgeCases:
    """Tests for unusual or edge-case inputs."""

    def test_document_with_only_id(self) -> None:
        """Document with only _id should result in {'id': str}."""
        oid = ObjectId()
        doc = {"_id": oid}

        result = serialize_document(doc)

        assert result == {"id": str(oid)}

    def test_numeric_values_preserved(self) -> None:
        """Various numeric types should be preserved."""
        doc = {"int_val": 42, "float_val": 3.14, "neg_val": -7, "zero": 0}

        result = serialize_document(doc)

        assert result["int_val"] == 42
        assert result["float_val"] == pytest.approx(3.14)
        assert result["neg_val"] == -7
        assert result["zero"] == 0

    def test_boolean_values_preserved(self) -> None:
        """Boolean values should not be modified."""
        doc = {"active": True, "deleted": False}

        result = serialize_document(doc)

        assert result["active"] is True
        assert result["deleted"] is False

    def test_none_field_values_preserved(self) -> None:
        """None field values should be preserved."""
        doc = {"description": None, "avatar": None}

        result = serialize_document(doc)

        assert result["description"] is None
        assert result["avatar"] is None

    def test_string_field_values_preserved(self) -> None:
        """String field values should be preserved."""
        doc = {"name": "hello", "email": "a@b.com"}

        result = serialize_document(doc)

        assert result["name"] == "hello"
        assert result["email"] == "a@b.com"

    def test_large_document(self) -> None:
        """Should handle documents with many fields efficiently."""
        oid = ObjectId()
        doc: dict[str, object] = {"_id": oid}
        for i in range(100):
            doc[f"field_{i}"] = f"value_{i}"

        result = serialize_document(doc)

        assert result["id"] == str(oid)
        assert len(result) == 101  # 100 fields + id
        assert result["field_0"] == "value_0"
        assert result["field_99"] == "value_99"

    def test_objectid_string_representation_format(self) -> None:
        """ObjectId string should be a 24-character hex string."""
        oid = ObjectId()
        doc = {"_id": oid}

        result = serialize_document(doc)

        assert len(result["id"]) == 24
        # Should be valid hex
        int(result["id"], 16)

    def test_list_with_single_dict_element(self) -> None:
        """Single-element list with a dict should still be serialized."""
        oid = ObjectId()
        doc = {"items": [{"_id": oid}]}

        result = serialize_document(doc)

        assert result["items"][0]["id"] == str(oid)

    def test_dict_with_objectid_key_name(self) -> None:
        """Field named 'objectid' (but not an ObjectId type) should be kept."""
        doc = {"objectid": "not-an-objectid"}

        result = serialize_document(doc)

        assert result["objectid"] == "not-an-objectid"
