"""Tests for MongoDB client initialization, collection access, and index creation.

Covers:
- MongoDB class: init with valid/invalid URI, ping, get_collection, _initialize_indexes
- init_mongodb: caching behavior, connection flow
- Collections module: lazy loading, caching, sync client, __getattr__
- Indexes module: create_all_indexes, individual index creators, error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.mongodb.mongodb import MongoDB, init_mongodb


# ---------------------------------------------------------------------------
# MongoDB class — __init__
# ---------------------------------------------------------------------------


class TestMongoDBInit:
    """Tests for MongoDB.__init__ constructor."""

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch("app.db.mongodb.mongodb.log")
    def test_successful_init(self, mock_log: MagicMock, mock_motor: MagicMock) -> None:
        """Valid URI and db_name should create client and database."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_client.get_database.return_value = mock_db
        mock_motor.return_value = mock_client

        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")

        mock_motor.assert_called_once()
        mock_client.get_database.assert_called_once_with("test_db")
        assert mongo.client is mock_client
        assert mongo.database is mock_db
        mock_log.set.assert_called_once()

    @patch("app.db.mongodb.mongodb.log")
    def test_none_uri_exits(self, mock_log: MagicMock) -> None:
        """None URI should log an error and call sys.exit(1)."""
        with pytest.raises(SystemExit) as exc_info:
            MongoDB(uri=None, db_name="test_db")

        assert exc_info.value.code == 1
        mock_log.error.assert_called_once()
        assert "URI" in mock_log.error.call_args[0][0]

    @patch("app.db.mongodb.mongodb.log")
    def test_empty_string_uri_exits(self, mock_log: MagicMock) -> None:
        """Empty string URI should also exit since it is falsy."""
        with pytest.raises(SystemExit) as exc_info:
            MongoDB(uri="", db_name="test_db")

        assert exc_info.value.code == 1

    @patch(
        "app.db.mongodb.mongodb.AsyncIOMotorClient", side_effect=Exception("conn error")
    )
    @patch("app.db.mongodb.mongodb.log")
    def test_motor_exception_exits(
        self, mock_log: MagicMock, mock_motor: MagicMock
    ) -> None:
        """Exception during Motor client creation should log error and exit."""
        with pytest.raises(SystemExit) as exc_info:
            MongoDB(uri="mongodb://bad-host:27017", db_name="test_db")

        assert exc_info.value.code == 1
        # Should log connection error status
        error_calls = [c for c in mock_log.set.call_args_list if "error" in str(c)]
        assert len(error_calls) >= 1
        mock_log.error.assert_called_once()
        assert "conn error" in mock_log.error.call_args[0][0]


# ---------------------------------------------------------------------------
# MongoDB class — ping
# ---------------------------------------------------------------------------


class TestMongoDBPing:
    """Tests for MongoDB.ping()."""

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch("app.db.mongodb.mongodb.pymongo.MongoClient")
    @patch("app.db.mongodb.mongodb.log")
    def test_ping_success(
        self,
        mock_log: MagicMock,
        mock_sync_client_cls: MagicMock,
        mock_motor: MagicMock,
    ) -> None:
        """Successful ping should not log errors."""
        mock_motor.return_value = MagicMock()
        mock_sync = MagicMock()
        mock_sync_client_cls.return_value = mock_sync

        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")
        mongo.ping()

        mock_sync.admin.command.assert_called_once_with("ping")
        mock_sync.close.assert_called_once()

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch(
        "app.db.mongodb.mongodb.pymongo.MongoClient",
        side_effect=Exception("ping failed"),
    )
    @patch("app.db.mongodb.mongodb.log")
    def test_ping_failure_logs_error(
        self,
        mock_log: MagicMock,
        mock_sync_client_cls: MagicMock,
        mock_motor: MagicMock,
    ) -> None:
        """Failed ping should log error but not raise."""
        mock_motor.return_value = MagicMock()

        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")
        # Reset log mock to clear init calls
        mock_log.reset_mock()

        mongo.ping()

        mock_log.error.assert_called_once()
        assert "Ping failed" in mock_log.error.call_args[0][0]


