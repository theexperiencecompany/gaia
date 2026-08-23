"""Inventory helpers for the operational account-deletion script.

The script is the GDPR/erasure path, so its inventory is what tells an operator
whether anything of the user's survived. A collection silently skipped here reads
as "nothing left to delete" — the one failure this file exists to catch.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.scripts.delete_user_account import _chroma_inventory

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
