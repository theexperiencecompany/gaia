"""The id-codec and inventory seams of the account-deletion script.

Covers the lines this PR changed while unbreaking the quality gate: the
``object_id_filter`` codec (bson stays inside app/db per the
repository-boundaries lint) and the chroma collection-name fallback that
handles both client shapes without a branch mypy can prove dead.
"""

from unittest.mock import MagicMock

from bson import ObjectId

from app.db.mongodb.mongodb import object_id_filter
from app.scripts.delete_user_account import _chroma_inventory, _mongo_inventory

UID = "6a857e12040c9ae55b0b805d"


class TestObjectIdFilter:
    def test_builds_the_id_filter_from_the_hex_string(self) -> None:
        assert object_id_filter(UID) == {"_id": ObjectId(UID)}


class TestMongoInventory:
    def test_users_are_counted_by_object_id_on_top_of_the_string_scan(self) -> None:
        """The users row is keyed by ObjectId while every other collection keys
        user_id as a string — dropping the codec would silently zero the users
        count and the dry-run would claim the account has no user document."""
        db = MagicMock()
        db.list_collection_names.return_value = ["users"]
        # Non-zero on BOTH sides so the += is observable: a mutant that
        # overwrites instead of adding reports 1 rather than 3.
        per_collection = {"users": MagicMock(), "fs.files": MagicMock()}
        db.__getitem__.side_effect = per_collection.__getitem__
        per_collection["users"].count_documents.return_value = 2
        db.users.count_documents.return_value = 1
        per_collection["fs.files"].count_documents.return_value = 0

        counts = _mongo_inventory(db, UID, "user@example.com")

        assert counts == {"users": 3}
        db.users.count_documents.assert_called_once_with({"_id": ObjectId(UID)})

    def test_full_inventory_shape(self) -> None:
        """Every branch of the scan: fs.* handled via gridfs only, plain
        collections keyed by user_id string, support_requests by the $or over
        id and email, zero-count collections omitted."""
        email = "user@example.com"
        db = MagicMock()
        db.list_collection_names.return_value = [
            "todos",
            "fs.chunks",
            "support_requests",
            "empty_one",
        ]
        per_collection = {
            "todos": MagicMock(),
            "fs.chunks": MagicMock(),
            "support_requests": MagicMock(),
            "empty_one": MagicMock(),
            "fs.files": MagicMock(),
        }
        db.__getitem__.side_effect = per_collection.__getitem__
        per_collection["todos"].count_documents.return_value = 3
        per_collection["support_requests"].count_documents.return_value = 2
        per_collection["empty_one"].count_documents.return_value = 0
        per_collection["fs.files"].count_documents.return_value = 4

        counts = _mongo_inventory(db, UID, email)

        assert counts == {"todos": 3, "support_requests": 2, "fs.files(gridfs)": 4}
        per_collection["todos"].count_documents.assert_called_once_with({"user_id": UID})
        per_collection["support_requests"].count_documents.assert_called_with(
            {"$or": [{"user_id": UID}, {"user_email": email}]}
        )
        per_collection["fs.chunks"].count_documents.assert_not_called()
        per_collection["fs.files"].count_documents.assert_called_once_with(
            {"metadata.user_id": UID}
        )


class TestChromaInventory:
    def test_handles_both_collection_shapes(self) -> None:
        """Older chroma clients list plain name strings, newer ones objects with
        .name — the fallback must inventory both without an isinstance branch."""
        client = MagicMock()
        named = MagicMock()
        named.name = "memories"
        client.list_collections.return_value = [named, "documents"]
        client.get_collection.return_value.get.return_value = {"ids": ["a", "b"]}

        counts = _chroma_inventory(client, UID)

        assert counts == {"memories": 2, "documents": 2}