# ---------------------------------------------------------------------------
# MongoDB class — _initialize_indexes
# ---------------------------------------------------------------------------


class TestMongoDBInitializeIndexes:
    """Tests for MongoDB._initialize_indexes()."""

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch("app.db.mongodb.mongodb.log")
    async def test_initialize_indexes_calls_create_all(
        self, mock_log: MagicMock, mock_motor: MagicMock
    ) -> None:
        """Should import and call create_all_indexes."""
        mock_motor.return_value = MagicMock()
        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")

        with patch(
            "app.db.mongodb.indexes.create_all_indexes", new_callable=AsyncMock
        ) as mock_create:
            await mongo._initialize_indexes()
            mock_create.assert_awaited_once()

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch("app.db.mongodb.mongodb.log")
    async def test_initialize_indexes_handles_exception(
        self, mock_log: MagicMock, mock_motor: MagicMock
    ) -> None:
        """Exception in create_all_indexes should be caught and logged."""
        mock_motor.return_value = MagicMock()
        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")
        mock_log.reset_mock()

        with patch(
            "app.db.mongodb.indexes.create_all_indexes",
            new_callable=AsyncMock,
            side_effect=RuntimeError("index boom"),
        ):
            # Should not raise
            await mongo._initialize_indexes()

        mock_log.error.assert_called_once()
        assert "index" in mock_log.error.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# MongoDB class — get_collection
# ---------------------------------------------------------------------------


class TestMongoDBGetCollection:
    """Tests for MongoDB.get_collection()."""

    @patch("app.db.mongodb.mongodb.AsyncIOMotorClient")
    @patch("app.db.mongodb.mongodb.log")
    def test_get_collection_delegates_to_database(
        self, mock_log: MagicMock, mock_motor: MagicMock
    ) -> None:
        """get_collection should delegate to the database object."""
        mock_db = MagicMock()
        mock_db.get_collection.return_value = "fake_collection"
        mock_motor.return_value = MagicMock()
        mock_motor.return_value.get_database.return_value = mock_db

        mongo = MongoDB(uri="mongodb://localhost:27017", db_name="test_db")
        result = mongo.get_collection("users")

        mock_db.get_collection.assert_called_once_with("users")
        assert result == "fake_collection"


# ---------------------------------------------------------------------------
# init_mongodb (module-level factory)
# ---------------------------------------------------------------------------


class TestInitMongodb:
    """Tests for the init_mongodb() factory function."""

    @patch("app.db.mongodb.mongodb.MongoDB")
    @patch("app.db.mongodb.mongodb.log")
    def test_creates_instance_and_pings(
        self, mock_log: MagicMock, mock_class: MagicMock
    ) -> None:
        """init_mongodb should create a MongoDB instance, call ping, and return it."""
        # Clear LRU cache from previous runs
        init_mongodb.cache_clear()

        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        result = init_mongodb()

        mock_class.assert_called_once()
        mock_instance.ping.assert_called_once()
        assert result is mock_instance

        # Clean up for other tests
        init_mongodb.cache_clear()

    @patch("app.db.mongodb.mongodb.MongoDB")
    @patch("app.db.mongodb.mongodb.log")
    def test_lru_cache_returns_same_instance(
        self, mock_log: MagicMock, mock_class: MagicMock
    ) -> None:
        """Repeated calls should return the same cached instance."""
        init_mongodb.cache_clear()

        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        first = init_mongodb()
        second = init_mongodb()

        # Only one MongoDB instance should be created
        assert mock_class.call_count == 1
        assert first is second

        init_mongodb.cache_clear()


# ---------------------------------------------------------------------------
# Collections module — lazy loading
# ---------------------------------------------------------------------------


