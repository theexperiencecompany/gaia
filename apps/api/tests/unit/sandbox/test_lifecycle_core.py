"""Layer 3 — lifecycle core: create/resume/acquire, mount script, canary, watcher.

The sibling files cover death-eviction (`test_lifecycle_eviction`), pause
scheduling (`test_lifecycle_pause`) and cached-entry reuse
(`test_lifecycle_reuse`). This one attacks what they leave untouched: the
credential split that keeps the JuiceFS meta password out of a world-readable
`/proc/<pid>/cmdline`, the mount-script shipping path, the canary staleness
protocol, fresh-create vs resume routing in `_acquire_or_create`, and the
failure modes that must not leave a half-built sandbox in the pool or a lock
held forever.

Boundaries mocked: the e2b `AsyncSandbox` (create/connect/commands/files), the
Mongo repository, the tiered rate limiter, and the host-side JuiceFS seeding.
The pooling and lifecycle state machine is the real production code.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
import re
import time
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

from e2b import CommandExitException
import pytest

from app.api.v1.middleware.tiered_rate_limiter import RateLimitExceededException
from app.constants.sandbox import SANDBOX_LIFETIME_SECONDS
from app.models.sandbox_models import E2bSandboxDocument, E2bSandboxState
from app.services.sandbox import lifecycle
from app.services.sandbox.artifact_watcher import ArtifactWatcher
from app.services.sandbox.pool import PooledSandbox, get_sandbox_pool
from app.services.sandbox.shard_router import shard_for
from app.services.storage import JuiceFSUnavailable


def _uid() -> str:
    return f"u-{uuid.uuid4().hex}"


def _cmd_result(exit_code: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Stand-in for e2b's CommandResult."""
    return SimpleNamespace(exit_code=exit_code, stdout=stdout, stderr=stderr)


def _fake_sandbox(sandbox_id: str = "sbx-1") -> AsyncMock:
    """An AsyncSandbox that is alive, mounts cleanly and accepts file writes."""
    sbx = AsyncMock()
    sbx.sandbox_id = sandbox_id
    sbx.commands.run = AsyncMock(return_value=_cmd_result())
    sbx.is_running = AsyncMock(return_value=True)
    sbx.files.write = AsyncMock()
    sbx.files.read = AsyncMock(return_value="")
    sbx.set_timeout = AsyncMock()
    sbx.kill = AsyncMock()
    sbx.beta_pause = AsyncMock()
    return sbx


def _fake_watcher(alive: bool = True, stop_error: Exception | None = None) -> ArtifactWatcher:
    """Duck-typed stand-in: lifecycle only ever calls is_alive() and stop()."""
    return cast(
        ArtifactWatcher,
        SimpleNamespace(is_alive=lambda: alive, stop=AsyncMock(side_effect=stop_error)),
    )


def _sandbox_class(sbx: AsyncMock) -> MagicMock:
    """Replacement for the module-level `AsyncSandbox` symbol."""
    cls = MagicMock()
    cls.create = AsyncMock(return_value=sbx)
    cls.connect = AsyncMock(return_value=sbx)
    return cls


# --------------------------------------------------------------------------
# _split_meta_url — the credential that must never reach argv
# --------------------------------------------------------------------------


def test_meta_password_never_stays_in_the_url_handed_to_the_juicefs_daemon() -> None:
    # The juicefs daemon long-lives with this URL spliced into its argv, and
    # /proc/<pid>/cmdline is world-readable inside the sandbox. Leaving the
    # password in the URL hands the unprivileged sandbox user the metadata-DB
    # credentials with one `cat`.
    url, password = lifecycle._split_meta_url("postgres://gaia:s3cr3t@db.internal:5432/jfs0")
    assert "s3cr3t" not in url, "the meta password must not survive in the URL argv"
    assert password == "s3cr3t", "the password must still be delivered out of band"


def test_meta_url_keeps_user_host_port_and_database_when_the_password_is_split_out() -> None:
    # Dropping the port or the database name from the sanitized URL silently
    # points the mount at the wrong metadata engine.
    url, _ = lifecycle._split_meta_url("postgres://gaia:s3cr3t@db.internal:5432/jfs0")
    assert url == "postgres://gaia@db.internal:5432/jfs0"


def test_meta_url_without_a_password_round_trips_unchanged() -> None:
    # Local/dev Postgres has no password; mangling the URL here would break
    # every dev mount.
    original = "postgres://gaia@localhost:5432/jfs0"
    assert lifecycle._split_meta_url(original) == (original, "")


def test_empty_meta_url_yields_an_empty_pair_instead_of_raising() -> None:
    # Unconfigured JUICEFS_META_URL_TEMPLATE must fall through to mount.sh's
    # ephemeral branch, not blow up the acquire path.
    assert lifecycle._split_meta_url("") == ("", "")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("p%40ss", "p@ss"),
        ("p%2Fword", "p/word"),
        ("a%3Ab", "a:b"),
        ("q%3Fmark", "q?mark"),
        ("h%23ash", "h#ash"),
        ("%40%2F%3A%3F%23", "@/:?#"),
    ],
    ids=["at", "slash", "colon", "question", "hash", "all reserved"],
)
def test_a_percent_encoded_meta_password_is_decoded_before_it_reaches_the_env(
    raw: str, expected: str
) -> None:
    # urlsplit().password does NOT decode. Inline in the URL the driver would
    # decode it, but we hand it to JuiceFS out-of-band as META_PASSWORD, which
    # it treats as the literal password. So any meta-DB password containing a
    # reserved char authenticated with the WRONG string, the mount failed, and
    # mount.sh fell through to its ephemeral branch — a silently non-durable
    # /workspace instead of a loud error.
    _, password = lifecycle._split_meta_url(f"postgres://gaia:{raw}@db:5432/jfs0")
    assert password == expected


