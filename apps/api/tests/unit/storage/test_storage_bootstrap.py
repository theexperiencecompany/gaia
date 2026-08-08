"""JuiceFS bootstrap: idempotency, failure classification, retry supervision.

This module runs once per container start and decides whether to *format* a
shared volume and whether to *lazy-unmount* a path. Both are destructive if the
idempotency guards misfire — reformatting a live volume or `fusermount -u -z`
against a healthy mount takes every user's workspace offline, and neither shows
up as an exception. So the guards, not the happy path, are what is attacked here.

Boundaries mocked: `_run` (the juicefs/fusermount subprocess), `_is_mounted`
(needs a real kernel mount), and the clock. Everything else — path creation,
key materialization, argv construction, error classification, backoff maths,
thread supervision — is the real production code running against a real
`tmp_path` filesystem.
"""

from __future__ import annotations

from collections.abc import Iterator
import errno
from pathlib import Path
import subprocess
import threading
import time as real_time
from typing import Any, cast

import pytest

from app.services.storage import bootstrap
from app.services.storage.bootstrap import (
    _bootstrap_loop,
    _bootstrap_once,
    _classify,
    _format_if_needed,
    _is_mounted,
    _mask_meta,
    _materialize_encryption_key,
    _meta_err_tail,
    _meta_url,
    _missing_settings,
    _mount,
    _mount_state,
)

META = "postgres://gaia:secret@meta.example.com:5432/jfs"


def _init_juicefs_mount() -> Any:
    """The real provider coroutine, unwrapped from @lazy_provider's closure.

    `lazy_provider` replaces the module attribute with a zero-arg registration
    function; the coroutine we need is the `func` free variable it closed over.
    """
    registrar = bootstrap.init_juicefs_mount
    freevars = registrar.__code__.co_freevars
    closure = registrar.__closure__
    assert closure is not None
    return closure[freevars.index("func")].cell_contents


# ── helpers ──────────────────────────────────────────────────────────