class TestCollectionsLazyLoading:
    """Tests for the collections lazy loading module."""

    @patch("app.db.mongodb.collections._collections_cache", {})
    @patch("app.db.mongodb.collections.log")
    def test_get_mongodb_instance_initializes_once(self, mock_log: MagicMock) -> None:
        """_get_mongodb_instance should call init_mongodb and cache the result."""
        import app.db.mongodb.collections as collections_mod
        import app.db.mongodb.mongodb as mongodb_mod

        mock_instance = MagicMock()

        # The real _get_mongodb_instance function — conftest replaces it globally,
        # so we must restore the real implementation for this test.
        def _real_get_mongodb_instance():
            if collections_mod._mongodb_instance is None:
                collections_mod._mongodb_instance = mongodb_mod.init_mongodb()
            return collections_mod._mongodb_instance

        old_fn = collections_mod._get_mongodb_instance
        old_instance = collections_mod._mongodb_instance
        old_init = mongodb_mod.init_mongodb
        collections_mod._get_mongodb_instance = _real_get_mongodb_instance
        collections_mod._mongodb_instance = None
        try:
            mock_init = MagicMock(return_value=mock_instance)
            mongodb_mod.init_mongodb = mock_init

            result = collections_mod._get_mongodb_instance()
            assert result is mock_instance
            mock_init.assert_called_once()
        finally:
            mongodb_mod.init_mongodb = old_init
            collections_mod._mongodb_instance = old_instance
            collections_mod._get_mongodb_instance = old_fn

    @patch("app.db.mongodb.collections._collections_cache", {})
    @patch("app.db.mongodb.collections.log")
    def test_get_collection_creates_and_caches(self, mock_log: MagicMock) -> None:
        """_get_collection should create the collection on first call, cache on second."""
        mock_instance = MagicMock()
        mock_collection = MagicMock()
        mock_instance.get_collection.return_value = mock_collection

        with patch(
            "app.db.mongodb.collections._get_mongodb_instance",
            return_value=mock_instance,
        ):
            from app.db.mongodb.collections import _get_collection

            first = _get_collection("users")
            second = _get_collection("users")

            assert first is mock_collection
            assert second is mock_collection
            # Should only be created once
            mock_instance.get_collection.assert_called_once_with("users")

    @patch("app.db.mongodb.collections._collections_cache", {})
    @patch("app.db.mongodb.collections.log")
    def test_get_collection_different_names(self, mock_log: MagicMock) -> None:
        """Different collection names should create separate collections."""
        mock_instance = MagicMock()
        col_a = MagicMock(name="col_a")
        col_b = MagicMock(name="col_b")
        mock_instance.get_collection.side_effect = lambda n: (
            col_a if n == "a" else col_b
        )

        with patch(
            "app.db.mongodb.collections._get_mongodb_instance",
            return_value=mock_instance,
        ):
            from app.db.mongodb.collections import _get_collection

            result_a = _get_collection("a")
            result_b = _get_collection("b")

            assert result_a is col_a
            assert result_b is col_b

    @patch("app.db.mongodb.collections._sync_client", None)
    @patch("app.db.mongodb.collections._sync_db", None)
    @patch("app.db.mongodb.collections.log")
    def test_get_sync_db_initializes(self, mock_log: MagicMock) -> None:
        """_get_sync_db should create a PyMongo client and database."""
        mock_sync_client = MagicMock()
        mock_sync_db = MagicMock()
        mock_sync_client.get_database.return_value = mock_sync_db

        with patch(
            "app.db.mongodb.collections.pymongo.MongoClient",
            return_value=mock_sync_client,
        ):
            from app.db.mongodb.collections import _get_sync_db

            result = _get_sync_db()
            assert result is mock_sync_db

    @patch("app.db.mongodb.collections._sync_collections_cache", {})
    @patch("app.db.mongodb.collections.log")
    def test_get_sync_collection_creates_and_caches(self, mock_log: MagicMock) -> None:
        """get_sync_collection should lazy-create and cache sync collections."""
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_db.get_collection.return_value = mock_col

        with patch("app.db.mongodb.collections._get_sync_db", return_value=mock_db):
            from app.db.mongodb.collections import get_sync_collection

            first = get_sync_collection("todos")
            second = get_sync_collection("todos")

            assert first is mock_col
            assert second is mock_col
            mock_db.get_collection.assert_called_once_with("todos")


# ---------------------------------------------------------------------------
# Collections module — __getattr__
# ---------------------------------------------------------------------------