# --------------------------------------------------------------------------
# _mount_env — what the root process inside the sandbox receives
# --------------------------------------------------------------------------


def test_mount_env_delivers_the_meta_password_out_of_band_from_the_url() -> None:
    # JuiceFS only reads META_PASSWORD when the URL carries no password. If the
    # split is skipped, the password rides in argv AND META_PASSWORD is empty.
    with patch.object(
        lifecycle.settings,
        "JUICEFS_META_URL_TEMPLATE",
        "postgres://gaia:pw123@db:5432/jfs{shard}",
    ):
        env = lifecycle._mount_env("user-7", 3)
    assert env["META_PASSWORD"] == "pw123"
    assert "pw123" not in env["JFS_META_URL"]
    assert env["JFS_META_URL"] == "postgres://gaia@db:5432/jfs3", "shard must be substituted"
    assert env["USER_ID"] == "user-7"


def test_r2_credentials_are_stripped_of_secret_store_whitespace() -> None:
    # Infisical-fetched secrets pick up trailing newlines; AWS SigV4 then
    # rejects every request with a cryptic "InvalidSignature".
    with (
        patch.object(lifecycle.settings, "R2_ACCESS_KEY", "  AKIA123\n"),
        patch.object(lifecycle.settings, "R2_SECRET_KEY", "sec\n"),
        patch.object(lifecycle.settings, "R2_BUCKET", " bucket \n"),
        patch.object(lifecycle.settings, "R2_ACCOUNT_ID", "acct\t"),
    ):
        env = lifecycle._mount_env("u", 0)
    assert env["JFS_R2_KEY"] == "AKIA123"
    assert env["JFS_R2_SECRET"] == "sec"
    assert env["JFS_R2_BUCKET"] == "bucket"
    assert env["JFS_R2_ACCOUNT"] == "acct"


def test_unset_r2_settings_become_empty_strings_not_the_literal_none() -> None:
    # DevelopmentSettings leaves these None; `str(None)` would ship the literal
    # "None" as an R2 key and produce an unreadable auth error.
    with (
        patch.object(lifecycle.settings, "R2_ACCESS_KEY", None),
        patch.object(lifecycle.settings, "R2_SECRET_KEY", None),
    ):
        env = lifecycle._mount_env("u", 0)
    assert env["JFS_R2_KEY"] == ""
    assert env["JFS_R2_SECRET"] == ""


# --------------------------------------------------------------------------
# _enforce_creation_limit
# --------------------------------------------------------------------------


async def test_rate_limited_creation_reports_the_reset_time_and_required_plan() -> None:
    # The user-facing message is the only thing the agent surfaces; losing the
    # reset time or the plan makes the limit look like an unexplained failure.
    reset = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    exc = RateLimitExceededException(
        feature="sandbox_creation", plan_required="pro", reset_time=reset
    )
    with patch.object(lifecycle, "enforce_rate_limit", AsyncMock(side_effect=exc)):
        with pytest.raises(lifecycle.SandboxRateLimitError) as caught:
            await lifecycle._enforce_creation_limit("u1")
    message = str(caught.value)
    assert reset.isoformat() in message
    assert "PRO" in message


async def test_rate_limit_detail_that_is_not_a_dict_still_blocks_creation() -> None:
    # A limiter that raises with a plain string detail must still be a hard
    # stop, not a crash inside the error handler that gets logged and ignored.
    exc = RateLimitExceededException(feature="sandbox_creation")
    exc.detail = "too many"
    with patch.object(lifecycle, "enforce_rate_limit", AsyncMock(side_effect=exc)):
        with pytest.raises(lifecycle.SandboxRateLimitError):
            await lifecycle._enforce_creation_limit("u1")


async def test_limiter_infrastructure_failure_blocks_creation_instead_of_passing() -> None:
    # Redis down must not become "limit check skipped" — that is an unmetered
    # path to provisioning E2B VMs.
    with patch.object(
        lifecycle, "enforce_rate_limit", AsyncMock(side_effect=ConnectionError("redis down"))
    ):
        with pytest.raises(lifecycle.SandboxAcquisitionError) as caught:
            await lifecycle._enforce_creation_limit("u1")
    assert not isinstance(caught.value, lifecycle.SandboxRateLimitError)


async def test_a_user_under_the_limit_is_allowed_through() -> None:
    with patch.object(lifecycle, "enforce_rate_limit", AsyncMock(return_value={})) as limiter:
        await lifecycle._enforce_creation_limit("u1")
    limiter.assert_awaited_once_with("u1", lifecycle.SANDBOX_CREATION_FEATURE_KEY)


# --------------------------------------------------------------------------
# _create_fresh_sandbox
# --------------------------------------------------------------------------


async def test_missing_e2b_api_key_fails_before_any_sandbox_is_provisioned() -> None:
    # Without the guard the SDK is called anyway and fails deep inside e2b with
    # an opaque auth error instead of naming the missing config.
    cls = _sandbox_class(_fake_sandbox())
    with (
        patch.object(lifecycle.settings, "E2B_API_KEY", None),
        patch.object(lifecycle.settings, "E2B_TEMPLATE_ID", "tpl"),
        patch.object(lifecycle, "AsyncSandbox", cls),
    ):
        with pytest.raises(lifecycle.SandboxAcquisitionError, match="E2B_API_KEY"):
            await lifecycle._create_fresh_sandbox("u1", 0)
    cls.create.assert_not_awaited()