def completed(returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


class RunRecorder:
    """Stand-in for `_run` — the only subprocess boundary in this module."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self.replies: dict[str, subprocess.CompletedProcess[str]] = {}

    def __call__(
        self,
        cmd: list[str],
        *,
        timeout: int = 60,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        self.envs.append(env)
        return self.replies.get(" ".join(cmd[:2]), completed())

    def argv(self, key: str) -> list[str]:
        matches = [c for c in self.calls if " ".join(c[:2]) == key]
        assert len(matches) == 1, f"expected exactly one {key!r} call, got {len(matches)}"
        return matches[0]

    def count(self, key: str) -> int:
        return sum(1 for c in self.calls if " ".join(c[:2]) == key)


class Clock:
    """Virtual clock so timeout/backoff windows are asserted, not waited out."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def mounted_after(n: int) -> Any:
    """`_is_mounted` stub that flips to True on the (n+1)-th call."""
    state = {"calls": 0}

    def check(path: Path) -> bool:
        state["calls"] += 1
        return state["calls"] > n

    return check


def flag_value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


class StatRaiser:
    """Minimal Path stand-in whose `stat()` fails with a chosen errno."""

    def __init__(self, code: int) -> None:
        self._code = code

    def stat(self) -> object:
        raise OSError(self._code, "boom")

    def __str__(self) -> str:
        return "/mnt/jfs"


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    c = Clock()
    monkeypatch.setattr(bootstrap, "time", c)
    return c


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> RunRecorder:
    recorder = RunRecorder()
    monkeypatch.setattr(bootstrap, "_run", recorder)
    return recorder


@pytest.fixture
def cfg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A fully-configured bootstrap rooted in tmp_path. Returns the mount path."""
    mount = tmp_path / "mnt" / "jfs"
    for name, value in (
        ("R2_ACCOUNT_ID", "acct123"),
        ("R2_BUCKET", "gaia-workspaces"),
        ("R2_ACCESS_KEY", "AKIAEXAMPLE"),
        ("R2_SECRET_KEY", "s3cr3t"),
        ("JUICEFS_META_URL_TEMPLATE", META),
        ("JUICEFS_HOST_MOUNT_PATH", str(mount)),
        ("JFS_ENCRYPTION_KEY", None),
        ("JUICEFS_MOUNT_READY_TIMEOUT", 15),
        ("JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 1),
        ("JUICEFS_BOOTSTRAP_RETRY_BACKOFF", 1),
    ):
        monkeypatch.setattr(bootstrap.settings, name, value)
    monkeypatch.setattr(bootstrap, "_CACHE_DIR", tmp_path / "cache" / "juicefs")
    monkeypatch.setattr(bootstrap, "_ENCRYPTION_KEY_FILE", tmp_path / "etc" / "jfs-master.pem")
    return mount


@pytest.fixture(autouse=True)
def _clean_thread_state() -> Iterator[None]:
    """The bootstrap thread handle is module state; leaking it across tests
    would make the "spawns exactly one thread" assertions depend on ordering."""
    bootstrap._bootstrap_thread = None
    yield
    thread = bootstrap._bootstrap_thread
    bootstrap._bootstrap_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)


# ── _classify: which failures are allowed to stop the retry loop ─────


@pytest.mark.parametrize(
    "stderr",
    [
        "FATAL: password authentication failed for user gaia",
        "AccessDenied: invalid access key id",
        "SignatureDoesNotMatch",
        "the specified bucket does not exist",
        "x509: certificate is not valid for meta.example.com",
    ],
)
def test_an_explicit_misconfiguration_is_classified_fatal(stderr: str) -> None:
    # These make bootstrap give up. Downgrading one to "transient" burns 20
    # attempts x 15s of backoff on a failure that can never succeed.
    assert _classify(stderr) == "fatal"


@pytest.mark.parametrize(
    "stderr",
    [
        "dial tcp: lookup meta.example.com: no such host",
        "server misbehaving",
        "dial tcp 10.0.0.1:5432: i/o timeout",
        "SIGSEGV: segmentation violation\ngoroutine 1 [running]:",
        "",
    ],
)
def test_a_flaky_or_opaque_failure_is_classified_transient(stderr: str) -> None:
    # Docker's embedded resolver and serverless Postgres cold-starts produce
    # exactly these. Calling them fatal means one DNS blip at boot leaves every
    # user's workspace unmounted until someone redeploys.
    assert _classify(stderr) == "transient"


def test_marker_matching_ignores_case_so_a_capitalized_error_still_stops_the_loop() -> None:
    # juicefs/pgx capitalize inconsistently ("Permission denied", "FATAL:").
    assert _classify("FATAL: Permission Denied while opening bucket") == "fatal"


# ── _meta_err_tail: keeping the diagnosable part of stderr ───────────


def test_the_error_tail_drops_the_banner_and_keeps_the_fatal_line() -> None:
    # Head-truncating stderr ([:300]) keeps the masked meta URL banner and drops
    # the only line that says why the mount failed.
    stderr = (
        "2026/07/30 juicefs[1] <INFO>: Meta address: postgres://gaia:***@meta.example.com/jfs\n"
        "2026/07/30 juicefs[1] <FATAL>: unable to connect to meta:\n"
        '  dial tcp 10.0.0.1:5432: connect: connection refused"'
    )
    tail = _meta_err_tail(stderr)
    assert "Meta address" not in tail
    assert "connection refused" in tail


def test_the_error_tail_keeps_continuation_lines_below_the_fatal_header() -> None:
    # pgx wraps the real cause on the line *after* "<FATAL>:"; a single-line grab
    # clips the message at the trailing colon and reports nothing actionable.
    stderr = "<FATAL>: meta connect failed:\n  too many connections for role gaia"
    assert "too many connections for role gaia" in _meta_err_tail(stderr)


def test_the_error_tail_starts_at_the_last_failure_marker_not_the_first() -> None:
    stderr = "<ERROR>: retrying format\nnoise\n<FATAL>: giving up: bucket unreachable"
    tail = _meta_err_tail(stderr)
    assert tail.startswith("<FATAL>")
    assert "retrying format" not in tail


def test_stderr_with_no_failure_marker_falls_back_to_its_tail_not_its_head() -> None:
    stderr = "banner\n" + "x" * 600 + "\nthe actual cause"
    tail = _meta_err_tail(stderr)
    assert tail.endswith("the actual cause")
    assert len(tail) <= 500


@pytest.mark.parametrize("stderr", ["", "   \n  "])
def test_blank_stderr_produces_no_detail_field(stderr: str) -> None:
    assert _meta_err_tail(stderr) == ""


# ── _missing_settings / _meta_url / _mask_meta ───────────────────────


def test_a_blank_credential_counts_as_missing_rather_than_configured(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Env-injected secrets arrive as "" far more often than as None. An
    # `is None` check here lets bootstrap format a volume with an empty key.
    monkeypatch.setattr(bootstrap.settings, "R2_SECRET_KEY", "")
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_META_URL_TEMPLATE", None)
    assert _missing_settings() == ["R2_SECRET_KEY", "JUICEFS_META_URL_TEMPLATE"]


def test_a_fully_configured_environment_reports_nothing_missing(cfg: Path) -> None:
    assert _missing_settings() == []


def test_the_shard_placeholder_is_substituted_into_the_meta_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_META_URL_TEMPLATE", "postgres://h/jfs_{shard}")
    assert _meta_url(3) == "postgres://h/jfs_3"
    assert _meta_url() == "postgres://h/jfs_0"


def test_a_postgresql_scheme_is_rewritten_because_juicefs_rejects_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Neon/Supabase hand out `postgresql://`. JuiceFS only accepts `postgres://`
    # and fails the format outright — which classifies as transient and burns
    # every retry.
    monkeypatch.setattr(
        bootstrap.settings, "JUICEFS_META_URL_TEMPLATE", "postgresql://u:p@h/db?sslmode=require"
    )
    assert _meta_url() == "postgres://u:p@h/db?sslmode=require"


def test_the_scheme_rewrite_only_applies_to_the_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A database literally named `postgresql_meta` must survive untouched.
    monkeypatch.setattr(
        bootstrap.settings, "JUICEFS_META_URL_TEMPLATE", "postgres://u:p@h/postgresql_meta"
    )
    assert _meta_url() == "postgres://u:p@h/postgresql_meta"


def test_the_masked_meta_url_never_carries_the_password_into_logs(cfg: Path) -> None:
    # This string is logged on every transient failure; the raw URL contains the
    # production Postgres password.
    masked = _mask_meta(META)
    assert "secret" not in masked
    assert "gaia:" not in masked
    assert masked == "meta.example.com:5432/jfs"


def test_the_masked_meta_url_drops_query_parameters() -> None:
    # Connection strings smuggle credentials in the query string too
    # (`?password=`, `?sslkey=`).
    assert _mask_meta("postgres://u:p@h/db?password=hunter2") == "h/db"


# ── _mount_state: what a stat on the mountpoint means ────────────────


def test_a_missing_mountpoint_is_absent(tmp_path: Path) -> None:
    assert _mount_state(tmp_path / "nope") == "absent"


def test_a_path_under_a_regular_file_is_absent(tmp_path: Path) -> None:
    # ENOTDIR, not ENOENT — the classifier must handle both or bootstrap
    # crashes instead of recreating the tree.
    (tmp_path / "afile").write_text("x")
    assert _mount_state(tmp_path / "afile" / "jfs") == "absent"


def test_an_existing_directory_is_present(tmp_path: Path) -> None:
    assert _mount_state(tmp_path) == "present"


def test_a_disconnected_fuse_endpoint_is_broken_rather_than_absent() -> None:
    # "Transport endpoint is not connected" raises ENOTCONN, which Path.exists()
    # does not swallow. Misreading it as "absent" skips the lazy-unmount and the
    # remount fights a stale endpoint forever.
    assert _mount_state(cast(Path, StatRaiser(errno.ENOTCONN))) == "broken"


def test_an_unexpected_stat_error_propagates_instead_of_reading_as_not_mounted() -> None:
    # Broadening the except to a catch-all would make an EACCES on /mnt/jfs look
    # like "nothing mounted here" and trigger a remount over a live mount.
    with pytest.raises(OSError):
        _mount_state(cast(Path, StatRaiser(errno.EACCES)))


# ── _is_mounted ──────────────────────────────────────────────────────


def test_a_nonexistent_path_is_not_probed_with_the_mountpoint_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Dropping the state guard sends every boot through a subprocess spawn on a
    # path that provably cannot be a mount.
    def must_not_run(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("mountpoint must not be spawned for a missing path")

    monkeypatch.setattr(bootstrap.subprocess, "run", must_not_run)
    assert _is_mounted(tmp_path / "nope") is False


def test_a_successful_mountpoint_probe_reports_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *_a, **_k: completed(returncode=0))
    assert _is_mounted(tmp_path) is True


def test_a_nonzero_mountpoint_probe_reports_not_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *_a, **_k: completed(returncode=1))
    assert _is_mounted(tmp_path) is False


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError("no mountpoint"), subprocess.TimeoutExpired(cmd="mountpoint", timeout=5)],
    ids=["binary missing", "probe hung"],
)
def test_the_fallback_still_recognizes_a_real_mount_when_the_probe_is_unusable(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> None:
    # macOS has no `mountpoint(1)`. If the fallback were dropped (or returned a
    # blanket False), a healthy mount would be reported unmounted and bootstrap
    # would lazy-unmount and remount it on every start.
    def boom(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise exc

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    assert _is_mounted(Path("/")) is True


def test_the_fallback_reports_a_plain_directory_as_not_mounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("no mountpoint")

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    assert _is_mounted(tmp_path) is False


# ── _materialize_encryption_key ──────────────────────────────────────


@pytest.mark.parametrize("pem", [None, "", "   \n  "])
def test_a_blank_encryption_key_writes_no_file_and_yields_no_path(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, pem: str | None
) -> None:
    # A whitespace-only env var must not produce a 0-byte PEM that then gets
    # handed to `juicefs format --encrypt-rsa-key`, corrupting the volume config.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", pem)
    assert _materialize_encryption_key() is None
    assert not bootstrap._ENCRYPTION_KEY_FILE.exists()


def test_the_key_file_is_written_newline_terminated_and_owner_only(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PEM parsers reject a file without a trailing newline; a world-readable
    # master key on a shared host is a credential leak.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "-----BEGIN KEY-----\nabc")
    path = _materialize_encryption_key()
    assert path is not None
    assert path.read_text() == "-----BEGIN KEY-----\nabc\n"
    assert path.stat().st_mode & 0o777 == 0o600


def test_materializing_the_key_twice_leaves_exactly_one_trailing_newline(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bootstrap re-runs on every retry attempt. Appending on each pass (or
    # writing in append mode) grows the PEM until juicefs cannot parse it.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    first = _materialize_encryption_key()
    second = _materialize_encryption_key()
    assert first == second
    assert second is not None
    assert second.read_text() == "KEYDATA\n"
    assert second.stat().st_mode & 0o777 == 0o600


def test_an_unwritable_key_directory_falls_back_to_a_locked_down_temp_file(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # /etc/gaia is root-owned in some deployments. Without the fallback the
    # OSError escapes and every bootstrap attempt dies before it ever mounts.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr(bootstrap, "_ENCRYPTION_KEY_FILE", blocker / "gaia" / "jfs.pem")
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")

    path = _materialize_encryption_key()
    assert path is not None
    assert path.read_text() == "KEYDATA\n"
    assert path.stat().st_mode & 0o777 == 0o600
    path.unlink()


# ── _format_if_needed: the destructive path ──────────────────────────


def test_an_already_formatted_volume_is_never_reformatted(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # `juicefs status` succeeding means the volume holds live user data.
    # Re-running format against it rewrites the volume config for everyone.
    runs.replies["juicefs status"] = completed(returncode=0)
    assert _format_if_needed(META, None) == "ok"
    assert runs.count("juicefs format") == 0


def test_a_permanent_status_error_stops_before_attempting_a_format(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # Bad credentials mean we cannot tell whether the volume exists. Formatting
    # anyway is how a configured volume gets clobbered.
    runs.replies["juicefs status"] = completed(1, "FATAL: password authentication failed")
    assert _format_if_needed(META, None) == "fatal"
    assert runs.count("juicefs format") == 0


def test_a_transient_status_failure_still_attempts_the_format(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # An uninitialized volume reports non-zero status with no permanent marker;
    # treating that as fatal means a fresh deployment never formats at all.
    runs.replies["juicefs status"] = completed(1, "database is not formatted")
    assert _format_if_needed(META, None) == "ok"
    assert runs.count("juicefs format") == 1


@pytest.mark.parametrize(
    "stderr",
    [
        "the volume is not empty",
        "volume gaia-0 already exists",
        "Database already formatted, please use `config`",
    ],
)
def test_a_volume_formatted_by_a_peer_container_is_treated_as_usable(
    cfg: Path, clock: Clock, runs: RunRecorder, stderr: str
) -> None:
    # Every replica boots this concurrently. If a losing racer reported failure,
    # its retry loop would spin and that pod would never mount.
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, stderr)
    assert _format_if_needed(META, None) == "ok"


def test_a_permission_error_during_format_is_fatal_not_retried(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "AccessDenied: invalid access key")
    assert _format_if_needed(META, None) == "fatal"


def test_an_unrecognized_format_failure_is_retried_rather_than_abandoned(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "dial tcp: i/o timeout")
    assert _format_if_needed(META, None) == "transient"


def test_the_format_command_carries_the_r2_bucket_and_credentials(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # JuiceFS otherwise falls through to EC2 IMDS against a non-AWS endpoint and
    # hangs until the format timeout.
    runs.replies["juicefs status"] = completed(1, "not formatted")
    _format_if_needed(META, None)
    argv = runs.argv("juicefs format")
    assert flag_value(argv, "--bucket") == (
        "https://acct123.r2.cloudflarestorage.com/gaia-workspaces"
    )
    assert flag_value(argv, "--access-key") == "AKIAEXAMPLE"
    assert flag_value(argv, "--secret-key") == "s3cr3t"
    assert flag_value(argv, "--storage") == "s3"


def test_the_meta_url_and_volume_name_are_the_last_two_positional_arguments(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # Swapping these makes juicefs treat the connection string as the volume
    # name and create a bogus volume.
    runs.replies["juicefs status"] = completed(1, "not formatted")
    _format_if_needed(META, None)
    assert runs.argv("juicefs format")[-2:] == [META, "gaia-0"]


def test_the_encryption_key_flag_is_omitted_when_no_key_exists(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    _format_if_needed(META, None)
    assert "--encrypt-rsa-key" not in runs.argv("juicefs format")


def test_the_encryption_key_flag_precedes_the_positional_arguments(
    cfg: Path, clock: Clock, runs: RunRecorder, tmp_path: Path
) -> None:
    # Appending it after the positionals would make juicefs read the flag as a
    # third positional and format an unencrypted volume.
    runs.replies["juicefs status"] = completed(1, "not formatted")
    key = tmp_path / "k.pem"
    _format_if_needed(META, key)
    argv = runs.argv("juicefs format")
    assert flag_value(argv, "--encrypt-rsa-key") == str(key)
    assert argv.index("--encrypt-rsa-key") < argv.index(META)


# ── _mount: the other destructive path ───────────────────────────────


def test_a_healthy_mount_is_left_completely_alone(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Losing this guard means every restart runs `fusermount -u -z` against a
    # live mount and yanks the filesystem out from under running sandboxes.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: True)
    assert _mount(META, cfg) == "ok"
    assert runs.calls == []


def test_a_missing_mountpoint_is_not_lazily_unmounted(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # fusermount against a path that does not exist is a pointless subprocess on
    # the startup critical path; the state guard exists to skip it.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    assert _mount(META, cfg) == "ok"
    assert runs.count("fusermount -u") == 0


def test_a_stale_mountpoint_directory_is_lazily_unmounted_before_remounting(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A leftover directory from a prior container run makes juicefs attempt a
    # normal umount that blocks ~3s and then fails the whole mount.
    cfg.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    assert _mount(META, cfg) == "ok"
    assert runs.argv("fusermount -u") == ["fusermount", "-u", "-z", str(cfg)]


def test_mounting_creates_the_mountpoint_and_the_cache_directory(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both parents are missing on a fresh container. Without parents=True the
    # mount fails with ENOENT and every retry repeats it.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    _mount(META, cfg)
    assert cfg.is_dir()
    assert bootstrap._CACHE_DIR.is_dir()


def test_the_mount_command_does_not_pass_r2_credential_flags(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `juicefs mount` has no --access-key/--secret-key; passing them aborts the
    # mount on an unknown-flag error. Credentials come from the meta DB.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    _mount(META, cfg)
    argv = runs.argv("juicefs mount")
    assert "--access-key" not in argv
    assert "--secret-key" not in argv
    assert "--background" in argv
    assert argv[-2:] == [META, str(cfg)]


def test_a_mount_that_appears_after_several_polls_is_reported_ready(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # juicefs' own supervisor exits non-zero while the detached child is still
    # initializing; trusting that exit code reports a working mount as failed.
    runs.replies["juicefs mount"] = completed(returncode=1, stderr="mountpoint not ready in 10s")
    # call 1 is _mount's own pre-check, calls 2-4 are polls, call 5 succeeds.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(4))
    assert _mount(META, cfg) == "ok"
    assert clock.slept == [1, 1, 1]


def test_the_readiness_poll_honours_the_configured_window(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_MOUNT_READY_TIMEOUT", 40)
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    assert _mount(META, cfg) == "transient"
    assert sum(clock.slept) == 40


def test_the_readiness_poll_never_drops_below_the_fifteen_second_floor(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A misconfigured (or zero) timeout would otherwise skip the poll entirely
    # and report every cold mount as failed.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_MOUNT_READY_TIMEOUT", 0)
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    assert _mount(META, cfg) == "transient"
    assert sum(clock.slept) == 15


def test_a_mount_that_never_appears_with_a_permanent_error_gives_up(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs.replies["juicefs mount"] = completed(1, "<FATAL>: permission denied opening /dev/fuse")
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    assert _mount(META, cfg) == "fatal"


def test_a_mount_that_never_appears_with_an_opaque_error_is_retried(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs.replies["juicefs mount"] = completed(1, "SIGSEGV: segmentation violation")
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    assert _mount(META, cfg) == "transient"


# ── _bootstrap_once: sequencing ──────────────────────────────────────


def test_a_healthy_mount_short_circuits_before_status_format_or_key_write(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the restart path. Reaching `juicefs format` here on a live volume
    # is the worst-case outcome of a broken idempotency guard.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: True)
    assert _bootstrap_once() == "ok"
    assert runs.calls == []
    assert not bootstrap._ENCRYPTION_KEY_FILE.exists()


def test_a_fatal_format_never_proceeds_to_mount(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    runs.replies["juicefs status"] = completed(1, "password authentication failed")
    assert _bootstrap_once() == "fatal"
    assert runs.count("juicefs mount") == 0


def test_a_transient_format_never_proceeds_to_mount(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mounting an unformatted volume leaves a wedged FUSE endpoint behind that
    # the next attempt then has to clean up.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "dial tcp: i/o timeout")
    assert _bootstrap_once() == "transient"
    assert runs.count("juicefs mount") == 0


def test_a_full_cold_start_formats_then_mounts(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(2))
    runs.replies["juicefs status"] = completed(1, "not formatted")
    assert _bootstrap_once() == "ok"
    assert [" ".join(c[:2]) for c in runs.calls] == [
        "juicefs status",
        "juicefs format",
        "juicefs mount",
    ]


# ── _bootstrap_loop: retry supervision ───────────────────────────────


@pytest.mark.parametrize("result", ["ok", "skip", "fatal"])
def test_a_terminal_result_stops_after_a_single_attempt(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    # Retrying a fatal misconfiguration burns 20 attempts of backoff for
    # nothing; retrying an "ok" would remount a healthy filesystem.
    attempts: list[int] = []

    def once() -> str:
        attempts.append(1)
        return result

    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", once)
    _bootstrap_loop()
    assert len(attempts) == 1
    assert clock.slept == []


def test_a_transient_failure_is_retried_up_to_the_configured_attempt_budget(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[int] = []
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 4)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: (attempts.append(1), "transient")[1])
    _bootstrap_loop()
    assert len(attempts) == 4


def test_no_backoff_is_slept_after_the_final_attempt(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sleeping past the last attempt keeps a daemon thread parked for 15s doing
    # nothing after it has already given up.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_RETRY_BACKOFF", 2)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: "transient")
    _bootstrap_loop()
    assert clock.slept == [2, 4]


def test_the_backoff_grows_exponentially_and_is_capped_at_fifteen_seconds(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Uncapped doubling from a base of 4 reaches 64s by attempt 5, so a mount
    # that would have converged sits unavailable for minutes.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 6)
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_RETRY_BACKOFF", 4)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: "transient")
    _bootstrap_loop()
    assert clock.slept == [4, 8, 15, 15, 15]


def test_a_zero_attempt_budget_still_makes_one_attempt(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An unset/zero env var must not silently disable the mount entirely.
    attempts: list[int] = []
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 0)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: (attempts.append(1), "transient")[1])
    _bootstrap_loop()
    assert len(attempts) == 1


def test_a_zero_backoff_setting_still_yields_a_nonzero_delay(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Backoff of 0 turns the retry loop into a hot spin against the meta DB.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_RETRY_BACKOFF", 0)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: "transient")
    _bootstrap_loop()
    assert clock.slept == [1, 2]


def test_an_exception_mid_attempt_is_absorbed_and_retried(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The loop runs in a daemon thread with no one to catch for it; an escaping
    # exception kills the thread and the mount never converges.
    attempts: list[int] = []

    def once() -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("meta socket closed")
        return "ok"

    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", once)
    _bootstrap_loop()
    assert len(attempts) == 2


def test_a_regular_file_squatting_the_mountpoint_does_not_kill_the_supervisor(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # mkdir(exist_ok=True) re-raises FileExistsError when a *file* occupies the
    # path. That escapes _mount and must be absorbed by the supervisor rather
    # than taking the daemon thread down silently.
    cfg.parent.mkdir(parents=True)
    cfg.write_text("stale file where the mount belongs")
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    _bootstrap_loop()
    assert clock.slept == [1]


# ── init_juicefs_mount: the provider entry point ─────────────────────


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[threading.Event]]:
    """Replace the loop body with a blocking stub so thread identity is testable."""
    gates: list[threading.Event] = []

    def loop() -> None:
        gate = threading.Event()
        gates.append(gate)
        gate.wait(timeout=5)

    monkeypatch.setattr(bootstrap, "_bootstrap_loop", loop)
    yield gates
    for gate in gates:
        gate.set()


@pytest.fixture
def juicefs_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _n: "/usr/local/bin/juicefs")


async def test_a_missing_juicefs_binary_skips_the_bootstrap_entirely(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, spawned: list[threading.Event]
) -> None:
    # Native dev runs have no juicefs; spawning a thread that shells out to a
    # nonexistent binary 20 times is pure noise in every local log.
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _n: None)
    assert await _init_juicefs_mount()() == str(cfg)
    assert bootstrap._bootstrap_thread is None


async def test_incomplete_r2_configuration_skips_the_bootstrap(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # Without this, format runs with an empty bucket URL against R2.
    monkeypatch.setattr(bootstrap.settings, "R2_BUCKET", None)
    assert await _init_juicefs_mount()() == str(cfg)
    assert bootstrap._bootstrap_thread is None


async def test_an_already_healthy_mount_spawns_no_bootstrap_thread(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: True)
    assert await _init_juicefs_mount()() == str(cfg)
    assert bootstrap._bootstrap_thread is None


async def test_an_unmounted_path_spawns_one_detached_daemon_thread(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # A non-daemon thread would block interpreter shutdown for the whole
    # backoff window on every restart.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    await _init_juicefs_mount()()
    thread = bootstrap._bootstrap_thread
    assert thread is not None
    assert thread.daemon is True
    assert thread.name == "juicefs-bootstrap"


async def test_a_second_provider_call_does_not_start_a_second_bootstrap_thread(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # API and worker both resolve this provider. Two concurrent supervisors race
    # on the same mountpoint — one lazy-unmounts what the other just mounted.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    init = _init_juicefs_mount()
    await init()
    first = bootstrap._bootstrap_thread
    await init()
    assert bootstrap._bootstrap_thread is first
    assert len(spawned) == 1


async def test_bootstrap_restarts_once_the_previous_supervisor_has_finished(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The alive check must not degrade into "ever started". A supervisor that
    # exhausted its attempts leaves the mount down; the next provider
    # resolution is the only thing that retries.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    monkeypatch.setattr(bootstrap, "_bootstrap_loop", lambda: None)
    init = _init_juicefs_mount()
    await init()
    first = bootstrap._bootstrap_thread
    assert first is not None
    first.join(timeout=5)
    await init()
    assert bootstrap._bootstrap_thread is not first


@pytest.mark.slow
async def test_an_unresponsive_mount_probe_still_starts_the_bootstrap(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # A wedged FUSE mount makes stat block forever. Before the timeout was
    # added this froze the ARQ worker before it consumed a single job — so the
    # probe must time out AND still fall through to a remount, not return early.
    monkeypatch.setattr(bootstrap, "_MOUNT_PROBE_TIMEOUT_SECONDS", 0.05)

    def wedged(_path: Path) -> bool:
        # Block LONGER than the probe timeout (0.05s, set above) so the
        # wait_for fires while this thread is still wedged — simulating a
        # stat that never returns. 0.5s is enough; the loop joins this
        # thread at close, so a long sleep is pure teardown cost.
        real_time.sleep(0.5)
        return True

    monkeypatch.setattr(bootstrap, "_is_mounted", wedged)
    assert await _init_juicefs_mount()() == str(cfg)
    assert bootstrap._bootstrap_thread is not None


async def test_the_provider_returns_the_configured_mount_path(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # Callers resolve the workspace root from this return value; a hardcoded
    # "/mnt/jfs" would silently ignore JUICEFS_HOST_MOUNT_PATH.
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    assert await _init_juicefs_mount()() == str(cfg)