class TestCollectionsGetattr:
    """Tests for module-level __getattr__ that enables lazy imports."""

    def test_getattr_known_collection_name(self) -> None:
        """Importing a known collection name should return via _get_collection."""
        with patch("app.db.mongodb.collections._get_collection") as mock_get:
            mock_get.return_value = MagicMock()

            from app.db.mongodb.collections import __getattr__

            __getattr__("users_collection")
            mock_get.assert_called_once_with("users")

    def test_getattr_unknown_name_raises(self) -> None:
        """Accessing an unknown attribute should raise AttributeError."""
        from app.db.mongodb.collections import __getattr__

        with pytest.raises(AttributeError, match="has no attribute"):
            __getattr__("nonexistent_collection")

    def test_getattr_all_collection_mappings(self) -> None:
        """All entries in _COLLECTION_MAPPINGS should be resolvable."""
        from app.db.mongodb.collections import _COLLECTION_MAPPINGS, __getattr__

        with patch("app.db.mongodb.collections._get_collection") as mock_get:
            mock_get.return_value = MagicMock()

            for attr_name, coll_name in _COLLECTION_MAPPINGS.items():
                mock_get.reset_mock()
                __getattr__(attr_name)
                mock_get.assert_called_once_with(coll_name)


# ---------------------------------------------------------------------------
# Indexes — create_all_indexes
# ---------------------------------------------------------------------------


class TestCreateAllIndexes:
    """Tests for create_all_indexes() and its error handling."""

    @patch("app.db.mongodb.indexes.log")
    async def test_create_all_indexes_success(self, mock_log: MagicMock) -> None:
        """All index creators succeeding should report full success."""
        # Patch all individual creators to be no-op coroutines
        index_creators = [
            "create_user_indexes",
            "create_conversation_indexes",
            "create_todo_indexes",
            "create_project_indexes",
            "create_goal_indexes",
            "create_note_indexes",
            "create_file_indexes",
            "create_mail_indexes",
            "create_calendar_indexes",
            "create_blog_indexes",
            "create_notification_indexes",
            "create_reminder_indexes",
            "create_workflow_indexes",
            "create_payment_indexes",
            "create_processed_webhook_indexes",
            "create_usage_indexes",
            "create_ai_models_indexes",
            "create_integration_indexes",
            "create_user_integration_indexes",
            "create_device_token_indexes",
            "create_vfs_indexes",
            "create_installed_skills_indexes",
            "create_workflow_execution_indexes",
            "create_bot_session_indexes",
        ]

        patches = {}
        for name in index_creators:
            patches[name] = patch(
                f"app.db.mongodb.indexes.{name}",
                new_callable=AsyncMock,
            )

        # Enter all patches
        mocks = {}
        for name, p in patches.items():
            mocks[name] = p.start()

        try:
            from app.db.mongodb.indexes import create_all_indexes

            await create_all_indexes()

            # All creators should be awaited
            for name, mock_fn in mocks.items():
                mock_fn.assert_awaited_once()

            # Check success log
            info_messages = [c[0][0] for c in mock_log.info.call_args_list]
            success_msgs = [m for m in info_messages if "completed" in m.lower()]
            assert len(success_msgs) >= 1
        finally:
            for p in patches.values():
                p.stop()

    @patch("app.db.mongodb.indexes.log")
    async def test_create_all_indexes_partial_failure(
        self, mock_log: MagicMock
    ) -> None:
        """Some index creators failing should be reported as exceptions, not crash."""
        index_creators = [
            "create_user_indexes",
            "create_conversation_indexes",
            "create_todo_indexes",
            "create_project_indexes",
            "create_goal_indexes",
            "create_note_indexes",
            "create_file_indexes",
            "create_mail_indexes",
            "create_calendar_indexes",
            "create_blog_indexes",
            "create_notification_indexes",
            "create_reminder_indexes",
            "create_workflow_indexes",
            "create_payment_indexes",
            "create_processed_webhook_indexes",
            "create_usage_indexes",
            "create_ai_models_indexes",
            "create_integration_indexes",
            "create_user_integration_indexes",
            "create_device_token_indexes",
            "create_vfs_indexes",
            "create_installed_skills_indexes",
            "create_workflow_execution_indexes",
            "create_bot_session_indexes",
        ]

        patches_dict = {}
        for name in index_creators:
            patches_dict[name] = patch(
                f"app.db.mongodb.indexes.{name}",
                new_callable=AsyncMock,
            )

        mocks = {}
        for name, p in patches_dict.items():
            mocks[name] = p.start()

        # Make the first creator raise
        mocks["create_user_indexes"].side_effect = RuntimeError("user index fail")

        try:
            from app.db.mongodb.indexes import create_all_indexes

            await create_all_indexes()

            # Should log the failure for users
            error_msgs = [c[0][0] for c in mock_log.error.call_args_list]
            assert any("users" in m for m in error_msgs)

            # Should also log warning about failed collections
            warning_msgs = [c[0][0] for c in mock_log.warning.call_args_list]
            assert any("Failed" in m for m in warning_msgs)
        finally:
            for p in patches_dict.values():
                p.stop()

    @patch("app.db.mongodb.indexes.log")
    async def test_create_all_indexes_critical_error_propagates(
        self, mock_log: MagicMock
    ) -> None:
        """A critical error in the orchestration itself should propagate."""
        with patch(
            "app.db.mongodb.indexes.asyncio.gather",
            new_callable=AsyncMock,
            side_effect=RuntimeError("gather exploded"),
        ):
            from app.db.mongodb.indexes import create_all_indexes

            with pytest.raises(RuntimeError, match="gather exploded"):
                await create_all_indexes()


