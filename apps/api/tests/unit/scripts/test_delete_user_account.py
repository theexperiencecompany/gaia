"""Unit tests for the account-deletion script's ChromaDB inventory step.

``_chroma_inventory`` must read each collection's name off the ``Collection``
object chromadb ≥0.6 returns from ``list_collections`` (the pre-0.6 API
returned plain strings — treating the object as one would count nothing), and
only report collections that actually hold the user's data.
"""

from unittest.mock import MagicMock

from app.scripts.delete_user_account import _chroma_inventory


def _client(collections: list[str], ids_by_name: dict[str, list[str]]) -> MagicMock:
    client = MagicMock()

    def _collection(name: str) -> MagicMock:
        col = MagicMock()
        col.name = name
        return col

    client.list_collections.return_value = [_collection(n) for n in collections]
    gets = {
        n: MagicMock(get=MagicMock(return_value={"ids": ids, "metadatas": [], "documents": []}))
        for n, ids in ids_by_name.items()
    }
    client.get_collection.side_effect = lambda name: gets[name]
    return client


def test_counts_only_collections_holding_the_users_data() -> None:
    client = _client(["memory", "tool_cache"], {"memory": ["id-1", "id-2"], "tool_cache": []})

    counts = _chroma_inventory(client, "uid-1")

    assert counts == {"memory": 2}
    client.get_collection.assert_any_call("memory")
    client.get_collection.assert_any_call("tool_cache")
    _, kwargs = client.get_collection("memory").get.call_args
    assert kwargs["where"] == {"user_id": "uid-1"}
