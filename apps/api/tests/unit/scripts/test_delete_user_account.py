"""Inventory helpers for the operational account-deletion script.

The script is the GDPR/erasure path, so its inventory is what tells an operator
whether anything of the user's survived. A collection silently skipped here reads
as "nothing left to delete" — the one failure this file exists to catch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call

from bson import ObjectId
import pytest

from app.db.mongodb.mongodb import object_id_filter
from app.scripts.delete_user_account import (
    JFS_USERS_ROOT,
    PG_USER_TABLES,
    _chroma_inventory,
    _mongo_inventory,
    _pg_inventory,
)

UID = "67689b80006f6eec3f6f6df8"
# Deliberately unnormalized: the footprint must lowercase and strip it.
RAW_EMAIL = "User@Example.COM "


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

        expected = [
            f"SELECT count(*) FROM {table} WHERE user_id = %s"  # noqa: S608 -- expected literal mirrors the hardcoded PG_USER_TABLES query, no user input
            for table in PG_USER_TABLES
        ]
        assert [c.args[0] for c in cursor.execute.call_args_list] == expected
        for c in cursor.execute.call_args_list:
            assert c.args[1] == (UID,)


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

        from app.config.settings import settings
        from app.scripts.delete_user_account import _revoke_external_access

        account = MagicMock()
        account.id = "acc-1"
        account.toolkit.slug = "gmail"
        d = _footprint(composio_accounts=[account], sandbox_ids=["sbx-1"])

        with patch("app.scripts.delete_user_account.AsyncSandbox") as sandbox:
            sandbox.kill = AsyncMock()
            await _revoke_external_access(d)

        d.composio.connected_accounts.delete.assert_called_once_with(nanoid="acc-1")
        sandbox.kill.assert_awaited_once_with(
            "sbx-1", api_key=settings.E2B_API_KEY, domain=settings.E2B_DOMAIN
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
    def test_gridfs_collections_and_users_doc_are_all_deleted(self, capsys: Any) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint()
        files_col = MagicMock()
        files_col.find.return_value = [{"_id": "file-1"}]
        todos = MagicMock()
        todos.delete_many.return_value.deleted_count = 3
        users = MagicMock()
        users.delete_one.return_value.deleted_count = 1
        chunks = MagicMock()
        cols = {"fs.files": files_col, "fs.chunks": chunks, "todos": todos}
        d.db.__getitem__.side_effect = cols.__getitem__
        d.db.users = users
        d.db.list_collection_names.return_value = ["todos", "users", "fs.files", "fs.chunks"]

        with patch("app.scripts.delete_user_account.gridfs.GridFSBucket") as bucket_cls:
            _delete_mongo_data(d)

        # GridFS files are deleted through the bucket, one per fs.files doc.
        bucket_cls.assert_called_once_with(d.db)
        bucket_cls.return_value.delete.assert_called_once_with("file-1")
        files_col.find.assert_called_once_with({"metadata.user_id": UID}, {"_id": 1})
        # The plain-collection loop skips every fs.* collection...
        files_col.delete_many.assert_not_called()
        chunks.delete_many.assert_not_called()
        todos.delete_many.assert_called_once_with({"user_id": UID})
        # ...and the users doc is removed by its ObjectId, last.
        users.delete_one.assert_called_once_with(object_id_filter(UID))
        assert "[mongo] todos: deleted 3" in capsys.readouterr().out

    def test_support_requests_are_deleted_by_email_too(self, capsys: Any) -> None:
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

        first, second = support.delete_many.call_args_list
        assert first.args[0] == {"user_id": UID}
        assert second.args[0] == {"user_email": d.email}
        # Both counts fold into one reported step.
        assert "[mongo] support_requests: deleted 3" in capsys.readouterr().out

    def test_bot_sessions_also_delete_by_platform_ids(self, capsys: Any) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint(
            platform_links={
                "telegram": {"platform_user_id": "tg-1"},
                "whatsapp": "wa-raw",
                "slack": {"other": "x"},
            }
        )
        bots = MagicMock()
        # Non-zero on BOTH sides so += is observable against = and -=.
        bots.delete_many.side_effect = [
            MagicMock(deleted_count=2),
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

        second = bots.delete_many.call_args_list[1]
        # dict links contribute their platform_user_id; a raw link contributes itself.
        assert second.args[0] == {
            "platform_user_id": {"$in": ["tg-1", "wa-raw", str({"other": "x"})]}
        }
        assert "[mongo] bot_sessions: deleted 6" in capsys.readouterr().out

    def test_bot_sessions_without_platform_links_only_delete_by_user_id(self, capsys: Any) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint(platform_links={})
        bots = MagicMock()
        bots.delete_many.side_effect = [MagicMock(deleted_count=0), MagicMock(deleted_count=7)]
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

        # No platform links -> only the user_id-scoped delete, never an $in sweep.
        assert bots.delete_many.call_args_list == [call({"user_id": UID})]

    def test_zero_count_deletions_are_not_reported_as_steps(self, capsys: Any) -> None:
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _delete_mongo_data

        d = _footprint()
        notes = MagicMock()
        notes.delete_many.return_value.deleted_count = 0
        users = MagicMock()
        users.delete_one.return_value.deleted_count = 1
        empty_files = MagicMock()
        empty_files.find.return_value = []
        d.db.__getitem__.side_effect = lambda name: {"fs.files": empty_files}.get(
            name, users if name == "users" else notes
        )
        d.db.list_collection_names.return_value = ["notes"]

        with patch("app.scripts.delete_user_account.gridfs.GridFSBucket"):
            _delete_mongo_data(d)

        notes.delete_many.assert_called_once_with({"user_id": UID})
        out = capsys.readouterr().out
        assert "[mongo] notes" not in out

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

        calls = cur.execute.call_args_list
        # One DELETE per PG_USER_TABLES entry, each scoped to the uid...
        for i, table in enumerate(PG_USER_TABLES):
            assert calls[i].args == (
                f"DELETE FROM {table} WHERE user_id = %s",  # noqa: S608 -- expected literal mirrors the hardcoded PG_USER_TABLES query, no user input
                (d.uid,),
            )
        # ...then the three checkpoint tables swept by a LIKE pattern that
        # matches derived threads embedding the conversation id.
        checkpoint_calls = calls[len(PG_USER_TABLES) :]
        assert [c.args[0].split("FROM ")[1].split(" ")[0] for c in checkpoint_calls] == [
            "checkpoint_writes",
            "checkpoint_blobs",
            "checkpoints",
        ]
        for c in checkpoint_calls:
            table = c.args[0].split("FROM ")[1].split(" ")[0]
            assert (
                c.args[0] == f"DELETE FROM {table} WHERE thread_id LIKE %s ESCAPE '\\'"  # noqa: S608 -- table comes from the asserted call itself, one of three literal checkpoint names
            )
            assert c.args[1] == ("%conv-1%",)
        d.pg.commit.assert_called_once()

    def test_the_like_pattern_escapes_wildcards_in_conversation_ids(self) -> None:
        from app.scripts.delete_user_account import _delete_postgres_data

        d = _footprint(conversation_ids=["a%b_c\\d"])
        cur = MagicMock()
        cur.rowcount = 0
        d.pg.cursor.return_value.__enter__.return_value = cur

        _delete_postgres_data(d)

        patterns = {c.args[1][0] for c in cur.execute.call_args_list[len(PG_USER_TABLES) :]}
        # % _ and \\ are backslash-escaped so the id only ever matches itself.
        assert patterns == {"%a\\%b\\_c\\\\d%"}

    def test_an_exception_rolls_back_and_is_recorded(self) -> None:
        from app.scripts.delete_user_account import _delete_postgres_data

        d = _footprint()
        d.pg.cursor.side_effect = RuntimeError("pg down")

        _delete_postgres_data(d)

        d.pg.rollback.assert_called_once()
        d.pg.commit.assert_not_called()
        from app.scripts.delete_user_account import _failures

        assert len(_failures) == 1
        assert _failures[0].startswith("postgres:")


@pytest.mark.unit
class TestDeleteLocalStores:
    def test_chroma_juicefs_and_redis_are_cleared(self, tmp_path: Any, capsys: Any) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _delete_local_stores

        ws = tmp_path / "ws"
        ws.mkdir()
        vectors = MagicMock()
        d = _footprint(chroma_counts={"vectors": 5}, redis_keys=["k1", "k2"], jfs_path=ws)
        d.chroma.get_collection.side_effect = lambda name: {"vectors": vectors}[name]

        with patch("app.scripts.delete_user_account.shutil.rmtree") as rmtree:
            _delete_local_stores(d)

        out = capsys.readouterr().out
        assert "[chroma] vectors: deleted 5" in out
        assert f"[juicefs] removed {ws}" in out
        assert "[redis] unlinked 2 keys" in out
        # The delete targets the collection the inventory counted, by name.
        assert d.chroma.get_collection.call_args_list == [call("vectors")]
        vectors.delete.assert_called_once_with(where={"user_id": UID})
        rmtree.assert_called_once_with(ws)
        d.redis_client.unlink.assert_called_once_with("k1", "k2")

    def test_chroma_failure_is_recorded_and_the_rest_still_runs(self) -> None:
        from app.scripts.delete_user_account import _delete_local_stores

        d = _footprint(chroma_counts={"vectors": 5}, redis_keys=["k1"])
        d.chroma.get_collection.side_effect = RuntimeError("chroma down")

        _delete_local_stores(d)

        d.redis_client.unlink.assert_called_once_with("k1")
        from app.scripts.delete_user_account import _failures

        assert any(f.startswith("chroma:") for f in _failures)

    def test_a_missing_juicefs_path_is_not_rmtree_d(self) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _delete_local_stores

        jfs = MagicMock()
        jfs.exists.return_value = False
        d = _footprint(jfs_path=jfs)

        with patch("app.scripts.delete_user_account.shutil.rmtree") as rmtree:
            _delete_local_stores(d)

        rmtree.assert_not_called()
        from app.scripts.delete_user_account import _failures

        assert not _failures

    def test_redis_unlink_is_skipped_without_keys_but_still_reported(self, capsys: Any) -> None:
        from app.scripts.delete_user_account import _delete_local_stores

        d = _footprint(redis_keys=[])

        _delete_local_stores(d)

        d.redis_client.unlink.assert_not_called()
        assert "[redis] unlinked 0 keys" in capsys.readouterr().out


@pytest.mark.unit
class TestRemoveResendContact:
    def test_removes_the_contact_when_an_audience_is_configured(self, capsys: Any) -> None:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _remove_resend_contact

        with (
            patch("app.scripts.delete_user_account.resend") as resend,
            patch("app.scripts.delete_user_account.settings") as settings,
        ):
            settings.RESEND_API_KEY = "rk"
            settings.RESEND_AUDIENCE_ID = "aud-1"
            _remove_resend_contact(_footprint())

        assert resend.api_key == "rk"
        resend.Contacts.remove.assert_called_once_with(
            audience_id="aud-1", email="user@example.com"
        )
        assert "[resend] removed contact user@example.com" in capsys.readouterr().out

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
        from contextlib import ExitStack
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.config.settings import settings
        from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com", execute=False, uid=None, confirm_email=None
        )
        db = MagicMock()
        user = {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        db.users.find.return_value = [user]
        footprint = _footprint()
        phase_names = [
            "_revoke_external_access",
            "_delete_mongo_data",
            "_delete_postgres_data",
            "_delete_local_stores",
            "_remove_resend_contact",
            "_delete_workos_identity",
            "_verify_removal",
        ]
        phase_mocks = {name: MagicMock() for name in phase_names}
        phase_patches = [
            patch(f"app.scripts.delete_user_account.{name}", new=phase_mocks[name])
            for name in phase_names
        ]
        fake_client = MagicMock()
        fake_client.__getitem__.return_value = db
        with ExitStack() as stack:
            mongo_client = stack.enter_context(
                patch("app.scripts.delete_user_account.MongoClient", return_value=fake_client)
            )
            stack.enter_context(
                patch(
                    "app.scripts.delete_user_account._build_footprint",
                    new_callable=AsyncMock,
                    return_value=footprint,
                )
            )
            for ph in phase_patches:
                stack.enter_context(ph)
            rc = await _run(args)

        mongo_client.assert_called_once_with(settings.MONGO_DB)
        fake_client.__getitem__.assert_called_once_with(MONGO_DATABASE_NAME)
        # The resolve step sees the normalized email.
        db.users.find.assert_called_once_with(
            {"email": {"$regex": "^user@example\\.com$", "$options": "i"}}
        )
        for mock in phase_mocks.values():
            mock.assert_not_called()
        assert rc == 0
        out = capsys.readouterr().out
        assert f"user: user@example.com  uid={UID}  name=U" in out
        assert "mode: DRY-RUN" in out
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
        jfs_exists: bool = False,
    ) -> int:
        from unittest.mock import patch

        from app.scripts.delete_user_account import _verify_removal

        jfs = MagicMock()
        jfs.exists.return_value = jfs_exists
        d.jfs_path = jfs
        with (
            patch(
                "app.scripts.delete_user_account._mongo_inventory",
                return_value=mongo or {},
            ) as mongo_inv,
            patch("app.scripts.delete_user_account._pg_inventory", return_value=pg or {}) as pg_inv,
            patch(
                "app.scripts.delete_user_account._chroma_inventory",
                return_value=chroma or {},
            ) as chroma_inv,
            patch(
                "app.scripts.delete_user_account._redis_user_keys",
                return_value=redis_keys or [],
            ) as redis_inv,
        ):
            rc = await _verify_removal(d)

        # The sweep re-inventories the SAME stores the footprint opened, scoped
        # to this user and email — a drifted argument would verify someone else.
        mongo_inv.assert_called_once_with(d.db, d.uid, d.email)
        pg_inv.assert_called_once_with(d.pg, d.uid)
        chroma_inv.assert_called_once_with(d.chroma, d.uid)
        redis_inv.assert_called_once_with(d.redis_client, d.uid)
        return rc

    async def test_every_store_clean_with_no_failures_returns_zero(self, capsys: Any) -> None:
        d = _footprint()

        rc = await self._verify(d)

        assert rc == 0
        out = capsys.readouterr().out
        assert "mongo: CLEAN" in out
        assert "postgres: CLEAN" in out
        assert "chroma: CLEAN" in out
        assert "redis: CLEAN" in out
        assert "juicefs: CLEAN" in out
        assert "composio: CLEAN" in out
        assert "workos: CLEAN" in out
        # The operator is told, with the uid, what the server cannot delete.
        assert f"MANUAL FOLLOW-UP: delete the PostHog person for distinct_id {UID}" in out
        assert f"MANUAL FOLLOW-UP: delete Langfuse traces for user_id {UID}" in out

    async def test_a_surviving_remnant_returns_one(self, capsys: Any) -> None:
        d = _footprint()

        rc = await self._verify(d, mongo={"todos": 2})

        assert rc == 1
        out = capsys.readouterr().out
        assert "mongo: REMNANT {'todos': 2}" in out

    async def test_each_store_remnant_is_reported_verbatim(self, capsys: Any) -> None:
        d = _footprint()

        rc = await self._verify(
            d,
            pg={"memories": 1},
            chroma={"vectors": 9},
            redis_keys=["rkey"],
            jfs_exists=True,
        )

        assert rc == 1
        out = capsys.readouterr().out
        assert "postgres: REMNANT {'memories': 1}" in out
        assert "chroma: REMNANT {'vectors': 9}" in out
        assert "redis: REMNANT ['rkey']" in out
        assert "juicefs: REMNANT True" in out

    async def test_composio_remnant_counts_only_active_accounts(self, capsys: Any) -> None:
        from unittest.mock import MagicMock

        active = MagicMock()
        active.id = "acc-active"
        active.status = "ACTIVE"
        inactive = MagicMock()
        inactive.id = "acc-revoked"
        inactive.status = "REVOKED"
        d = _footprint()
        listing = MagicMock()
        listing.items = [active, inactive]
        d.composio.connected_accounts.list.return_value = listing

        rc = await self._verify(d)

        d.composio.connected_accounts.list.assert_called_once_with(user_ids=[UID])
        assert rc == 1
        out = capsys.readouterr().out
        assert "composio: REMNANT ['acc-active']" in out
        assert "acc-revoked" not in out

    async def test_a_composio_listing_without_items_reads_as_clean(self, capsys: Any) -> None:
        from unittest.mock import Mock

        d = _footprint()
        # Some backends omit `items` entirely; the sweep must treat that as
        # "no accounts left", not crash the verification pass.
        d.composio.connected_accounts.list = Mock(return_value=object())

        rc = await self._verify(d)

        assert rc == 0
        assert "composio: CLEAN" in capsys.readouterr().out

    async def test_workos_remnant_lists_by_email_and_reports_ids(self, capsys: Any) -> None:
        from unittest.mock import AsyncMock, MagicMock

        survivor = MagicMock()
        survivor.id = "wus-1"
        d = _footprint()
        d.workos.user_management.list_users = AsyncMock(return_value=MagicMock(data=[survivor]))

        rc = await self._verify(d)

        d.workos.user_management.list_users.assert_awaited_once_with(email=d.email)
        assert rc == 1
        assert "workos: REMNANT ['wus-1']" in capsys.readouterr().out

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


async def _run_build_footprint(
    db: Any,
    user: Any,
    *,
    uid: str = UID,
    composio_items: list[Any] | None = None,
    workos_users: list[Any] | None = None,
    pg_counts: dict[str, int] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Call _build_footprint under the standard client patches.

    Returns the footprint plus every mock the tests need to inspect.
    """
    import argparse
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.scripts.delete_user_account import PG_USER_TABLES, _build_footprint

    args = argparse.Namespace(email=RAW_EMAIL)
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.side_effect = [(0,)] * len(PG_USER_TABLES)
    conn.cursor.return_value.__enter__.return_value = cur

    composio = MagicMock()
    listing = MagicMock()
    listing.items = composio_items or []
    composio.connected_accounts.list.return_value = listing

    workos = MagicMock()
    workos_result = MagicMock()
    workos_result.data = workos_users or []
    workos.user_management.list_users = AsyncMock(return_value=workos_result)

    redis_client = MagicMock()

    with (
        patch(
            "app.scripts.delete_user_account.psycopg.connect", return_value=conn
        ) as mock_pg_connect,
        patch("app.scripts.delete_user_account.chromadb.HttpClient") as mock_chroma_cls,
        patch(
            "app.scripts.delete_user_account.redislib.Redis.from_url",
            return_value=redis_client,
        ) as mock_redis_from_url,
        patch("app.scripts.delete_user_account.Composio", return_value=composio) as mock_composio,
        patch(
            "app.scripts.delete_user_account.AsyncWorkOSClient", return_value=workos
        ) as mock_workos_cls,
        patch(
            "app.scripts.delete_user_account._mongo_inventory",
            return_value={"todos": 5},
        ) as mock_mongo_inv,
        patch(
            "app.scripts.delete_user_account._pg_inventory",
            return_value={"memories": 1} if pg_counts is None else pg_counts,
        ) as mock_pg_inv,
        patch(
            "app.scripts.delete_user_account._chroma_inventory",
            return_value={"vectors": 9},
        ) as mock_chroma_inv,
        patch(
            "app.scripts.delete_user_account._redis_user_keys",
            return_value=["cache:k1"],
        ) as mock_redis_inv,
    ):
        d = await _build_footprint(args, db, user, uid)

    mocks: dict[str, Any] = {
        "pg_connect": mock_pg_connect,
        "chroma_cls": mock_chroma_cls,
        "redis_from_url": mock_redis_from_url,
        "composio_cls": mock_composio,
        "workos_cls": mock_workos_cls,
        "composio": composio,
        "workos": workos,
        "conn": conn,
        "redis_client": redis_client,
        "mongo_inv": mock_mongo_inv,
        "pg_inv": mock_pg_inv,
        "chroma_inv": mock_chroma_inv,
        "redis_inv": mock_redis_inv,
    }
    return d, mocks


