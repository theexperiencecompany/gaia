"""Brutal unit tests for event-driven workspace materialization.

Covers the pieces that moved per-user workspace work off the chat turn:
- workspace_sync.sync_stale_user_workspaces (the startup/CLI bulk sync)
- workspace_sync.init_system_subtree / resync_stale_user_workspaces
- integrations_fs.sync_user_integrations (connect/disconnect VFS sync)
- user_integrations.get_connected_integration_ids (the shared filter)
- the connect-path wiring in update_user_integration_status
- the registration-path wiring in oauth_service.store_user_info

The JuiceFS + Mongo boundaries are mocked; these test decision logic to its
limits (no mount, empty sets, stale vs current markers, force, partial
failure, new-vs-existing user), not the filesystem.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user_models import UserDocument
from app.services.integrations import user_integrations
from app.services.integrations.user_integration_status import update_user_integration_status
from app.services.integrations.user_integrations import (
    get_connected_integration_ids,
    get_user_integration_records,
)
from app.services.integrations_fs import sync_user_integrations
from app.services.oauth.oauth_service import store_user_info
from app.services.storage import juicefs
from app.services.workspace_sync import (
    init_system_subtree,
    resync_stale_user_workspaces,
    sync_stale_user_workspaces,
)

WS = "app.services.workspace_sync"
IFS = "app.services.integrations_fs"
UINT = "app.services.integrations.user_integrations"
USTATUS = "app.services.integrations.user_integration_status"
OAUTH = "app.services.oauth.oauth_service"
JFS = "app.services.storage.juicefs"


# _is_mounted must require a REAL mountpoint, not just an existing dir — a
# never-converged mount over a pre-created /mnt/jfs would silently route
# writes to local disk.


def test_is_mounted_rejects_plain_existing_dir(tmp_path):
    # tmp_path exists and is a directory, but is NOT a mountpoint.
    with patch.object(juicefs, "_mount_root", return_value=tmp_path):
        assert juicefs._is_mounted() is False


def test_is_mounted_false_for_missing_path():
    with patch.object(juicefs, "_mount_root", return_value=Path("/no/such/mount/xyz123")):
        assert juicefs._is_mounted() is False


# ---------------------------------------------------------------------------
# workspace_sync.sync_stale_user_workspaces
# ---------------------------------------------------------------------------


@pytest.fixture
def wsync():
    """Patch every external dependency of sync_stale_user_workspaces."""
    with (
        patch(f"{WS}._is_mounted", return_value=True) as is_mounted,
        patch(f"{WS}.library_hash", return_value="HASH_CURRENT"),
        patch(f"{WS}.user_root", side_effect=lambda uid: Path(f"/fake/{uid}")),
        patch(f"{WS}.read_skills_marker") as read_marker,
        patch(f"{WS}.provision_user_workspace", new_callable=AsyncMock) as provision,
        patch(
            f"{WS}.get_connected_integration_ids",
            new_callable=AsyncMock,
            return_value={"gmail"},
        ) as connected,
        patch(f"{WS}._active_user_ids", new_callable=AsyncMock) as active_ids,
        patch(f"{WS}._all_user_ids", new_callable=AsyncMock) as all_ids,
    ):
        yield SimpleNamespace(
            is_mounted=is_mounted,
            read_marker=read_marker,
            provision=provision,
            connected=connected,
            active_ids=active_ids,
            all_ids=all_ids,
        )


async def _run_sync(**kwargs):
    return await sync_stale_user_workspaces(**kwargs)


async def test_no_mount_short_circuits(wsync):
    wsync.is_mounted.return_value = False
    result = await _run_sync()
    assert result == {"scanned": 0, "synced": 0, "skipped": 0}
    wsync.active_ids.assert_not_called()
    wsync.provision.assert_not_called()


async def test_all_stale_provisioned(wsync):
    wsync.active_ids.return_value = ["u1", "u2"]
    wsync.read_marker.side_effect = ["OLD", "OLD"]
    result = await _run_sync()
    assert result == {"scanned": 2, "synced": 2, "skipped": 0}
    assert wsync.provision.await_count == 2


async def test_current_marker_skipped(wsync):
    wsync.active_ids.return_value = ["u1", "u2"]
    wsync.read_marker.side_effect = ["HASH_CURRENT", "HASH_CURRENT"]
    result = await _run_sync()
    assert result == {"scanned": 2, "synced": 0, "skipped": 2}
    wsync.provision.assert_not_called()


async def test_mixed_stale_and_current(wsync):
    wsync.active_ids.return_value = ["fresh", "stale"]
    wsync.read_marker.side_effect = ["HASH_CURRENT", "OLD"]
    result = await _run_sync()
    assert result == {"scanned": 2, "synced": 1, "skipped": 1}
    wsync.provision.assert_awaited_once_with("stale", {"gmail"})


async def test_force_ignores_marker(wsync):
    wsync.active_ids.return_value = ["u1", "u2"]
    # read_marker must never be consulted when force=True
    wsync.read_marker.side_effect = AssertionError("marker read despite force")
    result = await _run_sync(force=True)
    assert result == {"scanned": 2, "synced": 2, "skipped": 0}


async def test_one_user_failure_does_not_abort_batch(wsync):
    wsync.active_ids.return_value = ["bad", "good"]
    wsync.read_marker.side_effect = ["OLD", "OLD"]
    wsync.provision.side_effect = [RuntimeError("boom"), None]
    result = await _run_sync()
    # 'bad' raised, 'good' still provisioned; neither aborts the run.
    assert result == {"scanned": 2, "synced": 1, "skipped": 0}
    assert wsync.provision.await_count == 2


async def test_active_only_false_uses_all_users(wsync):
    wsync.all_ids.return_value = ["a", "b", "c"]
    wsync.read_marker.side_effect = ["OLD", "OLD", "OLD"]
    result = await _run_sync(active_only=False)
    assert result["scanned"] == 3
    wsync.all_ids.assert_awaited_once()
    wsync.active_ids.assert_not_called()


async def test_empty_user_set(wsync):
    wsync.active_ids.return_value = []
    result = await _run_sync()
    assert result == {"scanned": 0, "synced": 0, "skipped": 0}
    wsync.provision.assert_not_called()


async def test_provision_receives_connected_ids(wsync):
    wsync.active_ids.return_value = ["u1"]
    wsync.read_marker.side_effect = ["OLD"]
    wsync.connected.return_value = {"slack", "notion"}
    await _run_sync()
    wsync.provision.assert_awaited_once_with("u1", {"slack", "notion"})


# ---------------------------------------------------------------------------
# workspace_sync startup wrappers
# ---------------------------------------------------------------------------


async def test_init_system_subtree_waits_for_mount_then_materializes():
    calls = []
    aget = AsyncMock(side_effect=lambda name: calls.append(("mount", name)))
    subtree = AsyncMock(side_effect=lambda: calls.append(("subtree",)))
    with (
        patch(f"{WS}.providers", SimpleNamespace(aget=aget)),
        patch(f"{WS}.ensure_system_subtree", subtree),
    ):
        await init_system_subtree()
    assert calls == [("mount", "juicefs_mount"), ("subtree",)]


async def test_resync_runs_active_only():
    with (
        patch(f"{WS}.providers", SimpleNamespace(aget=AsyncMock())),
        patch(f"{WS}.sync_stale_user_workspaces", new_callable=AsyncMock) as sync,
    ):
        await resync_stale_user_workspaces()
    sync.assert_awaited_once_with(active_only=True)


# ---------------------------------------------------------------------------
# integrations_fs.sync_user_integrations
# ---------------------------------------------------------------------------


async def test_sync_user_integrations_materializes_connected_set():
    with (
        patch(
            f"{IFS}.get_connected_integration_ids",
            new_callable=AsyncMock,
            return_value={"gmail", "slack"},
        ),
        patch(f"{IFS}.materialize_user_integrations", new_callable=AsyncMock) as mat,
    ):
        rc = await sync_user_integrations("user-1")
    assert rc == 0
    mat.assert_awaited_once_with("user-1", {"gmail", "slack"})


async def test_sync_user_integrations_empty_set_still_materializes():
    """A full disconnect leaves an empty set — must still rewrite the catalog."""
    with (
        patch(
            f"{IFS}.get_connected_integration_ids",
            new_callable=AsyncMock,
            return_value=set(),
        ),
        patch(f"{IFS}.materialize_user_integrations", new_callable=AsyncMock) as mat,
    ):
        await sync_user_integrations("user-1")
    mat.assert_awaited_once_with("user-1", set())


# ---------------------------------------------------------------------------
# get_connected_integration_ids — the shared filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "docs, expected",
    [
        ([], set()),
        ([{"integration_id": "gmail", "status": "connected"}], {"gmail"}),
        ([{"integration_id": "gmail", "status": "created"}], set()),
        ([{"status": "connected"}], set()),  # missing integration_id
        (
            [
                {"integration_id": "x", "status": "connected"},
                {"integration_id": "x", "status": "connected"},
            ],
            {"x"},
        ),
        (
            [
                {"integration_id": "a", "status": "connected"},
                {"integration_id": "b", "status": "created"},
                {"integration_id": "c", "status": "connected"},
            ],
            {"a", "c"},
        ),
    ],
)
async def test_get_connected_integration_ids_filter(docs, expected):
    with patch(
        f"{UINT}.get_user_integration_records",
        new_callable=AsyncMock,
        return_value=docs,
    ):
        assert await get_connected_integration_ids("u") == expected


@asynccontextmanager
async def _stale_posthog_credential() -> AsyncIterator[MagicMock]:
    """Workspace seams with posthog connected in Mongo but dead in Postgres."""
    record = MagicMock()
    record.model_dump.return_value = {"integration_id": "posthog", "status": "connected"}

    async def _list_for_user(user_id: str, *args: object, **kwargs: object) -> list[object]:
        return [record] if user_id == "u" else []

    with (
        patch(
            f"{UINT}.user_integration_repository.list_for_user",
            new_callable=AsyncMock,
            side_effect=_list_for_user,
        ),
        patch(f"{UINT}.MCPTokenStore", create=True) as token_store_class,
        patch("app.db.redis.redis_cache.get", new_callable=AsyncMock, return_value=None),
        patch("app.db.redis.redis_cache.set", new_callable=AsyncMock),
    ):
        token_store_class.return_value.are_connected = AsyncMock(return_value={"posthog": False})
        yield token_store_class


@pytest.mark.regression
async def test_user_integration_records_reflect_posthog_credential_status():
    async with _stale_posthog_credential() as token_store_class:
        result = await get_user_integration_records("u")

    assert result == [{"integration_id": "posthog", "status": "created"}]
    token_store_class.assert_called_once_with("u")
    token_store_class.return_value.are_connected.assert_awaited_once_with(["posthog"])


@pytest.mark.regression
async def test_connected_ids_use_live_posthog_credential_state():
    async with _stale_posthog_credential() as token_store_class:
        assert await get_connected_integration_ids("u") == set()

    token_store_class.assert_called_once_with("u")


async def test_mcp_record_without_stored_config_keeps_its_status():
    """An MCP record with no stored config keeps its status without crashing."""
    with (
        patch(
            f"{UINT}._get_cached_user_integration_records",
            new_callable=AsyncMock,
            return_value=[{"integration_id": "odd-mcp", "status": "connected"}],
        ),
        patch(f"{UINT}.get_integration_by_id") as mock_lookup,
        patch(f"{UINT}.MCPTokenStore", create=True) as token_store_class,
    ):
        mock_lookup.return_value = MagicMock(managed_by="mcp", mcp_config=None)

        result = await get_user_integration_records("u")

    assert result == [{"integration_id": "odd-mcp", "status": "connected"}]
    token_store_class.assert_not_called()


async def test_custom_auth_filter_returns_only_mcp_integrations_needing_auth():
    """The custom credential check mirrors the platform filter exactly."""
    docs = [
        MagicMock(integration_id="a", managed_by="mcp", requires_auth=True),
        MagicMock(integration_id="b", managed_by="mcp", requires_auth=False),
        MagicMock(integration_id="c", managed_by="composio", requires_auth=True),
    ]
    with patch(f"{UINT}.integration_repository") as mock_repo:
        mock_repo.find_by_ids = AsyncMock(return_value=docs)

        assert await user_integrations.get_custom_auth_mcp_ids(["a", "b", "c"]) == ["a"]

    mock_repo.find_by_ids.assert_awaited_once_with(["a", "b", "c"])


async def test_custom_auth_filter_empty_list_skips_the_query():
    with patch(f"{UINT}.integration_repository") as mock_repo:
        mock_repo.find_by_ids = AsyncMock()

        assert await user_integrations.get_custom_auth_mcp_ids([]) == []

    mock_repo.find_by_ids.assert_not_awaited()


async def test_custom_and_platform_records_reconcile_independently():
    """Platform and custom checks share one credential batch but filter separately."""
    records = [
        {"integration_id": "github", "status": "connected"},
        {"integration_id": "custom-uuid", "status": "connected"},
    ]
    custom_doc = MagicMock(integration_id="custom-uuid", managed_by="mcp", requires_auth=True)

    async def _find(ids: list[str]) -> list[object]:
        return [custom_doc] if custom_doc.integration_id in ids else []

    async def _check(ids: list[str]) -> dict[str, bool]:
        return dict.fromkeys(ids, False)

    with (
        patch(
            f"{UINT}._get_cached_user_integration_records",
            new_callable=AsyncMock,
            return_value=records,
        ),
        patch(f"{UINT}.integration_repository") as mock_repo,
        patch(f"{UINT}.MCPTokenStore", create=True) as token_store_class,
    ):
        mock_repo.find_by_ids = AsyncMock(side_effect=_find)
        token_store_class.return_value.are_connected = AsyncMock(side_effect=_check)

        result = await get_user_integration_records("u")

    by_id = {record["integration_id"]: record["status"] for record in result}
    assert by_id == {"github": "connected", "custom-uuid": "created"}
    mock_repo.find_by_ids.assert_awaited_once_with(["custom-uuid"])
    token_store_class.return_value.are_connected.assert_awaited_once_with(["custom-uuid"])


# ---------------------------------------------------------------------------
# connect-path wiring: update_user_integration_status
# ---------------------------------------------------------------------------


async def test_connect_schedules_sync():
    repo = MagicMock()
    repo.set_status = AsyncMock(return_value=True)
    with (
        patch(f"{USTATUS}.user_integration_repository", repo),
        patch(f"{USTATUS}.schedule_user_integrations_sync") as sched,
    ):
        ok = await update_user_integration_status("u", "gmail", "connected")
    assert ok is True
    sched.assert_called_once_with("u")


async def test_created_status_does_not_schedule_sync():
    repo = MagicMock()
    repo.set_status = AsyncMock(return_value=True)
    with (
        patch(f"{USTATUS}.user_integration_repository", repo),
        patch(f"{USTATUS}.schedule_user_integrations_sync") as sched,
    ):
        await update_user_integration_status("u", "gmail", "created")
    sched.assert_not_called()


# ---------------------------------------------------------------------------
# registration-path wiring: oauth_service.store_user_info
# ---------------------------------------------------------------------------


def _oauth_patches(repo, sched):
    return (
        patch(f"{OAUTH}.user_repository", repo),
        patch(f"{OAUTH}.schedule_user_provision", sched),
        patch(f"{OAUTH}.track_login", MagicMock()),
        patch(f"{OAUTH}.track_signup", MagicMock()),
        # Signup queues its ESP deliveries on the worker rather than sending
        # them here; stub the pool so the enqueue never reaches a real Redis.
        patch(f"{OAUTH}.RedisPoolManager.get_pool", new_callable=AsyncMock),
    )


async def test_new_user_provisions_workspace():
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=None)  # no existing user
    repo.create = AsyncMock(return_value=UserDocument(id="NEW123", name="Ada", email="ada@x.com"))
    sched = MagicMock()
    p = _oauth_patches(repo, sched)
    with p[0], p[1], p[2], p[3], p[4]:
        user_id, is_new = await store_user_info("Ada", "ada@x.com", None)
    assert is_new is True
    sched.assert_called_once_with("NEW123")


async def test_existing_user_does_not_provision():
    repo = MagicMock()
    repo.get_by_email = AsyncMock(
        return_value=UserDocument(id="EXISTING", name="Ada", email="ada@x.com", picture="p.png")
    )
    repo.update = AsyncMock()
    sched = MagicMock()
    p = _oauth_patches(repo, sched)
    with p[0], p[1], p[2], p[3], p[4]:
        user_id, is_new = await store_user_info("Ada", "ada@x.com", None)
    assert is_new is False
    sched.assert_not_called()
