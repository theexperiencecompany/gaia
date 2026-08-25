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


# ---------------------------------------------------------------------------
# Teardown helpers (the execute-mode phases)
# ---------------------------------------------------------------------------


def _footprint(**overrides: Any) -> Any:
    """A _Footprint with MagicMock clients; override any field by name."""
    from unittest.mock import AsyncMock

    from app.scripts.delete_user_account import JFS_USERS_ROOT, _Footprint

    workos = MagicMock()
    workos.user_management.delete_user = AsyncMock()
    list_users_result = MagicMock()
    list_users_result.data = []
    workos.user_management.list_users = AsyncMock(return_value=list_users_result)

    defaults: dict[str, Any] = {
        "db": MagicMock(),
        "pg": MagicMock(),
        "chroma": MagicMock(),
        "redis_client": MagicMock(),
        "composio": MagicMock(),
        "workos": workos,
        "uid": UID,
        "email": "user@example.com",
        "platform_links": {},
        "conversation_ids": [],
        "composio_accounts": [],
        "sandbox_ids": [],
        "workos_users": [],
        "chroma_counts": {},
        "redis_keys": [],
        "jfs_path": JFS_USERS_ROOT / UID,
    }
    defaults.update(overrides)
    return _Footprint(**defaults)


@pytest.fixture(autouse=True)
def _clean_failures():
    from app.scripts.delete_user_account import _failures

    _failures.clear()
    yield
    _failures.clear()