async def test_missing_template_id_fails_before_any_sandbox_is_provisioned() -> None:
    # A create with template=None would boot the default e2b image, which has
    # no JuiceFS tooling — the mount would then "succeed" as ephemeral and the
    # user's files would silently not persist.
    cls = _sandbox_class(_fake_sandbox())
    with (
        patch.object(lifecycle.settings, "E2B_API_KEY", "key"),
        patch.object(lifecycle.settings, "E2B_TEMPLATE_ID", None),
        patch.object(lifecycle, "AsyncSandbox", cls),
    ):
        with pytest.raises(lifecycle.SandboxAcquisitionError, match="E2B_TEMPLATE_ID"):
            await lifecycle._create_fresh_sandbox("u1", 0)
    cls.create.assert_not_awaited()


async def test_fresh_sandbox_is_created_with_the_full_lifetime_and_owner_metadata() -> None:
    # The SDK's default timeout is minutes, not the hour we need; and the
    # user_id/shard_id metadata is what the reaper uses to attribute an orphan.
    sbx = _fake_sandbox("sbx-new")
    cls = _sandbox_class(sbx)
    with (
        patch.object(lifecycle.settings, "E2B_API_KEY", "key"),
        patch.object(lifecycle.settings, "E2B_TEMPLATE_ID", "gaia-coder"),
        patch.object(lifecycle, "AsyncSandbox", cls),
        patch.object(lifecycle, "_run_mount_script", AsyncMock()),
    ):
        result = await lifecycle._create_fresh_sandbox("u1", 2)
    assert result is sbx
    kwargs = cls.create.await_args.kwargs
    assert kwargs["template"] == "gaia-coder"
    assert kwargs["timeout"] == SANDBOX_LIFETIME_SECONDS
    assert kwargs["metadata"] == {"user_id": "u1", "shard_id": "2"}


async def test_a_fresh_sandbox_is_mounted_with_its_own_shard_credentials() -> None:
    # Skipping the mount (or mounting with another shard's meta URL) hands back
    # a sandbox whose /workspace is empty or belongs to the wrong volume.
    sbx = _fake_sandbox()
    mount = AsyncMock()
    with (
        patch.object(lifecycle.settings, "E2B_API_KEY", "key"),
        patch.object(lifecycle.settings, "E2B_TEMPLATE_ID", "gaia-coder"),
        patch.object(lifecycle.settings, "JUICEFS_META_URL_TEMPLATE", "postgres://db/jfs{shard}"),
        patch.object(lifecycle, "AsyncSandbox", _sandbox_class(sbx)),
        patch.object(lifecycle, "_run_mount_script", mount),
    ):
        await lifecycle._create_fresh_sandbox("u1", 5)
    mount.assert_awaited_once()
    mounted_sbx, env = mount.await_args.args
    assert mounted_sbx is sbx
    assert env["JFS_META_URL"] == "postgres://db/jfs5"
    assert env["USER_ID"] == "u1"


# --------------------------------------------------------------------------
# _run_mount_script
# --------------------------------------------------------------------------


def _b64_payload(cmd: str) -> bytes:
    match = re.search(r"printf %s '([A-Za-z0-9+/=]+)'", cmd)
    assert match is not None, f"command is not the base64-shipping form: {cmd!r}"
    return base64.b64decode(match.group(1))


async def test_mount_script_ships_the_apis_current_copy_byte_for_byte() -> None:
    # The point of shipping the script at acquire time is that edits to
    # mount_juicefs.sh take effect without an E2B template rebuild. A mangled
    # or truncated payload would run a broken script as root.
    sbx = _fake_sandbox()
    await lifecycle._run_mount_script(sbx, {"USER_ID": "u1"})
    cmd = sbx.commands.run.await_args.args[0]
    assert _b64_payload(cmd) == lifecycle.MOUNT_SCRIPT_FILE.read_bytes()


async def test_mount_credentials_ride_in_env_and_never_in_the_command_argv() -> None:
    # argv is world-readable via /proc; only `envs` on the root process is safe.
    sbx = _fake_sandbox()
    env = {"USER_ID": "u1", "META_PASSWORD": "pw-abc", "JFS_R2_SECRET": "r2-secret"}
    await lifecycle._run_mount_script(sbx, env)
    call = sbx.commands.run.await_args
    assert "pw-abc" not in call.args[0]
    assert "r2-secret" not in call.args[0]
    assert call.kwargs["envs"] == env
    assert call.kwargs["user"] == "root", "envd must fork the script directly as root"


async def test_mount_script_falls_back_to_the_template_copy_when_the_api_file_is_unreadable() -> (
    None
):
    # A packaging change that drops scripts/ from the image must degrade to the
    # template-baked mount.sh, not fail every sandbox acquisition.
    sbx = _fake_sandbox()
    with patch.object(lifecycle, "MOUNT_SCRIPT_FILE", Path("/nonexistent/mount_juicefs.sh")):
        await lifecycle._run_mount_script(sbx, {})
    assert sbx.commands.run.await_args.args[0] == lifecycle.MOUNT_SCRIPT_PATH


