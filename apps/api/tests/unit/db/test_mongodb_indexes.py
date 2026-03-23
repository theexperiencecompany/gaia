"""Tests for MongoDB index creation module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Patch all collection imports before importing the module under test
_COLLECTION_NAMES = [
    "ai_models_collection",
    "blog_collection",
    "bot_sessions_collection",
    "calendars_collection",
    "conversations_collection",
    "device_tokens_collection",
    "files_collection",
    "goals_collection",
    "integrations_collection",
    "mail_collection",
    "notes_collection",
    "notifications_collection",
    "payments_collection",
    "plans_collection",
    "processed_webhooks_collection",
    "projects_collection",
    "reminders_collection",
    "skills_collection",
    "subscriptions_collection",
    "todos_collection",
    "usage_snapshots_collection",
    "user_integrations_collection",
    "users_collection",
    "vfs_nodes_collection",
    "workflow_executions_collection",
    "workflows_collection",
]


def _make_mock_collection() -> AsyncMock:
    coll = AsyncMock()
    coll.create_index = AsyncMock(return_value="index_name")

    # Mock list_indexes for get_index_status
    index_cursor = MagicMock()
    index_cursor.to_list = AsyncMock(return_value=[{"name": "test_index"}])
    coll.list_indexes = MagicMock(return_value=index_cursor)

    # Mock find for backfill
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    coll.find = MagicMock(return_value=cursor)
    coll.update_one = AsyncMock()

    return coll


@pytest.fixture(autouse=True)
def mock_collections(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Mock all MongoDB collections."""
    mocks = {}
    for name in _COLLECTION_NAMES:
        mock = _make_mock_collection()
        mocks[name] = mock
        monkeypatch.setattr(f"app.db.mongodb.indexes.{name}", mock)
    return mocks