# ---------------------------------------------------------------------------
# Indexes — _create_index_safe
# ---------------------------------------------------------------------------


class TestCreateIndexSafe:
    """Tests for _create_index_safe helper."""

    async def test_creates_index_normally(self) -> None:
        """Should delegate to collection.create_index on success."""
        from app.db.mongodb.indexes import _create_index_safe

        mock_collection = AsyncMock()
        await _create_index_safe(mock_collection, "field_name", unique=True)

        mock_collection.create_index.assert_awaited_once_with("field_name", unique=True)

    async def test_silently_skips_index_options_conflict(self) -> None:
        """IndexOptionsConflict errors should be silently swallowed."""
        from app.db.mongodb.indexes import _create_index_safe

        mock_collection = AsyncMock()
        mock_collection.create_index.side_effect = Exception(
            "IndexOptionsConflict: index already exists with different name"
        )

        # Should not raise
        await _create_index_safe(mock_collection, "field_name")

    async def test_silently_skips_code_85(self) -> None:
        """Errors containing code 85 should be silently swallowed."""
        from app.db.mongodb.indexes import _create_index_safe

        mock_collection = AsyncMock()
        mock_collection.create_index.side_effect = Exception(
            "{'code': 85, 'errmsg': 'index options conflict'}"
        )

        # Should not raise
        await _create_index_safe(mock_collection, [("a", 1)])

    async def test_reraises_other_exceptions(self) -> None:
        """Non-conflict exceptions should be re-raised."""
        from app.db.mongodb.indexes import _create_index_safe

        mock_collection = AsyncMock()
        mock_collection.create_index.side_effect = RuntimeError("network error")

        with pytest.raises(RuntimeError, match="network error"):
            await _create_index_safe(mock_collection, "field_name")


# ---------------------------------------------------------------------------
# Indexes — individual index creator functions
# ---------------------------------------------------------------------------