async def test_a_crashed_mount_script_raises_with_its_stderr() -> None:
    # Swallowing a crashed mount hands back a sandbox with no /workspace at
    # all; every subsequent file tool then fails with a confusing ENOENT.
    sbx = _fake_sandbox()
    sbx.commands.run = AsyncMock(return_value=_cmd_result(exit_code=3, stderr="mount: no juicefs"))
    with pytest.raises(lifecycle.SandboxAcquisitionError, match="mount: no juicefs"):
        await lifecycle._run_mount_script(sbx, {})


async def test_an_ephemeral_fallback_mount_is_recorded_but_not_treated_as_a_crash() -> None:
    # mount.sh exits 0 with a `WARN:` when it falls back to a non-durable
    # /workspace. Losing that signal means silent data loss for the user.
    sbx = _fake_sandbox()
    sbx.commands.run = AsyncMock(
        return_value=_cmd_result(exit_code=0, stderr="WARN: falling back to ephemeral\n")
    )
    recorded: dict[str, object] = {}
    with patch.object(lifecycle, "_record", recorded.update):
        await lifecycle._run_mount_script(sbx, {})
    assert recorded["mount_status"] == "ephemeral_fallback"


async def test_a_clean_mount_is_recorded_as_mounted() -> None:
    sbx = _fake_sandbox()
    recorded: dict[str, object] = {}
    with patch.object(lifecycle, "_record", recorded.update):
        await lifecycle._run_mount_script(sbx, {})
    assert recorded["mount_status"] == "mounted"


# --------------------------------------------------------------------------
# _run_silent — internal probes where non-zero is an answer, not an error
# --------------------------------------------------------------------------


async def test_silent_probe_reports_a_non_zero_exit_instead_of_raising() -> None:
    sbx = _fake_sandbox()
    sbx.commands.run = AsyncMock(return_value=_cmd_result(exit_code=1, stdout="o", stderr="e"))
    assert await lifecycle._run_silent(sbx, "mountpoint -q /workspace") == (1, "o", "e")


async def test_silent_probe_turns_a_raised_command_error_into_a_negative_answer() -> None:
    # e2b raises CommandExitException on ANY non-zero exit. If that escaped,
    # `mountpoint -q` returning 1 (a legitimate "not mounted") would crash the
    # acquire path instead of triggering a remount.
    sbx = _fake_sandbox()
    sbx.commands.run = AsyncMock(
        side_effect=CommandExitException(
            stdout="", stderr="not a mountpoint", exit_code=1, error=None
        )
    )
    exit_code, _, stderr = await lifecycle._run_silent(sbx, "mountpoint -q /workspace")
    assert exit_code == 1
    assert "not a mountpoint" in stderr


async def test_silent_probe_normalises_a_missing_exit_code_to_success() -> None:
    sbx = _fake_sandbox()
    sbx.commands.run = AsyncMock(return_value=SimpleNamespace(exit_code=None))
    assert await lifecycle._run_silent(sbx, "true") == (0, "", "")


# --------------------------------------------------------------------------
# _ensure_mounted
# --------------------------------------------------------------------------


async def test_a_healthy_mount_is_not_remounted() -> None:
    # Re-running mount.sh on every acquire would add ~seconds to every tool
    # call and tear down a working FUSE mount for no reason.
    sbx = _fake_sandbox()
    mount = AsyncMock()
    with patch.object(lifecycle, "_run_mount_script", mount):
        await lifecycle._ensure_mounted(sbx, {"USER_ID": "u1"})
    mount.assert_not_awaited()


async def test_a_wedged_mount_that_still_passes_mountpoint_is_remounted_with_credentials() -> None:
    # A dead JuiceFS daemon leaves the mount-table entry in place, so
    # `mountpoint -q` says yes while every real I/O returns EIO. Probing only
    # the mount table would leave that sandbox wedged for its whole lifetime.
    sbx = _fake_sandbox()

    async def run(cmd: str, **kwargs: Any) -> SimpleNamespace:
        return _cmd_result(exit_code=1 if "stat" in cmd else 0)

    sbx.commands.run = AsyncMock(side_effect=run)
    mount = AsyncMock()
    env = {"USER_ID": "u1", "META_PASSWORD": "pw"}
    with patch.object(lifecycle, "_run_mount_script", mount):
        await lifecycle._ensure_mounted(sbx, env)
    mount.assert_awaited_once()
    assert mount.await_args.args[1] == env, "a remount without credentials mounts nothing"


# --------------------------------------------------------------------------
# canary protocol — the E2B GH#884 stale-filesystem mitigation
# --------------------------------------------------------------------------


async def test_first_use_after_acquire_writes_a_canary_and_accepts_the_sandbox() -> None:
    sbx = _fake_sandbox()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts=None)
    assert await lifecycle._verify_canary_or_die(entry) is True
    path, written = sbx.files.write.await_args.args
    assert path == lifecycle.CANARY_PATH
    assert entry.last_canary_ts == written, "the cached canary must match what is on disk"


async def test_a_canary_that_does_not_match_reports_a_stale_filesystem() -> None:
    # This is the whole point of the canary: a resumed sandbox whose FS rolled
    # back to an older snapshot must be recreated, not silently used.
    sbx = _fake_sandbox()
    sbx.files.read = AsyncMock(return_value="2020-01-01T00:00:00+00:00")
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="2026-01-01T00:00:00+00:00")
    assert await lifecycle._verify_canary_or_die(entry) is False