@pytest.fixture(autouse=True)
def mock_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock helper functions."""
    monkeypatch.setattr(
        "app.db.mongodb.indexes.generate_unique_integration_slug",
        AsyncMock(return_value="test-slug"),
    )


# ---------------------------------------------------------------------------
# Individual index creation functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndividualIndexCreation:
    async def test_create_user_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_user_indexes

        await create_user_indexes()
        assert mock_collections["users_collection"].create_index.call_count >= 5

    async def test_create_conversation_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_conversation_indexes

        await create_conversation_indexes()
        assert mock_collections["conversations_collection"].create_index.call_count >= 4

    async def test_create_todo_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_todo_indexes

        await create_todo_indexes()
        assert mock_collections["todos_collection"].create_index.call_count >= 10

    async def test_create_project_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_project_indexes

        await create_project_indexes()
        assert mock_collections["projects_collection"].create_index.call_count >= 3

    async def test_create_goal_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_goal_indexes

        await create_goal_indexes()
        assert mock_collections["goals_collection"].create_index.call_count >= 3

    async def test_create_note_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_note_indexes

        await create_note_indexes()
        assert mock_collections["notes_collection"].create_index.call_count >= 3

    async def test_create_file_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_file_indexes

        await create_file_indexes()
        assert mock_collections["files_collection"].create_index.call_count >= 4

    async def test_create_mail_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_mail_indexes

        await create_mail_indexes()
        assert mock_collections["mail_collection"].create_index.call_count >= 2

    async def test_create_calendar_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_calendar_indexes

        await create_calendar_indexes()
        assert mock_collections["calendars_collection"].create_index.call_count >= 3

    async def test_create_blog_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_blog_indexes

        await create_blog_indexes()
        assert mock_collections["blog_collection"].create_index.call_count >= 5

    async def test_create_notification_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_notification_indexes

        await create_notification_indexes()
        assert mock_collections["notifications_collection"].create_index.call_count >= 3

    async def test_create_reminder_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_reminder_indexes

        await create_reminder_indexes()
        assert mock_collections["reminders_collection"].create_index.call_count >= 5

    async def test_create_workflow_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_workflow_indexes

        await create_workflow_indexes()
        assert mock_collections["workflows_collection"].create_index.call_count >= 10

    async def test_create_workflow_execution_indexes(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_workflow_execution_indexes

        await create_workflow_execution_indexes()
        assert (
            mock_collections["workflow_executions_collection"].create_index.call_count
            >= 4
        )

    async def test_create_payment_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_payment_indexes

        await create_payment_indexes()
        # payments + subscriptions + plans
        total = (
            mock_collections["payments_collection"].create_index.call_count
            + mock_collections["subscriptions_collection"].create_index.call_count
            + mock_collections["plans_collection"].create_index.call_count
        )
        assert total >= 10

    async def test_create_processed_webhook_indexes(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_processed_webhook_indexes

        await create_processed_webhook_indexes()
        assert (
            mock_collections["processed_webhooks_collection"].create_index.call_count
            >= 2
        )

    async def test_create_usage_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_usage_indexes

        await create_usage_indexes()
        assert (
            mock_collections["usage_snapshots_collection"].create_index.call_count >= 4
        )

    async def test_create_ai_models_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_ai_models_indexes

        await create_ai_models_indexes()
        assert mock_collections["ai_models_collection"].create_index.call_count >= 6

    async def test_create_device_token_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_device_token_indexes

        await create_device_token_indexes()
        assert mock_collections["device_tokens_collection"].create_index.call_count >= 3

    async def test_create_bot_session_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_bot_session_indexes

        await create_bot_session_indexes()
        assert mock_collections["bot_sessions_collection"].create_index.call_count >= 4


# ---------------------------------------------------------------------------
# _create_index_safe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateIndexSafe:
    async def test_normal_creation(self) -> None:
        from app.db.mongodb.indexes import _create_index_safe

        coll = AsyncMock()
        coll.create_index = AsyncMock()
        await _create_index_safe(coll, "field", unique=True)
        coll.create_index.assert_called_once_with("field", unique=True)

    async def test_index_options_conflict_silently_skipped(self) -> None:
        from app.db.mongodb.indexes import _create_index_safe

        coll = AsyncMock()
        coll.create_index = AsyncMock(
            side_effect=Exception("IndexOptionsConflict: existing index")
        )
        # Should not raise
        await _create_index_safe(coll, "field")

    async def test_index_options_conflict_code_85_skipped(self) -> None:
        from app.db.mongodb.indexes import _create_index_safe

        coll = AsyncMock()
        coll.create_index = AsyncMock(
            side_effect=Exception("Something with 'code': 85 in it")
        )
        await _create_index_safe(coll, "field")

    async def test_other_errors_reraise(self) -> None:
        from app.db.mongodb.indexes import _create_index_safe

        coll = AsyncMock()
        coll.create_index = AsyncMock(side_effect=RuntimeError("connection lost"))

        with pytest.raises(RuntimeError, match="connection lost"):
            await _create_index_safe(coll, "field")


# ---------------------------------------------------------------------------
# Integration and VFS indexes (use _create_index_safe)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSafeIndexCreation:
    async def test_create_integration_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_integration_indexes

        await create_integration_indexes()
        # Uses _create_index_safe, so we check the collection mock
        coll = mock_collections["integrations_collection"]
        assert coll.create_index.call_count >= 5

    async def test_create_user_integration_indexes(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_user_integration_indexes

        await create_user_integration_indexes()
        coll = mock_collections["user_integrations_collection"]
        assert coll.create_index.call_count >= 4

    async def test_create_vfs_indexes(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_vfs_indexes

        await create_vfs_indexes()
        coll = mock_collections["vfs_nodes_collection"]
        assert coll.create_index.call_count >= 7

    async def test_create_installed_skills_indexes(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_installed_skills_indexes

        await create_installed_skills_indexes()
        coll = mock_collections["skills_collection"]
        assert coll.create_index.call_count >= 3


# ---------------------------------------------------------------------------
# _backfill_integration_slugs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBackfillIntegrationSlugs:
    async def test_no_docs_to_backfill(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import _backfill_integration_slugs

        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        mock_collections["integrations_collection"].find = MagicMock(
            return_value=cursor
        )

        await _backfill_integration_slugs()
        mock_collections["integrations_collection"].update_one.assert_not_called()

    async def test_backfills_slugs_for_docs(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import _backfill_integration_slugs

        docs = [
            {"integration_id": "int1", "name": "My Int", "category": "custom"},
        ]
        cursor1 = MagicMock()
        cursor1.to_list = AsyncMock(return_value=docs)
        cursor2 = MagicMock()
        cursor2.to_list = AsyncMock(return_value=[])

        mock_collections["integrations_collection"].find = MagicMock(
            side_effect=[cursor1, cursor2]
        )

        await _backfill_integration_slugs()
        mock_collections["integrations_collection"].update_one.assert_called_once()

    async def test_backfill_handles_error_gracefully(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import _backfill_integration_slugs

        mock_collections["integrations_collection"].find = MagicMock(
            side_effect=RuntimeError("db error")
        )

        # Should not raise (non-fatal)
        await _backfill_integration_slugs()


# ---------------------------------------------------------------------------
# Error handling in individual create functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIndexCreationErrors:
    async def test_user_index_error_raises(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_user_indexes

        mock_collections["users_collection"].create_index = AsyncMock(
            side_effect=RuntimeError("fail")
        )
        with pytest.raises(RuntimeError):
            await create_user_indexes()

    async def test_todo_index_error_raises(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_todo_indexes

        mock_collections["todos_collection"].create_index = AsyncMock(
            side_effect=RuntimeError("fail")
        )
        with pytest.raises(RuntimeError):
            await create_todo_indexes()


# ---------------------------------------------------------------------------
# create_all_indexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateAllIndexes:
    async def test_all_succeed(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import create_all_indexes

        await create_all_indexes()
        # Should complete without error

    async def test_partial_failure_still_completes(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_all_indexes

        # Make users fail
        mock_collections["users_collection"].create_index = AsyncMock(
            side_effect=RuntimeError("users fail")
        )

        # create_all_indexes uses gather with return_exceptions, so should not raise
        await create_all_indexes()

    @patch("app.db.mongodb.indexes.log")
    async def test_critical_error_raises(
        self, mock_log: MagicMock, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import create_all_indexes

        with patch(
            "app.db.mongodb.indexes.asyncio.gather",
            side_effect=RuntimeError("critical"),
        ):
            with pytest.raises(RuntimeError, match="critical"):
                await create_all_indexes()


# ---------------------------------------------------------------------------
# get_index_status / log_index_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetIndexStatus:
    async def test_returns_index_dict(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import get_index_status

        result = await get_index_status()
        assert isinstance(result, dict)
        assert "users" in result
        assert "test_index" in result["users"]

    async def test_handles_collection_error(self, mock_collections: dict) -> None:
        from app.db.mongodb.indexes import get_index_status

        idx_cursor = MagicMock()
        idx_cursor.to_list = AsyncMock(side_effect=RuntimeError("nope"))
        mock_collections["users_collection"].list_indexes = MagicMock(
            return_value=idx_cursor
        )

        result = await get_index_status()
        assert "users" in result
        assert any("ERROR" in s for s in result["users"])

    async def test_global_error_returns_error_dict(
        self, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import get_index_status

        with patch(
            "app.db.mongodb.indexes.asyncio.gather", side_effect=RuntimeError("boom")
        ):
            result = await get_index_status()
        assert "error" in result


@pytest.mark.asyncio
class TestLogIndexSummary:
    @patch("app.db.mongodb.indexes.log")
    async def test_logs_summary(
        self, mock_log: MagicMock, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import log_index_summary

        await log_index_summary()
        assert mock_log.info.call_count >= 3

    @patch("app.db.mongodb.indexes.log")
    async def test_handles_error(
        self, mock_log: MagicMock, mock_collections: dict
    ) -> None:
        from app.db.mongodb.indexes import log_index_summary

        with patch(
            "app.db.mongodb.indexes.get_index_status", side_effect=RuntimeError("boom")
        ):
            await log_index_summary()
        mock_log.error.assert_called()