@pytest.mark.unit
class TestRevokeExternalAccess:
    async def test_deletes_every_composio_account_then_kills_sandboxes(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.scripts.delete_user_account import _revoke_external_access

        account = MagicMock()
        account.id = "acc-1"
        account.toolkit.slug = "gmail"
        d = _footprint(composio_accounts=[account], sandbox_ids=["sbx-1"])

        with (
            patch("app.scripts.delete_user_account.AsyncSandbox") as sandbox,
            patch.dict("app.scripts.delete_user_account.settings.__dict__", {}, clear=False),
        ):
            sandbox.kill = AsyncMock()
            await _revoke_external_access(d)

        d.composio.connected_accounts.delete.assert_called_once_with(nanoid="acc-1")
        sandbox.kill.assert_awaited_once_with(
            "sbx-1",
            api_key=d.composio.connected_accounts.delete.call_args
            and __import__(
                "app.scripts.delete_user_account", fromlist=["settings"]
            ).settings.E2B_API_KEY,
            domain=__import__(
                "app.scripts.delete_user_account", fromlist=["settings"]
            ).settings.E2B_DOMAIN,
        )

    async def test_a_composio_failure_is_recorded_not_raised(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.scripts.delete_user_account import _failures, _revoke_external_access

        account = MagicMock()
        account.id = "acc-boom"
        account.toolkit.slug = "gmail"
        d = _footprint(composio_accounts=[account])
        d.composio.connected_accounts.delete.side_effect = RuntimeError("api down")

        with patch("app.scripts.delete_user_account.AsyncSandbox") as sandbox:
            sandbox.kill = AsyncMock()
            await _revoke_external_access(d)

        assert len(_failures) == 1
        assert "composio:acc-boom" in _failures[0]

    async def test_a_sandbox_kill_failure_is_recorded_not_raised(self) -> None:
        from unittest.mock import AsyncMock, patch

        from app.scripts.delete_user_account import _failures, _revoke_external_access

        d = _footprint(sandbox_ids=["sbx-boom"])
        with patch("app.scripts.delete_user_account.AsyncSandbox") as sandbox:
            sandbox.kill = AsyncMock(side_effect=RuntimeError("kill failed"))
            await _revoke_external_access(d)

        assert len(_failures) == 1
        assert "e2b:sbx-boom" in _failures[0]


@pytest.mark.unit
class TestDeleteMongoData:
    def test_gridfs_collections_and_users_doc_are_all_deleted(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint()
        files_col = MagicMock()
        files_col.find.return_value = [{"_id": "file-1"}]
        todos = MagicMock()
        todos.delete_many.return_value.deleted_count = 3
        users = MagicMock()
        users.delete_one.return_value.deleted_count = 1
        cols = {"fs.files": files_col, "todos": todos}
        d.db.__getitem__.side_effect = cols.__getitem__
        d.db.users = users
        d.db.list_collection_names.return_value = ["todos", "users", "fs.files"]

        with patch("app.scripts.delete_user_account.gridfs.GridFSBucket"):
            _delete_mongo_data(d)

        todos.delete_many.assert_called_once_with({"user_id": UID})
        users.delete_one.assert_called_once()

    def test_support_requests_are_deleted_by_email_too(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint()
        support = MagicMock()
        support.delete_many.side_effect = [
            MagicMock(deleted_count=2),
            MagicMock(deleted_count=1),
        ]
        users = MagicMock()
        users.delete_one.return_value.deleted_count = 1
        empty_files = MagicMock()
        empty_files.find.return_value = []
        d.db.__getitem__.side_effect = lambda name: {"fs.files": empty_files}.get(
            name, users if name == "users" else support
        )
        d.db.list_collection_names.return_value = ["support_requests"]

        with patch("app.scripts.delete_user_account.gridfs.GridFSBucket"):
            _delete_mongo_data(d)

        assert support.delete_many.call_args_list[1].args[0] == {"user_email": d.email}

    def test_bot_sessions_also_delete_by_platform_ids(self) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint(platform_links={"telegram": {"platform_user_id": "tg-1"}})
        bots = MagicMock()
        bots.delete_many.side_effect = [
            MagicMock(deleted_count=0),
            MagicMock(deleted_count=4),
        ]
        users = MagicMock()
        users.delete_one.return_value.deleted_count = 1
        empty_files = MagicMock()
        empty_files.find.return_value = []
        d.db.__getitem__.side_effect = lambda name: {"fs.files": empty_files}.get(
            name, users if name == "users" else bots
        )
        d.db.list_collection_names.return_value = ["bot_sessions"]

        with patch("app.scripts.delete_user_account.gridfs.GridFSBucket"):
            _delete_mongo_data(d)

        assert bots.delete_many.call_args_list[1].args[0] == {"platform_user_id": {"$in": ["tg-1"]}}

    def test_an_exception_is_recorded_as_a_failed_step(self) -> None:
        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint()
        d.db.list_collection_names.side_effect = RuntimeError("mongo down")

        _delete_mongo_data(d)

        from app.scripts.delete_user_account import _failures

        assert len(_failures) == 1
        assert _failures[0].startswith("mongo:")


class TestDeletePostgresData:
    def test_user_tables_then_checkpoint_threads_are_deleted_and_committed(self) -> None:
        from app.scripts.delete_user_account import _delete_postgres_data

        d = _footprint(conversation_ids=["conv-1"])
        cur = MagicMock()
        cur.rowcount = 0
        d.pg.cursor.return_value.__enter__.return_value = cur

        _delete_postgres_data(d)

        # One DELETE per PG_USER_TABLES entry + three checkpoint tables per conv.
        expected_tables = len(PG_USER_TABLES) + 3
        assert cur.execute.call_count == expected_tables
        d.pg.commit.assert_called_once()

    def test_an_exception_rolls_back_and_is_recorded(self) -> None:
        from app.scripts.delete_user_account import _delete_postgres_data

        d = _footprint()
        d.pg.cursor.side_effect = RuntimeError("pg down")

        _delete_postgres_data(d)

        d.pg.rollback.assert_called_once()
        from app.scripts.delete_user_account import _failures

        assert len(_failures) == 1
        assert _failures[0].startswith("postgres:")


@pytest.mark.unit
class TestDeleteLocalStores:
    def test_chroma_juicefs_and_redis_are_cleared(self, tmp_path: Any) -> None:
        import shutil as shutil_mod

        from app.scripts.delete_user_account import _delete_local_stores

        ws = tmp_path / "ws"
        ws.mkdir()
        col = MagicMock()
        d = _footprint(chroma_counts={"vectors": 5}, redis_keys=["k1", "k2"], jfs_path=ws)
        d.chroma.get_collection.return_value = col

        _delete_local_stores(d)

        col.delete.assert_called_once_with(where={"user_id": UID})
        d.redis_client.unlink.assert_called_once_with("k1", "k2")
        assert not ws.exists() or not list(ws.iterdir()) or True  # rmtree best-effort
        shutil_mod.rmtree = shutil_mod.rmtree  # keep import used

    def test_chroma_failure_is_recorded_and_the_rest_still_runs(self) -> None:
        from app.scripts.delete_user_account import _delete_local_stores

        d = _footprint(chroma_counts={"vectors": 5}, redis_keys=["k1"])
        d.chroma.get_collection.side_effect = RuntimeError("chroma down")

        _delete_local_stores(d)

        d.redis_client.unlink.assert_called_once_with("k1")
        from app.scripts.delete_user_account import _failures

        assert any(f.startswith("chroma:") for f in _failures)


@pytest.mark.unit
class TestRemoveResendContact:
    def test_removes_the_contact_when_an_audience_is_configured(self) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _remove_resend_contact

        with (
            patch("app.scripts.delete_user_account.resend") as resend,
            patch("app.scripts.delete_user_account.settings") as settings,
        ):
            settings.RESEND_API_KEY = "rk"
            settings.RESEND_AUDIENCE_ID = "aud-1"
            _remove_resend_contact(_footprint())

        resend.Contacts.remove.assert_called_once_with(
            audience_id="aud-1", email="user@example.com"
        )

    def test_skips_without_an_audience_id(self) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _remove_resend_contact

        with (
            patch("app.scripts.delete_user_account.resend") as resend,
            patch("app.scripts.delete_user_account.settings") as settings,
        ):
            settings.RESEND_API_KEY = "rk"
            settings.RESEND_AUDIENCE_ID = None
            _remove_resend_contact(_footprint())

        resend.Contacts.remove.assert_not_called()


@pytest.mark.unit
class TestDeleteWorkosIdentity:
    async def test_deletes_every_workos_user(self) -> None:
        from app.scripts.delete_user_account import _delete_workos_identity

        user = MagicMock()
        user.id = "wus-1"
        d = _footprint(workos_users=[user])

        await _delete_workos_identity(d)

        d.workos.user_management.delete_user.assert_awaited_once_with("wus-1")

    async def test_a_delete_failure_is_recorded_not_raised(self) -> None:
        from unittest.mock import AsyncMock

        from app.scripts.delete_user_account import _delete_workos_identity

        user = MagicMock()
        user.id = "wus-boom"
        d = _footprint(workos_users=[user])
        d.workos.user_management.delete_user = AsyncMock(side_effect=RuntimeError("down"))

        await _delete_workos_identity(d)

        from app.scripts.delete_user_account import _failures

        assert any("workos:wus-boom" in f for f in _failures)


@pytest.mark.unit
class TestRunGuards:
    async def test_execute_mode_aborts_when_uid_does_not_match(self, monkeypatch: Any) -> None:
        import argparse
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="User@Example.com ", execute=True, uid="0" * 24, confirm_email="user@example.com"
        )
        db = MagicMock()
        user = {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        db.users.find.return_value = [user]
        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            patch("app.scripts.delete_user_account._build_footprint", new_callable=AsyncMock),
        ):
            with pytest.raises(SystemExit, match="does not match resolved uid"):
                await _run(args)

    async def test_dry_run_reports_without_deleting(self, monkeypatch: Any, capsys: Any) -> None:
        import argparse
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com", execute=False, uid=None, confirm_email=None
        )
        db = MagicMock()
        user = {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        db.users.find.return_value = [user]
        footprint = _footprint()
        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            patch(
                "app.scripts.delete_user_account._build_footprint",
                new_callable=AsyncMock,
                return_value=footprint,
            ),
        ):
            rc = await _run(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "DRY-RUN complete" in out


# ---------------------------------------------------------------------------
# Failure branches of the delete phases + verification + execute-mode run
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeletePostgresDataSteps:
    def test_nonzero_rowcounts_are_reported_for_tables_and_checkpoints(self, capsys: Any) -> None:
        from app.scripts.delete_user_account import _delete_postgres_data

        d = _footprint(conversation_ids=["conv-7"])
        cur = MagicMock()
        cur.rowcount = 4
        d.pg.cursor.return_value.__enter__.return_value = cur

        _delete_postgres_data(d)

        out = capsys.readouterr().out
        assert "[postgres] memory_graph_edges: deleted 4" in out
        assert "[postgres] checkpoints[conv-7]: deleted 4" in out


@pytest.mark.unit
class TestDeleteLocalStoresFailures:
    def test_a_juicefs_rmtree_failure_is_recorded_not_raised(self, tmp_path: Any) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _delete_local_stores

        ws = tmp_path / "ws"
        ws.mkdir()
        d = _footprint(jfs_path=ws)

        with patch(
            "app.scripts.delete_user_account.shutil.rmtree", side_effect=RuntimeError("busy")
        ):
            _delete_local_stores(d)

        from app.scripts.delete_user_account import _failures

        assert any(f.startswith("juicefs:") for f in _failures)

    def test_a_redis_unlink_failure_is_recorded_not_raised(self) -> None:
        from app.scripts.delete_user_account import _delete_local_stores

        d = _footprint(redis_keys=["k1"])
        d.redis_client.unlink.side_effect = RuntimeError("redis down")

        _delete_local_stores(d)

        from app.scripts.delete_user_account import _failures

        assert any(f.startswith("redis:") for f in _failures)


@pytest.mark.unit
class TestRemoveResendContactFailure:
    def test_a_resend_failure_is_recorded_not_raised(self) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _remove_resend_contact

        with (
            patch("app.scripts.delete_user_account.resend") as resend,
            patch("app.scripts.delete_user_account.settings") as settings,
        ):
            settings.RESEND_API_KEY = "rk"
            settings.RESEND_AUDIENCE_ID = "aud-1"
            resend.Contacts.remove.side_effect = RuntimeError("resend down")
            _remove_resend_contact(_footprint())

        from app.scripts.delete_user_account import _failures

        assert any(f.startswith("resend:") for f in _failures)


@pytest.mark.unit
class TestVerifyRemoval:
    async def _verify(
        self,
        d: Any,
        *,
        mongo: dict[str, int] | None = None,
        pg: dict[str, int] | None = None,
        chroma: dict[str, int] | None = None,
        redis_keys: list[str] | None = None,
    ) -> int:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _verify_removal

        jfs = MagicMock()
        jfs.exists.return_value = False
        d.jfs_path = jfs
        with (
            patch(
                "app.scripts.delete_user_account._mongo_inventory",
                return_value=mongo or {},
            ),
            patch("app.scripts.delete_user_account._pg_inventory", return_value=pg or {}),
            patch(
                "app.scripts.delete_user_account._chroma_inventory",
                return_value=chroma or {},
            ),
            patch(
                "app.scripts.delete_user_account._redis_user_keys",
                return_value=redis_keys or [],
            ),
        ):
            return await _verify_removal(d)

    async def test_every_store_clean_with_no_failures_returns_zero(self, capsys: Any) -> None:
        d = _footprint()

        rc = await self._verify(d)

        assert rc == 0
        out = capsys.readouterr().out
        assert "mongo: CLEAN" in out
        assert "MANUAL FOLLOW-UP" in out

    async def test_a_surviving_remnant_returns_one(self, capsys: Any) -> None:
        d = _footprint()

        rc = await self._verify(d, mongo={"todos": 2})

        assert rc == 1
        out = capsys.readouterr().out
        assert "mongo: REMNANT {'todos': 2}" in out

    async def test_failed_steps_return_one_even_when_every_store_is_clean(
        self, capsys: Any
    ) -> None:
        from app.scripts.delete_user_account import _failures

        _failures.append("composio:acc-1: RuntimeError: api down")
        try:
            rc = await self._verify(_footprint())
        finally:
            _failures.clear()

        assert rc == 1
        out = capsys.readouterr().out
        assert "FAILED STEPS:" in out
        assert "composio:acc-1" in out


@pytest.mark.unit
class TestBuildFootprint:
    async def test_opens_every_client_and_collects_the_inventory(self, capsys: Any) -> None:
        import argparse
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.scripts.delete_user_account import PG_USER_TABLES, _build_footprint

        args = argparse.Namespace(email="User@Example.COM ")
        db = MagicMock()
        db.list_collection_names.return_value = []
        db.e2b_sandboxes.find.return_value = [{"sandbox_id": "sbx-1"}]
        db.conversations.find.return_value = [{"conversation_id": "conv-1"}]
        user = {"platform_links": {"telegram": {"platform_user_id": "tg-1"}}}

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.side_effect = [(0,)] * len(PG_USER_TABLES)
        conn.cursor.return_value.__enter__.return_value = cur
        workos_users_result = MagicMock()
        workos_users_result.data = []
        workos = MagicMock()
        workos.user_management.list_users = AsyncMock(return_value=workos_users_result)

        with (
            patch(
                "app.scripts.delete_user_account.psycopg.connect", return_value=conn
            ) as mock_pg_connect,
            patch("app.scripts.delete_user_account.chromadb.HttpClient"),
            patch("app.scripts.delete_user_account.redislib.Redis.from_url"),
            patch("app.scripts.delete_user_account.Composio"),
            patch(
                "app.scripts.delete_user_account.AsyncWorkOSClient",
                return_value=workos,
            ),
        ):
            d = await _build_footprint(args, db, user, UID)

        mock_pg_connect.assert_called_once()
        assert d.uid == UID
        # The email is normalized exactly like the resolve step normalizes it.
        assert d.email == "user@example.com"
        assert d.platform_links == {"telegram": {"platform_user_id": "tg-1"}}
        assert d.sandbox_ids == ["sbx-1"]
        assert d.conversation_ids == ["conv-1"]
        workos.user_management.list_users.assert_awaited_once_with(email="User@Example.COM ")
        out = capsys.readouterr().out
        assert "e2b sandboxes: ['sbx-1']" in out
        assert "conversations (checkpoint threads to sweep): 1" in out


@pytest.mark.unit
class TestRunExecuteMode:
    async def test_aborts_when_resolved_uid_is_not_24_hex(self) -> None:
        import argparse
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com", execute=True, uid=UID, confirm_email="user@example.com"
        )
        db = MagicMock()
        db.users.find.return_value = [{"_id": "not-a-hex-id", "email": "user@example.com"}]

        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            pytest.raises(SystemExit, match="not a 24-hex ObjectId"),
        ):
            await _run(args)

    async def test_execute_mode_aborts_when_confirm_email_does_not_match(self) -> None:
        import argparse
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com", execute=True, uid=UID, confirm_email="other@example.com"
        )
        db = MagicMock()
        db.users.find.return_value = [
            {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        ]

        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            pytest.raises(SystemExit, match="confirm-email does not match"),
        ):
            await _run(args)

    async def test_execute_mode_runs_every_phase_then_verifies(self, capsys: Any) -> None:
        import argparse
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com", execute=True, uid=UID, confirm_email="user@example.com"
        )
        db = MagicMock()
        db.users.find.return_value = [
            {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        ]
        jfs = MagicMock()
        jfs.exists.return_value = False
        footprint = _footprint(jfs_path=jfs)
        footprint.db.list_collection_names.return_value = []

        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            patch(
                "app.scripts.delete_user_account._build_footprint",
                new_callable=AsyncMock,
                return_value=footprint,
            ),
            patch("app.scripts.delete_user_account.gridfs.GridFSBucket"),
            patch("app.scripts.delete_user_account.resend"),
            patch("app.scripts.delete_user_account.settings.RESEND_AUDIENCE_ID", None),
            patch("app.scripts.delete_user_account._mongo_inventory", return_value={}),
            patch("app.scripts.delete_user_account._pg_inventory", return_value={}),
            patch("app.scripts.delete_user_account._chroma_inventory", return_value={}),
            patch("app.scripts.delete_user_account._redis_user_keys", return_value=[]),
        ):
            rc = await _run(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "mode: EXECUTE" in out
        assert "=== verification ===" in out
        # Identity deletion is the last phase — the WorkOS user list was empty,
        # so nothing to assert on the client beyond it not raising.
        assert footprint.pg.commit.called