async def test_a_missing_canary_file_reports_a_stale_filesystem() -> None:
    # A rolled-back FS loses the file entirely; a read failure must be "stale",
    # never "assume fine".
    sbx = _fake_sandbox()
    sbx.files.read = AsyncMock(side_effect=FileNotFoundError("no canary"))
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="ts-1")
    assert await lifecycle._verify_canary_or_die(entry) is False


async def test_an_empty_canary_file_reports_a_stale_filesystem() -> None:
    # A truncated write leaves a zero-byte file; comparing "" to the cached ts
    # must not accidentally match.
    sbx = _fake_sandbox()
    sbx.files.read = AsyncMock(return_value="   \n")
    assert await lifecycle._read_canary(sbx) is None


async def test_canary_comparison_survives_a_trailing_newline_from_the_sandbox() -> None:
    # Some FUSE/text paths append a newline. Comparing unstripped content would
    # declare every healthy sandbox stale and recreate it on every single call.
    sbx = _fake_sandbox()
    sbx.files.read = AsyncMock(return_value="ts-1\n")
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="ts-1")
    assert await lifecycle._verify_canary_or_die(entry) is True


async def test_writing_a_canary_returns_the_exact_value_it_stored() -> None:
    # A mismatch between the returned value and the written one makes the very
    # next verify fail and evicts a perfectly healthy sandbox.
    sbx = _fake_sandbox()
    returned = await lifecycle._write_canary(sbx)
    assert sbx.files.write.await_args.args == (lifecycle.CANARY_PATH, returned)


# --------------------------------------------------------------------------
# _connect_sandbox
# --------------------------------------------------------------------------


async def test_connect_refreshes_the_server_side_lifetime_of_a_resumed_sandbox() -> None:
    # connect() without an explicit timeout inherits the SDK's short default,
    # so a resumed sandbox gets killed minutes into the session.
    sbx = _fake_sandbox()
    cls = _sandbox_class(sbx)
    with patch.object(lifecycle, "AsyncSandbox", cls):
        assert await lifecycle._connect_sandbox("sbx-old") is sbx
    assert cls.connect.await_args.kwargs["timeout"] == SANDBOX_LIFETIME_SECONDS


async def test_connect_failure_returns_none_so_acquire_falls_through_to_a_fresh_create() -> None:
    cls = _sandbox_class(_fake_sandbox())
    cls.connect = AsyncMock(side_effect=RuntimeError("sandbox not found"))
    with patch.object(lifecycle, "AsyncSandbox", cls):
        assert await lifecycle._connect_sandbox("sbx-old") is None


