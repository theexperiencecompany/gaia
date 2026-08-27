"""Tests for per-worktree ChromaDB collection namespacing.

Parallel worktrees share one local ChromaDB, and the tool/trigger stores index
by diffing the live collection against their own registry — so without a
per-worktree suffix, whichever API booted last deletes the rows it does not
recognise and a branch's tools vanish for the other. The suffix must apply when
set and be a no-op (prod-safe) when empty.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db.chroma import namespace as namespace_mod


@pytest.mark.unit
class TestNamespacedCollection:
    def test_empty_namespace_leaves_the_name_unchanged(self) -> None:
        # Production runs one API against a dedicated Chroma: names must not move.
        with patch.object(namespace_mod, "get_settings") as get_settings:
            get_settings.return_value = MagicMock(CHROMA_COLLECTION_NAMESPACE="")
            assert namespace_mod.namespaced_collection("langgraph_tools_store") == (
                "langgraph_tools_store"
            )

    def test_a_namespace_suffixes_every_collection(self) -> None:
        with patch.object(namespace_mod, "get_settings") as get_settings:
            get_settings.return_value = MagicMock(CHROMA_COLLECTION_NAMESPACE="wt510")
            assert namespace_mod.namespaced_collection("langgraph_tools_store") == (
                "langgraph_tools_store__wt510"
            )

    def test_two_namespaces_never_collide(self) -> None:
        # The whole point: worktree A and worktree B address different collections.
        with patch.object(namespace_mod, "get_settings") as get_settings:
            get_settings.return_value = MagicMock(CHROMA_COLLECTION_NAMESPACE="wt510")
            a = namespace_mod.namespaced_collection("langgraph_tools_store")
            get_settings.return_value = MagicMock(CHROMA_COLLECTION_NAMESPACE="wt230")
            b = namespace_mod.namespaced_collection("langgraph_tools_store")
        assert a != b


@pytest.mark.unit
class TestChromaStoreAppliesNamespace:
    def test_store_stores_the_namespaced_collection_name(self) -> None:
        from app.db.chroma.chroma_store import ChromaStore

        with patch(
            "app.db.chroma.chroma_store.namespaced_collection",
            return_value="langgraph_tools_store__wt510",
        ):
            store = ChromaStore(
                client=MagicMock(),
                collection_name="langgraph_tools_store",
            )
        assert store.collection_name == "langgraph_tools_store__wt510"
