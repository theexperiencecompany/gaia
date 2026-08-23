"""Unit tests for app.scripts.delete_user_account — per-store inventory helpers.

The operational deletion script is exercised end-to-end manually (it destroys
real data by design); these tests pin the pure inventory logic so the mutation
gate has a target and regressions in counting/filtering fail fast.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.scripts.delete_user_account import _chroma_inventory


class TestChromaInventory:
    """Tests for _chroma_inventory — counts user docs per Chroma collection."""

    def test_counts_ids_per_collection(self) -> None:
        """Each collection contributes the number of ids returned by .get()."""
        client = MagicMock()
        client.list_collections.return_value = [
            SimpleNamespace(name="docs"),
            SimpleNamespace(name="notes"),
        ]

        def get_collection(name: str) -> MagicMock:
            handle = MagicMock()
            handle.get.return_value = {"ids": ["a", "b", "c"]} if name == "docs" else {"ids": ["z"]}
            return handle

        client.get_collection.side_effect = get_collection

        counts = _chroma_inventory(client, "user-1")

        assert counts == {"docs": 3, "notes": 1}

    def test_empty_collections_are_omitted(self) -> None:
        """Collections with zero matching docs are absent from the result."""
        client = MagicMock()
        client.list_collections.return_value = [SimpleNamespace(name="empty")]

        handle = MagicMock()
        handle.get.return_value = {"ids": []}
        client.get_collection.return_value = handle

        assert _chroma_inventory(client, "user-1") == {}

    def test_missing_ids_key_treated_as_zero(self) -> None:
        """A payload without an 'ids' key counts as no documents, not a crash."""
        client = MagicMock()
        client.list_collections.return_value = [SimpleNamespace(name="odd")]

        handle = MagicMock()
        handle.get.return_value = {"metadatas": [{}]}
        client.get_collection.return_value = handle

        assert _chroma_inventory(client, "user-1") == {}

    def test_get_filters_on_exact_user_id(self) -> None:
        """The query filters on exact user_id equality with the standard caps."""
        client = MagicMock()
        client.list_collections.return_value = [SimpleNamespace(name="docs")]

        handle = MagicMock()
        handle.get.return_value = {"ids": ["a"]}
        client.get_collection.return_value = handle

        _chroma_inventory(client, "user-42")

        handle.get.assert_called_once_with(where={"user_id": "user-42"}, limit=200_000, include=[])

    def test_no_collections_yields_empty_inventory(self) -> None:
        """An empty Chroma instance inventories to {}."""
        client = MagicMock()
        client.list_collections.return_value = []

        assert _chroma_inventory(client, "user-1") == {}