class TestIndividualIndexCreators:
    """Spot-check a few representative index creator functions."""

    async def test_create_user_indexes_calls_gather(self) -> None:
        """create_user_indexes should call create_index multiple times via gather."""
        mock_collection = AsyncMock()

        with (
            patch("app.db.mongodb.indexes.users_collection", mock_collection),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import create_user_indexes

            await create_user_indexes()

            # Should have called create_index for email (unique) plus several compound indexes
            assert mock_collection.create_index.await_count >= 5

    async def test_create_user_indexes_error_propagates(self) -> None:
        """Exception in create_user_indexes should be re-raised."""
        mock_collection = AsyncMock()
        mock_collection.create_index.side_effect = RuntimeError("timeout")

        with (
            patch("app.db.mongodb.indexes.users_collection", mock_collection),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import create_user_indexes

            with pytest.raises(RuntimeError, match="timeout"):
                await create_user_indexes()

    async def test_create_todo_indexes_includes_text_index(self) -> None:
        """create_todo_indexes should include a text search index."""
        mock_collection = AsyncMock()

        with (
            patch("app.db.mongodb.indexes.todos_collection", mock_collection),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import create_todo_indexes

            await create_todo_indexes()

            # Check that at least one call includes "text" index type
            text_calls = [
                c
                for c in mock_collection.create_index.call_args_list
                if any(
                    isinstance(arg, list) and any(t == "text" for _, t in arg)
                    for arg in c.args
                )
            ]
            assert len(text_calls) >= 1

    async def test_create_processed_webhook_indexes_has_ttl(self) -> None:
        """create_processed_webhook_indexes should include a TTL index."""
        mock_collection = AsyncMock()

        with (
            patch(
                "app.db.mongodb.indexes.processed_webhooks_collection", mock_collection
            ),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import create_processed_webhook_indexes

            await create_processed_webhook_indexes()

            # Check that expireAfterSeconds appears in kwargs
            ttl_calls = [
                c
                for c in mock_collection.create_index.call_args_list
                if c.kwargs.get("expireAfterSeconds") is not None
            ]
            assert len(ttl_calls) >= 1
            assert ttl_calls[0].kwargs["expireAfterSeconds"] == 2592000  # 30 days


# ---------------------------------------------------------------------------
# Indexes — get_index_status and log_index_summary
# ---------------------------------------------------------------------------


class TestIndexStatus:
    """Tests for get_index_status and log_index_summary."""

    async def test_get_index_status_returns_dict(self) -> None:
        """get_index_status should return a dict mapping collection names to index names."""
        mock_collection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"name": "idx_1"}, {"name": "idx_2"}]
        )
        mock_collection.list_indexes.return_value = mock_cursor

        # Patch all collections used in get_index_status
        collection_names = [
            "users_collection",
            "conversations_collection",
            "todos_collection",
            "projects_collection",
            "goals_collection",
            "notes_collection",
            "files_collection",
            "mail_collection",
            "calendars_collection",
            "blog_collection",
            "notifications_collection",
            "reminders_collection",
            "workflows_collection",
            "vfs_nodes_collection",
            "skills_collection",
        ]

        patches_dict = {
            name: patch(f"app.db.mongodb.indexes.{name}", mock_collection)
            for name in collection_names
        }

        for p in patches_dict.values():
            p.start()

        try:
            with patch("app.db.mongodb.indexes.log"):
                from app.db.mongodb.indexes import get_index_status

                result = await get_index_status()

            assert isinstance(result, dict)
            assert "users" in result
            assert result["users"] == ["idx_1", "idx_2"]
        finally:
            for p in patches_dict.values():
                p.stop()

    async def test_get_index_status_handles_error_per_collection(self) -> None:
        """If list_indexes fails for one collection, its entry should contain the error."""
        failing_collection = MagicMock()
        failing_cursor = MagicMock()
        failing_cursor.to_list = AsyncMock(side_effect=RuntimeError("network"))
        failing_collection.list_indexes.return_value = failing_cursor

        ok_collection = MagicMock()
        ok_cursor = MagicMock()
        ok_cursor.to_list = AsyncMock(return_value=[{"name": "_id_"}])
        ok_collection.list_indexes.return_value = ok_cursor

        collection_patches = {
            "users_collection": failing_collection,
            "conversations_collection": ok_collection,
            "todos_collection": ok_collection,
            "projects_collection": ok_collection,
            "goals_collection": ok_collection,
            "notes_collection": ok_collection,
            "files_collection": ok_collection,
            "mail_collection": ok_collection,
            "calendars_collection": ok_collection,
            "blog_collection": ok_collection,
            "notifications_collection": ok_collection,
            "reminders_collection": ok_collection,
            "workflows_collection": ok_collection,
            "vfs_nodes_collection": ok_collection,
            "skills_collection": ok_collection,
        }

        applied_patches = []
        for name, mock_obj in collection_patches.items():
            p = patch(f"app.db.mongodb.indexes.{name}", mock_obj)
            p.start()
            applied_patches.append(p)

        try:
            with patch("app.db.mongodb.indexes.log"):
                from app.db.mongodb.indexes import get_index_status

                result = await get_index_status()

            # The failing collection should have an ERROR entry
            assert any("ERROR" in idx for idx in result.get("users", []))
        finally:
            for p in applied_patches:
                p.stop()

    async def test_get_index_status_top_level_error(self) -> None:
        """A top-level exception should return an error dict."""
        # Force a top-level exception by making asyncio.gather raise
        with (
            patch(
                "app.db.mongodb.indexes.asyncio.gather",
                new_callable=AsyncMock,
                side_effect=RuntimeError("catastrophic"),
            ),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import get_index_status

            # The function catches top-level exceptions
            result = await get_index_status()
            assert "error" in result

    async def test_log_index_summary_calls_get_index_status(self) -> None:
        """log_index_summary should call get_index_status and log results."""
        mock_status = {"users": ["idx_1"], "todos": ["idx_1", "idx_2"]}

        with (
            patch(
                "app.db.mongodb.indexes.get_index_status",
                new_callable=AsyncMock,
                return_value=mock_status,
            ),
            patch("app.db.mongodb.indexes.log") as mock_log,
        ):
            from app.db.mongodb.indexes import log_index_summary

            await log_index_summary()

            # Should log total count
            info_msgs = [c[0][0] for c in mock_log.info.call_args_list]
            assert any("Total" in m for m in info_msgs)

    async def test_log_index_summary_warns_on_error_entries(self) -> None:
        """Collections with ERROR entries should be logged as warnings."""
        mock_status = {"users": ["ERROR: connection failed"]}

        with (
            patch(
                "app.db.mongodb.indexes.get_index_status",
                new_callable=AsyncMock,
                return_value=mock_status,
            ),
            patch("app.db.mongodb.indexes.log") as mock_log,
        ):
            from app.db.mongodb.indexes import log_index_summary

            await log_index_summary()

            mock_log.warning.assert_called()


# ---------------------------------------------------------------------------
# Indexes — _backfill_integration_slugs
# ---------------------------------------------------------------------------


class TestBackfillIntegrationSlugs:
    """Tests for the slug backfill helper."""

    async def test_backfill_no_documents(self) -> None:
        """When no docs need backfill, should do nothing."""
        mock_collection = MagicMock()
        mock_collection.update_one = AsyncMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_collection.find.return_value = mock_cursor

        with (
            patch("app.db.mongodb.indexes.integrations_collection", mock_collection),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import _backfill_integration_slugs

            await _backfill_integration_slugs()

        mock_collection.update_one.assert_not_awaited()

    async def test_backfill_updates_documents(self) -> None:
        """When docs exist, should generate slugs and update them."""
        doc = {"integration_id": "int_1", "name": "My Tool", "category": "productivity"}

        mock_collection = MagicMock()
        mock_collection.update_one = AsyncMock()
        # First call returns docs, second returns empty (loop exit)
        mock_cursor_with_docs = MagicMock()
        mock_cursor_with_docs.to_list = AsyncMock(return_value=[doc])
        mock_cursor_empty = MagicMock()
        mock_cursor_empty.to_list = AsyncMock(return_value=[])
        mock_collection.find.side_effect = [mock_cursor_with_docs, mock_cursor_empty]

        with (
            patch("app.db.mongodb.indexes.integrations_collection", mock_collection),
            patch(
                "app.db.mongodb.indexes.generate_unique_integration_slug",
                new_callable=AsyncMock,
                return_value="my-tool-productivity",
            ),
            patch("app.db.mongodb.indexes.log"),
        ):
            from app.db.mongodb.indexes import _backfill_integration_slugs

            await _backfill_integration_slugs()

        mock_collection.update_one.assert_awaited_once()

    async def test_backfill_handles_exception(self) -> None:
        """Exception during backfill should be caught (non-fatal)."""
        mock_collection = MagicMock()
        mock_collection.find.side_effect = RuntimeError("query failed")

        with (
            patch("app.db.mongodb.indexes.integrations_collection", mock_collection),
            patch("app.db.mongodb.indexes.log") as mock_log,
        ):
            from app.db.mongodb.indexes import _backfill_integration_slugs

            # Should not raise
            await _backfill_integration_slugs()

        mock_log.warning.assert_called_once()