@pytest.mark.unit
class TestBuildFootprint:
    async def test_opens_every_client_with_the_configured_settings(self) -> None:
        from unittest.mock import MagicMock

        from app.config.settings import settings

        d, mocks = await _run_build_footprint(MagicMock(), {})

        mocks["pg_connect"].assert_called_once_with(settings.POSTGRES_URL)
        mocks["chroma_cls"].assert_called_once_with(
            host=settings.CHROMADB_HOST, port=settings.CHROMADB_PORT
        )
        mocks["redis_from_url"].assert_called_once_with(settings.REDIS_URL)
        mocks["composio_cls"].assert_called_once_with(api_key=settings.COMPOSIO_KEY)
        mocks["workos_cls"].assert_called_once_with(
            api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
        )

    async def test_collects_the_full_inventory_into_the_footprint(self, capsys: Any) -> None:
        account = MagicMock()
        account.id = "acc-1"
        workos_user = MagicMock()
        workos_user.id = "wus-1"

        db = MagicMock()
        db.e2b_sandboxes.find.return_value = [{"sandbox_id": "sbx-1"}]
        db.conversations.find.return_value = [{"conversation_id": "conv-1"}]
        user = {"platform_links": {"telegram": {"platform_user_id": "tg-1"}}}

        d, mocks = await _run_build_footprint(
            db, user, composio_items=[account], workos_users=[workos_user]
        )

        # The footprint carries the exact client objects that were opened...
        assert d.db is db
        assert d.pg is mocks["conn"]
        assert d.chroma is mocks["chroma_cls"].return_value
        assert d.redis_client is mocks["redis_client"]
        assert d.composio is mocks["composio"]
        assert d.workos is mocks["workos"]
        assert d.uid == UID
        # ...the inventory, scoped to this user and the normalized email...
        mocks["mongo_inv"].assert_called_once_with(db, UID, "user@example.com")
        mocks["pg_inv"].assert_called_once_with(mocks["conn"], UID)
        mocks["chroma_inv"].assert_called_once_with(mocks["chroma_cls"].return_value, UID)
        mocks["redis_inv"].assert_called_once_with(mocks["redis_client"], UID)
        assert d.chroma_counts == {"vectors": 9}
        assert d.redis_keys == ["cache:k1"]
        # ...and every field the teardown and verification phases need.
        # The email is normalized exactly like the resolve step normalizes it.
        assert d.email == "user@example.com"
        assert d.platform_links == {"telegram": {"platform_user_id": "tg-1"}}
        assert d.sandbox_ids == ["sbx-1"]
        assert d.conversation_ids == ["conv-1"]
        assert d.composio_accounts == [account]
        assert d.workos_users == [workos_user]
        assert d.jfs_path == JFS_USERS_ROOT / UID
        db.e2b_sandboxes.find.assert_called_once_with({"user_id": UID}, {"sandbox_id": 1})
        db.conversations.find.assert_called_once_with({"user_id": UID}, {"conversation_id": 1})
        mocks["composio"].connected_accounts.list.assert_called_once_with(user_ids=[UID])
        mocks["workos"].user_management.list_users.assert_awaited_once_with(email=RAW_EMAIL)
        out = capsys.readouterr().out
        assert "mongo: {'todos': 5}" in out
        assert "postgres: {'memories': 1}" in out
        assert "chroma: {'vectors': 9}" in out
        assert "redis: 1 keys" in out
        assert "e2b sandboxes: ['sbx-1']" in out
        assert "conversations (checkpoint threads to sweep): 1" in out
        assert "platform_links: ['telegram']" in out

    async def test_an_empty_postgres_inventory_prints_none_not_an_empty_dict(
        self, capsys: Any
    ) -> None:
        """The footprint is read by a human before they approve a deletion —
        `postgres: {}` reads as a bug, `postgres: none` reads as "nothing there"."""
        await _run_build_footprint(MagicMock(), {}, pg_counts={})

        assert "postgres: none" in capsys.readouterr().out.splitlines()

    @pytest.mark.parametrize("user", [{}, {"platform_links": None}, {"other": 1}])
    async def test_platform_links_fall_back_to_an_empty_dict(self, user: Any) -> None:
        from unittest.mock import MagicMock

        d, _ = await _run_build_footprint(MagicMock(), user)

        assert d.platform_links == {}

    async def test_aborts_when_the_jfs_path_escapes_the_users_root(self) -> None:
        from unittest.mock import MagicMock

        with pytest.raises(SystemExit, match="refusing to touch"):
            await _run_build_footprint(MagicMock(), {}, uid="../escape")


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
            pytest.raises(SystemExit, match=r"^ABORT: --confirm-email does not match email$"),
        ):
            await _run(args)

    async def test_execute_mode_aborts_when_confirm_email_is_missing(self) -> None:
        """A missing --confirm-email must abort even when the fallback string
        would coincidentally compare equal to the email."""
        import argparse
        from unittest.mock import MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(email="xxxx", execute=True, uid=UID, confirm_email=None)
        db = MagicMock()
        db.users.find.return_value = [{"_id": ObjectId(UID), "email": "xxxx", "name": "U"}]

        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            pytest.raises(SystemExit, match=r"^ABORT: --confirm-email does not match email$"),
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

    async def test_execute_mode_runs_phases_in_order_and_returns_the_verdict(
        self, capsys: Any
    ) -> None:
        import argparse
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.scripts.delete_user_account import _run

        args = argparse.Namespace(
            email="user@example.com",
            execute=True,
            uid=UID,
            confirm_email="  USER@Example.COM ",
        )
        db = MagicMock()
        db.users.find.return_value = [
            {"_id": ObjectId(UID), "email": "user@example.com", "name": "U"}
        ]
        jfs = MagicMock()
        jfs.exists.return_value = False
        footprint = _footprint(jfs_path=jfs)

        order: list[tuple[str, Any]] = []

        async def revoke(d: Any) -> None:
            order.append(("revoke", d))

        def mongo_phase(d: Any) -> None:
            order.append(("mongo", d))

        def postgres_phase(d: Any) -> None:
            order.append(("postgres", d))

        def local_phase(d: Any) -> None:
            order.append(("local", d))

        def resend_phase(d: Any) -> None:
            order.append(("resend", d))

        async def workos_phase(d: Any) -> None:
            order.append(("workos", d))

        async def verify(d: Any) -> int:
            order.append(("verify", d))
            return 7

        with (
            patch("app.scripts.delete_user_account.MongoClient", return_value={"GAIA": db}),
            patch(
                "app.scripts.delete_user_account._build_footprint",
                new_callable=AsyncMock,
                return_value=footprint,
            ) as build_footprint,
            patch("app.scripts.delete_user_account._revoke_external_access", revoke),
            patch("app.scripts.delete_user_account._delete_mongo_data", mongo_phase),
            patch("app.scripts.delete_user_account._delete_postgres_data", postgres_phase),
            patch("app.scripts.delete_user_account._delete_local_stores", local_phase),
            patch("app.scripts.delete_user_account._remove_resend_contact", resend_phase),
            patch("app.scripts.delete_user_account._delete_workos_identity", workos_phase),
            patch("app.scripts.delete_user_account._verify_removal", verify),
        ):
            rc = await _run(args)

        assert rc == 7
        # Every phase operates on the SAME footprint, built from this run's
        # args, db handle, resolved user and uid.
        build_footprint.assert_awaited_once_with(args, db, db.users.find.return_value[0], UID)
        assert [name for name, _ in order] == [
            "revoke",
            "mongo",
            "postgres",
            "local",
            "resend",
            "workos",
            "verify",
        ]
        assert all(d is footprint for _, d in order)
        out = capsys.readouterr().out
        # The exact line, not a substring: the banner is what tells the operator
        # the destructive phase has begun, so its text is the assertion.
        assert "=== deleting ===" in out.splitlines()
        assert "mode: EXECUTE" in out
        assert f"user: user@example.com  uid={UID}  name=U" in out
