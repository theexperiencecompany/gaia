"""Tests for app.db.chroma.chroma_triggers_store."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.base import PutOp

from app.db.chroma.chroma_triggers_store import (
    TRIGGERS_NAMESPACE,
    _build_put_operations,
    _build_trigger_description,
    _compute_trigger_diff,
    _compute_trigger_hash,
    _execute_batch_operations,
    _get_current_triggers_with_hashes,
    _get_existing_triggers_from_chroma,
    get_triggers_store,
)


# ---------------------------------------------------------------------------
# _compute_trigger_hash
# ---------------------------------------------------------------------------


class TestComputeTriggerHash:
    def test_basic_hash(self):
        trigger = SimpleNamespace(
            slug="new_email",
            name="New Email",
            description="Triggered on new email",
            workflow_trigger_schema=None,
        )
        result = _compute_trigger_hash("gmail", trigger)
        expected = hashlib.sha256(
            "new_email::New Email::Triggered on new email::gmail".encode()
        ).hexdigest()
        assert result == expected

    def test_hash_with_schema(self):
        schema = SimpleNamespace(config_schema={"type": "object"})
        trigger = SimpleNamespace(
            slug="s",
            name="N",
            description="D",
            workflow_trigger_schema=schema,
        )
        result = _compute_trigger_hash("int_id", trigger)
        content = "s::N::D::int_id::{'type': 'object'}"
        assert result == hashlib.sha256(content.encode()).hexdigest()

    def test_hash_with_none_description(self):
        trigger = SimpleNamespace(
            slug="s",
            name="N",
            description=None,
            workflow_trigger_schema=None,
        )
        result = _compute_trigger_hash("id", trigger)
        content = "s::N::::id"
        assert result == hashlib.sha256(content.encode()).hexdigest()

    def test_hash_with_schema_no_config(self):
        schema = SimpleNamespace(config_schema=None)
        trigger = SimpleNamespace(
            slug="s",
            name="N",
            description="D",
            workflow_trigger_schema=schema,
        )
        result = _compute_trigger_hash("id", trigger)
        # Schema present but config_schema is None => no schema in content
        content = "s::N::D::id"
        assert result == hashlib.sha256(content.encode()).hexdigest()


# ---------------------------------------------------------------------------
# _build_trigger_description
# ---------------------------------------------------------------------------


class TestBuildTriggerDescription:
    def test_builds_description(self):
        integration = SimpleNamespace(name="Gmail", category="email")
        trigger = SimpleNamespace(name="New Email", description="When email arrives")
        result = _build_trigger_description(integration, trigger)
        assert "New Email" in result
        assert "Gmail" in result
        assert "email" in result

    def test_handles_none_description(self):
        integration = SimpleNamespace(name="Slack", category=None)
        trigger = SimpleNamespace(name="Message", description=None)
        result = _build_trigger_description(integration, trigger)
        assert "Message" in result
        assert "general" in result


# ---------------------------------------------------------------------------
# _get_current_triggers_with_hashes
# ---------------------------------------------------------------------------


class TestGetCurrentTriggersWithHashes:
    def test_collects_triggers(self):
        trigger = SimpleNamespace(
            slug="new_email",
            name="New Email",
            description="Triggered on email",
            workflow_trigger_schema=None,
        )
        integ = SimpleNamespace(
            id="gmail",
            name="Gmail",
            category="email",
            associated_triggers=[trigger],
        )
        with patch(
            "app.db.chroma.chroma_triggers_store.OAUTH_INTEGRATIONS",
            [integ],
        ):
            result = _get_current_triggers_with_hashes()

        assert "new_email" in result
        assert result["new_email"]["integration_id"] == "gmail"

    def test_skips_integration_without_triggers(self):
        integ = SimpleNamespace(
            id="x",
            name="X",
            category="misc",
            associated_triggers=None,
        )
        with patch(
            "app.db.chroma.chroma_triggers_store.OAUTH_INTEGRATIONS",
            [integ],
        ):
            result = _get_current_triggers_with_hashes()
        assert result == {}

    def test_empty_triggers_list(self):
        integ = SimpleNamespace(
            id="x",
            name="X",
            category="misc",
            associated_triggers=[],
        )
        with patch(
            "app.db.chroma.chroma_triggers_store.OAUTH_INTEGRATIONS",
            [integ],
        ):
            result = _get_current_triggers_with_hashes()
        assert result == {}


# ---------------------------------------------------------------------------
# _get_existing_triggers_from_chroma
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetExistingTriggersFromChroma:
    async def test_returns_triggers_from_correct_namespace(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": [f"{TRIGGERS_NAMESPACE}::new_email"],
            "metadatas": [{"trigger_hash": "h1", "namespace": TRIGGERS_NAMESPACE}],
        }
        result = await _get_existing_triggers_from_chroma(collection)
        assert "new_email" in result
        assert result["new_email"]["hash"] == "h1"

    async def test_skips_wrong_namespace(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["other_ns::trigger_x"],
            "metadatas": [{"trigger_hash": "h", "namespace": "other_ns"}],
        }
        result = await _get_existing_triggers_from_chroma(collection)
        assert result == {}

    async def test_skips_ids_without_separator(self):
        collection = AsyncMock()
        collection.get.return_value = {
            "ids": ["no_separator"],
            "metadatas": [{"trigger_hash": "h"}],
        }
        result = await _get_existing_triggers_from_chroma(collection)
        assert result == {}

    async def test_handles_exception(self):
        collection = AsyncMock()
        collection.get.side_effect = RuntimeError("fail")
        result = await _get_existing_triggers_from_chroma(collection)
        assert result == {}

    async def test_handles_empty_data(self):
        collection = AsyncMock()
        collection.get.return_value = {"ids": None, "metadatas": None}
        result = await _get_existing_triggers_from_chroma(collection)
        assert result == {}


# ---------------------------------------------------------------------------
# _compute_trigger_diff
# ---------------------------------------------------------------------------


class TestComputeTriggerDiff:
    def test_new_trigger(self):
        current = {"slug_a": {"hash": "h1"}}
        existing: dict[str, dict] = {}
        upsert, delete = _compute_trigger_diff(current, existing)
        assert len(upsert) == 1
        assert len(delete) == 0

    def test_modified_trigger(self):
        current = {"slug_a": {"hash": "new_h"}}
        existing = {"slug_a": {"hash": "old_h"}}
        upsert, delete = _compute_trigger_diff(current, existing)
        assert len(upsert) == 1

    def test_unchanged_trigger(self):
        current = {"slug_a": {"hash": "same"}}
        existing = {"slug_a": {"hash": "same"}}
        upsert, delete = _compute_trigger_diff(current, existing)
        assert len(upsert) == 0
        assert len(delete) == 0

    def test_deleted_trigger(self):
        current: dict[str, dict] = {}
        existing = {"slug_gone": {"hash": "h"}}
        upsert, delete = _compute_trigger_diff(current, existing)
        assert len(delete) == 1
        assert delete[0] == "slug_gone"


# ---------------------------------------------------------------------------
# _build_put_operations
# ---------------------------------------------------------------------------


class TestBuildPutOperations:
    def test_upsert_operation(self):
        data = {
            "slug": "new_email",
            "name": "New Email",
            "description": "desc",
            "integration_id": "gmail",
            "integration_name": "Gmail",
            "category": "email",
            "rich_description": "rich",
            "hash": "h1",
        }
        ops = _build_put_operations([("new_email", data)], [])
        assert len(ops) == 1
        assert ops[0].namespace == (TRIGGERS_NAMESPACE,)
        assert ops[0].key == "new_email"
        assert ops[0].value["trigger_hash"] == "h1"

    def test_delete_operation(self):
        ops = _build_put_operations([], ["old_slug"])
        assert len(ops) == 1
        assert ops[0].value is None
        assert ops[0].key == "old_slug"

    def test_mixed_operations(self):
        data = {
            "slug": "s",
            "name": "N",
            "description": "D",
            "integration_id": "i",
            "integration_name": "I",
            "rich_description": "R",
            "hash": "h",
        }
        ops = _build_put_operations([("s", data)], ["old"])
        assert len(ops) == 2


# ---------------------------------------------------------------------------
# _execute_batch_operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExecuteBatchOperations:
    async def test_noop_on_empty_ops(self):
        store = AsyncMock()
        await _execute_batch_operations(store, [])
        store.abatch.assert_not_awaited()

    async def test_batches_operations(self):
        store = AsyncMock()
        ops = [MagicMock(spec=PutOp) for _ in range(75)]
        await _execute_batch_operations(store, ops, batch_size=50)
        assert store.abatch.await_count == 2


# ---------------------------------------------------------------------------
# get_triggers_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetTriggersStore:
    async def test_returns_store(self):
        mock_store = MagicMock()
        with patch("app.db.chroma.chroma_triggers_store.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=mock_store)
            result = await get_triggers_store()
        assert result is mock_store

    async def test_raises_when_none(self):
        with patch("app.db.chroma.chroma_triggers_store.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="not initialized"):
                await get_triggers_store()


# ---------------------------------------------------------------------------
# initialize_chroma_triggers_store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInitializeChromaTriggersStore:
    async def test_full_diff_pipeline_no_changes(self):
        """Test the full diff pipeline when nothing needs updating."""
        current = {"slug_a": {"hash": "h1"}}
        existing = {"slug_a": {"hash": "h1"}}
        upsert, delete = _compute_trigger_diff(current, existing)
        ops = _build_put_operations(upsert, delete)
        assert ops == []

    async def test_full_diff_pipeline_with_changes(self):
        """Test the full pipeline with upserts and deletes combined."""
        current = {
            "new_slug": {
                "hash": "h_new",
                "slug": "new_slug",
                "name": "New",
                "description": "D",
                "integration_id": "i",
                "integration_name": "I",
                "rich_description": "R",
            }
        }
        existing = {"old_slug": {"hash": "h_old"}}
        upsert, delete = _compute_trigger_diff(current, existing)
        ops = _build_put_operations(upsert, delete)
        # 1 upsert + 1 delete
        assert len(ops) == 2
        upsert_op = [o for o in ops if o.value is not None][0]
        delete_op = [o for o in ops if o.value is None][0]
        assert upsert_op.key == "new_slug"
        assert delete_op.key == "old_slug"
