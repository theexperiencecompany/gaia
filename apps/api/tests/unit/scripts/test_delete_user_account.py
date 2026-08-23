"""Pins for the account-deletion script's inventory counters.

The inventories are the dry-run's output and the verification sweep's baseline,
so a wrong count is a wrong erasure report. Kept to pure fakes: the script's
store clients are exercised for real in operations, not here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.scripts.delete_user_account import PG_USER_TABLES, _chroma_inventory, _pg_inventory


class _FakeChromaCollection:
    def __init__(self, name: str, ids: list[str]) -> None:
        self._name = name
        self._ids = ids

    @property
    def name(self) -> str:
        return self._name

    def get(self, where: dict[str, str], limit: int, include: list[str]) -> dict[str, list[str]]:
        assert where == {"user_id": "uid-1"}
        return {"ids": self._ids}


class TestChromaInventory:
    def test_counts_per_collection_and_skips_empty_ones(self) -> None:
        client = MagicMock()
        client.list_collections.return_value = [
            _FakeChromaCollection("memories", ["a", "b"]),
            _FakeChromaCollection("journal", []),
        ]
        client.get_collection.side_effect = lambda name: next(
            c for c in client.list_collections.return_value if c.name == name
        )

        counts = _chroma_inventory(client, "uid-1")

        assert counts == {"memories": 2}


class TestPgInventory:
    def test_counts_per_table_and_drops_zero_rows(self) -> None:
        rows = iter([(3,)] + [(0,)] * (len(PG_USER_TABLES) - 1))
        cursor = MagicMock()
        cursor.fetchone.side_effect = lambda: next(rows)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        counts = _pg_inventory(conn, "uid-1")

        assert counts == {PG_USER_TABLES[0]: 3}
        assert cursor.execute.call_count == len(PG_USER_TABLES)