@pytest.mark.slow
async def test_a_hung_control_plane_connect_is_bounded_instead_of_stalling_the_agent() -> None:
    # Without the wait_for, a wedged E2B control plane blocks the user's tool
    # call for the full SDK timeout with no output at all.
    cls = _sandbox_class(_fake_sandbox())

    async def hang(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(5)

    cls.connect = AsyncMock(side_effect=hang)
    started = time.monotonic()
    with (
        patch.object(lifecycle, "AsyncSandbox", cls),
        patch.object(lifecycle, "SANDBOX_CONNECT_TIMEOUT_SECONDS", 0.05),
    ):
        assert await lifecycle._connect_sandbox("sbx-old") is None
    assert time.monotonic() - started < 2, "connect must be bounded, not wait out the SDK"


# --------------------------------------------------------------------------
# watcher lifecycle
# --------------------------------------------------------------------------


async def test_a_watcher_that_fails_to_start_never_blocks_sandbox_acquisition() -> None:
    # The watcher is a latency optimization; the host-side JuiceFS listing is
    # authoritative. Letting its failure escape would make every tool call fail
    # whenever envd's stream setup hiccups.
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x")
    with patch.object(
        lifecycle, "start_watcher_for", AsyncMock(side_effect=RuntimeError("envd stream refused"))
    ):
        await lifecycle._ensure_watcher("u1", entry)
    assert entry.watcher is None


async def test_a_live_watcher_is_not_restarted_on_every_acquire() -> None:
    # Restarting leaks the previous HTTP/2 stream to envd and duplicates every
    # artifact event in the chat UI.
    watcher = _fake_watcher(alive=True)
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x", watcher=watcher)
    start = AsyncMock(return_value=_fake_watcher())
    with patch.object(lifecycle, "start_watcher_for", start):
        await lifecycle._ensure_watcher("u1", entry)
    start.assert_not_awaited()
    assert entry.watcher is watcher


async def test_a_dead_watcher_is_replaced_so_artifacts_keep_surfacing() -> None:
    # A watcher whose stream died after a pause/resume reports is_alive() False;
    # keeping it means agent-written files never appear in the UI again.
    dead = _fake_watcher(alive=False)
    fresh = _fake_watcher(alive=True)
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x", watcher=dead)
    with patch.object(lifecycle, "start_watcher_for", AsyncMock(return_value=fresh)):
        await lifecycle._ensure_watcher("u1", entry)
    assert entry.watcher is fresh


async def test_stopping_a_watcher_clears_the_handle_even_when_stop_raises() -> None:
    # A stale handle left behind would make the next _ensure_watcher believe a
    # watcher is running (is_alive on a half-stopped watcher) and never reopen.
    watcher = _fake_watcher(stop_error=RuntimeError("stream already gone"))
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x", watcher=watcher)
    await lifecycle._stop_watcher(entry)
    assert entry.watcher is None


# --------------------------------------------------------------------------
# _seed_user_subtrees
# --------------------------------------------------------------------------


async def test_both_the_workspace_and_the_skills_subtree_are_seeded_host_side() -> None:
    # The sandbox mounts each with --subdir; a missing skills subtree makes the
    # skills mount fail and silently drops the user's installed skills.
    workspace, skills = AsyncMock(), AsyncMock()
    with (
        patch.object(lifecycle, "ensure_user_workspace", workspace),
        patch.object(lifecycle, "ensure_user_skills_dir", skills),
    ):
        await lifecycle._seed_user_subtrees("u1")
    workspace.assert_awaited_once_with("u1")
    skills.assert_awaited_once_with("u1")


async def test_a_missing_host_juicefs_mount_does_not_block_sandbox_creation() -> None:
    # Native dev has no /mnt/jfs; mount.sh then takes its ephemeral branch.
    with patch.object(
        lifecycle,
        "ensure_user_workspace",
        AsyncMock(side_effect=JuiceFSUnavailable("no mount")),
    ):
        await lifecycle._seed_user_subtrees("u1")


async def test_a_real_seeding_failure_is_not_swallowed_as_dev_mode() -> None:
    # Only JuiceFSUnavailable means "dev mode". A permission or I/O error would
    # otherwise be masked, and the user would get a sandbox mounted on nothing.
    with patch.object(
        lifecycle, "ensure_user_workspace", AsyncMock(side_effect=PermissionError("EACCES"))
    ):
        with pytest.raises(PermissionError):
            await lifecycle._seed_user_subtrees("u1")


# --------------------------------------------------------------------------
# _resume_existing_sandbox
# --------------------------------------------------------------------------


def _doc(
    sandbox_id: str | None, workspace_version: int = 0, shard_id: int = 0
) -> E2bSandboxDocument:
    return E2bSandboxDocument(
        user_id="u1",
        shard_id=shard_id,
        state=E2bSandboxState.PAUSED,
        sandbox_id=sandbox_id,
        workspace_version=workspace_version,
    )


async def test_a_record_without_a_sandbox_id_is_not_resumed() -> None:
    # A doc written before the sandbox id was known must not turn into
    # connect(None), which the SDK would resolve to some other sandbox or error.
    connect = AsyncMock()
    with patch.object(lifecycle, "_connect_sandbox", connect):
        assert await lifecycle._resume_existing_sandbox(_doc(None), {}) is None
    connect.assert_not_awaited()


async def test_an_unreachable_recorded_sandbox_falls_through_instead_of_raising() -> None:
    with patch.object(lifecycle, "_connect_sandbox", AsyncMock(return_value=None)):
        assert await lifecycle._resume_existing_sandbox(_doc("sbx-old"), {}) is None


async def test_a_resumed_but_unhealthy_sandbox_is_not_handed_back() -> None:
    # connect() can succeed against a sandbox that is wedged. Returning it
    # means every tool call in the turn times out instead of one fresh create.
    sbx = _fake_sandbox()
    sbx.is_running = AsyncMock(return_value=False)
    with patch.object(lifecycle, "_connect_sandbox", AsyncMock(return_value=sbx)):
        assert await lifecycle._resume_existing_sandbox(_doc("sbx-old"), {}) is None


async def test_a_resumed_sandbox_is_remounted_before_it_is_used() -> None:
    # FUSE mounts do not survive a pause/resume cycle; skipping the check hands
    # back a sandbox whose /workspace is stale or gone.
    sbx = _fake_sandbox()
    ensure = AsyncMock()
    env = {"USER_ID": "u1"}
    with (
        patch.object(lifecycle, "_connect_sandbox", AsyncMock(return_value=sbx)),
        patch.object(lifecycle, "_ensure_mounted", ensure),
    ):
        assert await lifecycle._resume_existing_sandbox(_doc("sbx-old"), env) is sbx
    ensure.assert_awaited_once_with(sbx, env)


# --------------------------------------------------------------------------
# _acquire_or_create — the state machine
# --------------------------------------------------------------------------


def _acquire_patches(sbx: AsyncMock, repo: AsyncMock) -> list[Any]:
    """Patch only the true boundaries: e2b, Mongo, the limiter, host JuiceFS."""
    return [
        patch.object(lifecycle.settings, "E2B_API_KEY", "key"),
        patch.object(lifecycle.settings, "E2B_TEMPLATE_ID", "gaia-coder"),
        patch.object(lifecycle, "AsyncSandbox", _sandbox_class(sbx)),
        patch.object(lifecycle, "e2b_sandbox_repository", repo),
        patch.object(lifecycle, "enforce_rate_limit", AsyncMock(return_value={})),
        patch.object(lifecycle, "ensure_user_workspace", AsyncMock()),
        patch.object(lifecycle, "ensure_user_skills_dir", AsyncMock()),
        patch.object(lifecycle, "start_watcher_for", AsyncMock(return_value=_fake_watcher())),
        patch.object(lifecycle, "_run_mount_script", AsyncMock()),
    ]


async def _acquire(user_id: str, sbx: AsyncMock, repo: AsyncMock) -> PooledSandbox:
    stack = _acquire_patches(sbx, repo)
    for p in stack:
        p.start()
    try:
        return await lifecycle._acquire_or_create(user_id)
    finally:
        for p in reversed(stack):
            p.stop()


async def test_a_fresh_acquisition_pools_the_entry_and_records_the_canary_it_wrote() -> None:
    # If the recorded/cached canary is not the value actually written into the
    # sandbox, the very next acquire declares the FS stale and recreates the
    # sandbox — an infinite recreate loop that costs a VM per tool call.
    uid = _uid()
    sbx = _fake_sandbox("sbx-fresh")
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=None)
    try:
        entry = await _acquire(uid, sbx, repo)
        assert entry.sandbox is sbx
        assert get_sandbox_pool().get(uid) is entry, "the entry must be pooled for reuse"
        written = sbx.files.write.await_args.args[1]
        kwargs = repo.record_acquisition.await_args.kwargs
        assert entry.last_canary_ts == written
        assert kwargs["last_canary_ts"] == written
        assert kwargs["sandbox_id"] == "sbx-fresh"
        assert kwargs["workspace_version"] == 1
        assert kwargs["shard_id"] == shard_for(uid)
    finally:
        get_sandbox_pool().evict(uid)


