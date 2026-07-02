"""Unit tests for TriggerService.resync_user_workflow_triggers (reconnect self-heal)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.workflow.trigger_service import TriggerService

MODULE = "app.services.workflow.trigger_service"


def _wf(wf_id: str, trigger_name: str, ids: list[str] | None) -> dict:
    return {
        "_id": wf_id,
        "user_id": "user1",
        "activated": True,
        "trigger_config": {
            "type": "integration",
            "trigger_name": trigger_name,
            "enabled": True,
            "composio_trigger_ids": ids,
        },
    }


def _collection_returning(docs: list[dict]) -> MagicMock:
    async def _aiter(_query):
        for d in docs:
            yield d

    collection = MagicMock()
    collection.find = lambda query: _aiter(query)
    collection.update_one = AsyncMock()
    return collection


@pytest.mark.asyncio
class TestResyncUserWorkflowTriggers:
    async def test_repoints_ids_and_unregisters_old(self):
        collection = _collection_returning([_wf("wf1", "gmail_poll_inbox", ["ti_old"])])
        with (
            patch(f"{MODULE}.workflows_collection", collection),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=["ti_new"])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])

        collection.update_one.assert_awaited_once_with(
            {"_id": "wf1"},
            {"$set": {"trigger_config.composio_trigger_ids": ["ti_new"]}},
        )
        unreg.assert_awaited_once_with("user1", "gmail_poll_inbox", ["ti_old"], "wf1")

    async def test_no_trigger_names_is_a_noop(self):
        collection = _collection_returning([])
        with patch(f"{MODULE}.workflows_collection", collection):
            await TriggerService.resync_user_workflow_triggers("user1", [])
        collection.update_one.assert_not_awaited()

    async def test_account_level_empty_ids_skips_update(self):
        """gmail_new_message registration returns [] — nothing to repoint."""
        collection = _collection_returning([_wf("wf1", "gmail_new_message", None)])
        with (
            patch(f"{MODULE}.workflows_collection", collection),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=[])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_new_message"])
        collection.update_one.assert_not_awaited()
        unreg.assert_not_awaited()

    async def test_unchanged_ids_skip_update(self):
        collection = _collection_returning([_wf("wf1", "gmail_poll_inbox", ["ti_same"])])
        with (
            patch(f"{MODULE}.workflows_collection", collection),
            patch.object(TriggerService, "register_triggers", AsyncMock(return_value=["ti_same"])),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()) as unreg,
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])
        collection.update_one.assert_not_awaited()
        unreg.assert_not_awaited()

    async def test_one_failure_does_not_block_the_rest(self):
        collection = _collection_returning(
            [
                _wf("wf_bad", "gmail_poll_inbox", ["ti_a"]),
                _wf("wf_good", "gmail_poll_inbox", ["ti_b"]),
            ]
        )
        register = AsyncMock(side_effect=[RuntimeError("composio down"), ["ti_new"]])
        with (
            patch(f"{MODULE}.workflows_collection", collection),
            patch.object(TriggerService, "register_triggers", register),
            patch.object(TriggerService, "unregister_triggers", AsyncMock()),
        ):
            await TriggerService.resync_user_workflow_triggers("user1", ["gmail_poll_inbox"])

        collection.update_one.assert_awaited_once_with(
            {"_id": "wf_good"},
            {"$set": {"trigger_config.composio_trigger_ids": ["ti_new"]}},
        )
