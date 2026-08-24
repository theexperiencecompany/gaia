"""Inventory helpers for the operational account-deletion script.

The script is the GDPR/erasure path, so its inventory is what tells an operator
whether anything of the user's survived. A collection silently skipped here reads
as "nothing left to delete" — the one failure this file exists to catch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from bson import ObjectId
import pytest

from app.db.mongodb.mongodb import object_id_filter
from app.scripts.delete_user_account import (
    PG_USER_TABLES,
    _chroma_inventory,
    _mongo_inventory,
    _pg_inventory,
)

UID = "67689b80006f6eec3f6f6df8"


class FakeCollection:
    """A chroma collection whose `.get()` records the filter it was called with."""

    def __init__(self, name: str, ids: list[str]) -> None:
        self.name = name
        self._ids = ids
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ids": list(self._ids)}


class FakeClient:
    def __init__(self, collections: list[FakeCollection]) -> None:
        self._collections = {c.name: c for c in collections}

    def list_collections(self) -> list[FakeCollection]:
        return list(self._collections.values())

    def get_collection(self, name: str) -> FakeCollection:
        return self._collections[name]


@pytest.mark.unit
class TestChromaInventory:
    def test_counts_each_collections_matching_vectors(self) -> None:
        client = FakeClient(
            [
                FakeCollection("memories", ["a", "b", "c"]),
                FakeCollection("conversations", ["d"]),
            ]
        )

        assert _chroma_inventory(client, UID) == {"memories": 3, "conversations": 1}

    def test_collections_holding_nothing_are_left_out(self) -> None:
        """The inventory is a remnant report: a zero would read as a surviving
        collection an operator then goes looking for."""
        client = FakeClient([FakeCollection("memories", ["a"]), FakeCollection("empty", [])])

        assert _chroma_inventory(client, UID) == {"memories": 1}

    def test_every_collection_is_filtered_to_this_user(self) -> None:
        """The filter is the whole safety story — an unfiltered read would report
        (and the delete pass would then act on) other people's vectors."""
        memories = FakeCollection("memories", ["a"])
        client = FakeClient([memories])

        _chroma_inventory(client, UID)

        assert memories.calls[0]["where"] == {"user_id": UID}

    def test_a_collection_with_no_ids_key_counts_as_empty(self) -> None:
        """chroma omits `ids` rather than returning an empty list on some backends."""

        class NoIds(FakeCollection):
            def get(self, **kwargs: Any) -> dict[str, Any]:
                return {}

        assert _chroma_inventory(FakeClient([NoIds("memories", [])]), UID) == {}


@pytest.mark.unit
class TestObjectIdFilter:
    def test_builds_the_id_filter_from_the_hex_string(self) -> None:
        """The id-codec lives in app/db (repository-boundaries lint), so the
        raw-connection script never imports bson itself."""
        assert object_id_filter(UID) == {"_id": ObjectId(UID)}


@pytest.mark.unit
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


@pytest.mark.unit
class TestPgInventory:
    def test_counts_every_user_table_and_omits_the_empty_ones(self) -> None:
        """Postgres is scanned by a fixed table list rather than a catalogue
        query, so a table dropped from PG_USER_TABLES is never counted and never
        deleted — the inventory would report the user as fully erased."""
        rows = iter([(3,)] + [(0,)] * (len(PG_USER_TABLES) - 1))
        cursor = MagicMock()
        cursor.fetchone.side_effect = lambda: next(rows)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        counts = _pg_inventory(conn, UID)

        assert counts == {PG_USER_TABLES[0]: 3}
        assert cursor.execute.call_count == len(PG_USER_TABLES)

    def test_every_query_is_scoped_to_this_user(self) -> None:
        """An unscoped count would report (and the delete pass then act on)
        other people's rows."""
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        _pg_inventory(conn, UID)

        for call in cursor.execute.call_args_list:
            sql, params = call.args
            assert "WHERE user_id = %s" in sql
            assert params == (UID,)