async def test_a_resumed_sandbox_keeps_its_recorded_workspace_version() -> None:
    # Bumping the version on resume would make the workspace look re-created
    # and invalidate consumers that key off it.
    uid = _uid()
    sbx = _fake_sandbox("sbx-old")
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=_doc("sbx-old", workspace_version=7))
    try:
        await _acquire(uid, sbx, repo)
        assert repo.record_acquisition.await_args.kwargs["workspace_version"] == 7
    finally:
        get_sandbox_pool().evict(uid)


async def test_a_resume_is_not_charged_against_the_creation_rate_limit() -> None:
    # Only provisioning a new VM costs money. Metering resumes would lock a
    # heavy user out of their own existing sandbox.
    uid = _uid()
    sbx = _fake_sandbox("sbx-old")
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=_doc("sbx-old", workspace_version=3))
    limiter = AsyncMock(return_value={})
    stack = [*_acquire_patches(sbx, repo), patch.object(lifecycle, "enforce_rate_limit", limiter)]
    for p in stack:
        p.start()
    try:
        await lifecycle._acquire_or_create(uid)
    finally:
        for p in reversed(stack):
            p.stop()
        get_sandbox_pool().evict(uid)
    limiter.assert_not_awaited()


async def test_a_failed_resume_creates_fresh_and_bumps_the_workspace_version() -> None:
    # The old sandbox is gone, so its /workspace snapshot is too — the version
    # has to move or stale artifacts stay addressable.
    uid = _uid()
    sbx = _fake_sandbox("sbx-new")
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=_doc("sbx-dead", workspace_version=4))
    stack = [
        *_acquire_patches(sbx, repo),
        patch.object(lifecycle, "_resume_existing_sandbox", AsyncMock(return_value=None)),
    ]
    for p in stack:
        p.start()
    try:
        entry = await lifecycle._acquire_or_create(uid)
        assert entry.sandbox is sbx
        assert repo.record_acquisition.await_args.kwargs["workspace_version"] == 5
    finally:
        for p in reversed(stack):
            p.stop()
        get_sandbox_pool().evict(uid)


async def test_a_rate_limited_user_gets_no_pool_entry_and_no_mongo_record() -> None:
    # A pooled entry for a sandbox that was never created would be handed to
    # the next tool call and fail on every command.
    uid = _uid()
    sbx = _fake_sandbox()
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=None)
    stack = [
        *_acquire_patches(sbx, repo),
        patch.object(
            lifecycle,
            "enforce_rate_limit",
            AsyncMock(side_effect=RateLimitExceededException(feature="sandbox_creation")),
        ),
    ]
    for p in stack:
        p.start()
    try:
        with pytest.raises(lifecycle.SandboxRateLimitError):
            await lifecycle._acquire_or_create(uid)
    finally:
        for p in reversed(stack):
            p.stop()
    assert get_sandbox_pool().get(uid) is None
    repo.record_acquisition.assert_not_awaited()


async def test_an_e2b_failure_mid_acquire_leaves_nothing_behind() -> None:
    # A half-built acquire that still pools an entry or records a Mongo doc
    # makes the next acquire "resume" a sandbox that does not exist.
    uid = _uid()
    sbx = _fake_sandbox()
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=None)
    stack = [
        *_acquire_patches(sbx, repo),
        patch.object(
            lifecycle, "_create_fresh_sandbox", AsyncMock(side_effect=RuntimeError("e2b 503"))
        ),
    ]
    for p in stack:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="e2b 503"):
            await lifecycle._acquire_or_create(uid)
    finally:
        for p in reversed(stack):
            p.stop()
    assert get_sandbox_pool().get(uid) is None
    repo.record_acquisition.assert_not_awaited()


async def test_a_healthy_cached_entry_short_circuits_before_any_mongo_or_e2b_call() -> None:
    # Reuse is the whole point of the pool; falling through to Mongo/E2B on
    # every tool call would add a control-plane round-trip per command.
    uid = _uid()
    sbx = _fake_sandbox()
    sbx.files.read = AsyncMock(return_value="ts-1")
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="ts-1", timeout_refreshed_at=time.monotonic())
    get_sandbox_pool().put(uid, entry)
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=None)
    try:
        assert await _acquire(uid, sbx, repo) is entry
        repo.get_for_user.assert_not_awaited()
        repo.record_acquisition.assert_not_awaited()
    finally:
        get_sandbox_pool().evict(uid)


# --------------------------------------------------------------------------
# _cancel_pause_task / pause_sandbox_for_user
# --------------------------------------------------------------------------


async def test_cancelling_the_idle_pause_waits_for_it_to_actually_unwind() -> None:
    # A bare cancel() only *requests* cancellation. Returning before the task
    # unwinds lets a pause that is already in flight server-side land on a
    # sandbox we just handed to a tool call.
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x")
    entry.pause_task = asyncio.create_task(asyncio.sleep(30))
    task = entry.pause_task
    await lifecycle._cancel_pause_task(entry)
    assert task.done(), "cancel must be awaited to completion, not just requested"
    assert entry.pause_task is None


async def test_cancelling_an_already_finished_pause_is_a_no_op() -> None:
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x")
    entry.pause_task = asyncio.create_task(asyncio.sleep(0))
    await entry.pause_task
    await lifecycle._cancel_pause_task(entry)
    assert entry.pause_task is None


async def test_a_manual_pause_stops_the_watcher_and_drops_the_pending_idle_pause() -> None:
    # Pausing with the watcher still attached leaks its envd stream, and a
    # surviving idle-pause task would fire again on a sandbox already paused.
    uid = _uid()
    sbx = _fake_sandbox()
    watcher = _fake_watcher()
    entry = PooledSandbox(sandbox=sbx, last_canary_ts="x", watcher=watcher)
    entry.pause_task = asyncio.create_task(asyncio.sleep(30))
    pending = entry.pause_task
    get_sandbox_pool().put(uid, entry)
    try:
        with patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()):
            assert await lifecycle.pause_sandbox_for_user(uid) is True
    finally:
        get_sandbox_pool().evict(uid)
    sbx.beta_pause.assert_awaited_once()
    assert entry.watcher is None
    assert pending.done()


# --------------------------------------------------------------------------
# acquire_sandbox — lock discipline
# --------------------------------------------------------------------------


async def test_an_empty_user_id_is_rejected_before_anything_is_provisioned() -> None:
    # An empty user_id would key the pool, the Mongo doc and the JuiceFS subdir
    # on "" — a shared cross-user sandbox.
    acquire = AsyncMock()
    with patch.object(lifecycle, "_acquire_or_create", acquire):
        with pytest.raises(lifecycle.SandboxAcquisitionError, match="user_id is required"):
            async with lifecycle.acquire_sandbox(""):
                pass
    acquire.assert_not_awaited()


async def test_the_per_user_lock_is_released_when_acquisition_itself_fails() -> None:
    # A lock held after a failed acquire deadlocks that user's every future
    # tool call for the lifetime of the process.
    uid = _uid()
    with patch.object(
        lifecycle,
        "_acquire_or_create",
        AsyncMock(side_effect=lifecycle.SandboxAcquisitionError("e2b down")),
    ):
        with pytest.raises(lifecycle.SandboxAcquisitionError):
            async with lifecycle.acquire_sandbox(uid):
                pass
    assert not (await get_sandbox_pool().get_lock(uid)).locked()


async def test_the_refcount_returns_to_zero_after_a_failing_tool_call() -> None:
    # A leaked refcount means the idle-pause never fires and the sandbox burns
    # its full billed lifetime after the user has stopped working.
    uid = _uid()
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x")
    with (
        patch.object(lifecycle, "_acquire_or_create", AsyncMock(return_value=entry)),
        patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()),
        patch.object(lifecycle, "_schedule_pause"),
    ):
        with pytest.raises(RuntimeError):
            async with lifecycle.acquire_sandbox(uid):
                raise RuntimeError("tool failed")
    assert entry.refcount == 0


async def test_concurrent_acquisitions_for_one_user_do_not_overlap() -> None:
    # Two tool calls sharing one sandbox handle concurrently would interleave
    # mount checks and canary writes, and could pause a sandbox mid-command.
    uid = _uid()
    entry = PooledSandbox(sandbox=_fake_sandbox(), last_canary_ts="x")
    order: list[str] = []

    async def worker(tag: str) -> None:
        async with lifecycle.acquire_sandbox(uid):
            order.append(f"enter-{tag}")
            await asyncio.sleep(0.02)
            order.append(f"exit-{tag}")

    with (
        patch.object(lifecycle, "_acquire_or_create", AsyncMock(return_value=entry)),
        patch.object(lifecycle, "e2b_sandbox_repository", AsyncMock()),
        patch.object(lifecycle, "_schedule_pause"),
    ):
        await asyncio.gather(worker("a"), worker("b"))

    assert order[0].removeprefix("enter-") == order[1].removeprefix("exit-"), (
        f"same-user acquisitions must serialize, got {order}"
    )


async def test_a_users_recorded_shard_is_honoured_instead_of_being_recomputed() -> None:
    # shard_router's docstring: the Mongo doc records the shard "so we never
    # re-shard a user without an explicit migration". But the shard was always
    # recomputed from the CURRENT JUICEFS_NUM_SHARDS and the recorded value had
    # no read site at all — so raising the shard count silently pointed an
    # existing user at a different meta DB, and their whole workspace read as
    # empty. Pin the recorded shard.
    uid = _uid()
    sbx = _fake_sandbox("sbx-old")
    repo = AsyncMock()
    repo.get_for_user = AsyncMock(return_value=_doc("sbx-old", shard_id=3))
    with patch.object(lifecycle, "shard_for", lambda _u: 7):
        try:
            await _acquire(uid, sbx, repo)
            assert repo.record_acquisition.await_args.kwargs["shard_id"] == 3
        finally:
            get_sandbox_pool().evict(uid)
