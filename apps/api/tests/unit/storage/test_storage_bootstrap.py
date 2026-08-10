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

import asyncio
from collections.abc import Iterator
import errno
from pathlib import Path
import subprocess
import threading
import time as real_time
from typing import Any, cast

import pytest

from app.constants.log_tags import LogTag
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
        self.timeouts: list[int | None] = []
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
        self.timeouts.append(timeout)
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


class SeqClock(Clock):
    """Clock whose monotonic() follows a scripted sequence.

    The plain Clock never advances between two reads in the same second, so
    `-`/`/`/`*1001` duration mutations all compute 0.0 and are
    indistinguishable; a scripted sequence makes the two reads differ.
    """

    def __init__(self, sequence: list[float]) -> None:
        super().__init__()
        self._sequence = list(sequence)

    def monotonic(self) -> float:
        return self._sequence.pop(0) if self._sequence else self.now


class LogRecorder:
    """Record every log.info / log.warning call exactly as made.

    The bootstrap module binds contextual fields onto every line; a mutant
    that corrupts the message or one of those fields changes what operators
    see in prod but never changes the function's return value.
    """

    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict[str, Any]]] = []
        self.warning_calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, message: str, **kwargs: Any) -> None:
        self.info_calls.append((message, dict(kwargs)))

    def warning(self, message: str, **kwargs: Any) -> None:
        self.warning_calls.append((message, dict(kwargs)))


class OpRecorder:
    """Record record_fs_op calls so duration maths and outcome strings are pinned."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, op: str, **kwargs: Any) -> None:
        self.calls.append((op, dict(kwargs)))


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
def logs(monkeypatch: pytest.MonkeyPatch) -> LogRecorder:
    recorder = LogRecorder()
    monkeypatch.setattr(bootstrap, "log", recorder)
    return recorder


@pytest.fixture
def ops(monkeypatch: pytest.MonkeyPatch) -> OpRecorder:
    recorder = OpRecorder()
    monkeypatch.setattr(bootstrap, "record_fs_op", recorder)
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
    assert _meta_err_tail(stderr) == stderr


def test_the_error_tail_pins_an_error_only_marker_line() -> None:
    # <ERROR> lines (no <FATAL>) must still anchor the tail; a mutated marker
    # literal falls through to the last-500 fallback and loses the cause.
    stderr = "x" * 600 + "\n<ERROR>: giving up: connection refused"
    assert _meta_err_tail(stderr) == "<ERROR>: giving up: connection refused"


def test_the_error_tail_truncates_a_long_fatal_section_to_exactly_500() -> None:
    stderr = "<FATAL>: " + "x" * 600
    tail = _meta_err_tail(stderr)
    assert len(tail) == 500
    assert tail == stderr[-500:]


def test_the_error_tail_starts_at_the_last_failure_marker_not_the_first() -> None:
    stderr = "<ERROR>: retrying format\nnoise\n<FATAL>: giving up: bucket unreachable"
    tail = _meta_err_tail(stderr)
    assert tail.startswith("<FATAL>")
    assert "retrying format" not in tail


def test_stderr_with_no_failure_marker_falls_back_to_its_exact_tail() -> None:
    # The fallback must be the LAST 500 characters of the whole stream — a
    # 500-char window from the start (or only the last line) drops the cause.
    stderr = "banner\n" + "x" * 1200 + "\nthe actual cause"
    tail = _meta_err_tail(stderr)
    assert tail == stderr[-500:]
    assert len(tail) == 500


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


@pytest.mark.parametrize(
    ("attr", "expected"),
    [
        ("R2_ACCOUNT_ID", ["R2_ACCOUNT_ID"]),
        ("R2_BUCKET", ["R2_BUCKET"]),
        ("R2_ACCESS_KEY", ["R2_ACCESS_KEY"]),
    ],
)
def test_each_blank_credential_is_reported_by_its_exact_name(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, attr: str, expected: list[str]
) -> None:
    # The names are the settings' env var names — operators grep logs for
    # exactly those strings when diagnosing a skipped bootstrap.
    monkeypatch.setattr(bootstrap.settings, attr, "")
    assert _missing_settings() == expected


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


def test_an_unset_meta_template_yields_an_empty_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A placeholder fallback string ("XXXX") would be handed to `juicefs status`
    # as a live (and invalid) meta address instead of a missing one.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_META_URL_TEMPLATE", None)
    assert _meta_url() == ""


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


def test_a_url_with_two_at_signs_keeps_only_the_slice_after_the_first() -> None:
    # Passwords can contain "@"; splitting on every one (or from the right)
    # exposes the userinfo section in the logs.
    assert _mask_meta("postgres://u:p@h1@h2/db") == "h1@h2/db"


def test_the_query_split_happens_at_the_first_question_mark() -> None:
    # A query value containing "?" must not survive into the masked URL.
    assert _mask_meta("postgres://u:p@h/db?a=b?c=d") == "h/db"


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


def test_a_disconnected_fuse_endpoint_is_broken_rather_than_absent(
    logs: LogRecorder,
) -> None:
    # "Transport endpoint is not connected" raises ENOTCONN, which Path.exists()
    # does not swallow. Misreading it as "absent" skips the lazy-unmount and the
    # remount fights a stale endpoint forever.
    err = OSError(errno.ENOTCONN, "boom")
    assert _mount_state(cast(Path, StatRaiser(errno.ENOTCONN))) == "broken"
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} broken FUSE mountpoint detected",
            {"path": "/mnt/jfs", "errno": err.errno, "detail": str(err)},
        )
    ]


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


def test_the_mountpoint_probe_runs_with_the_exact_argv_and_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The probe must stay a fixed argv, no-shell call with a hard 5s cap — a
    # mutated binary name, quiet flag, or an unset timeout is invisible to the
    # boolean return value but breaks (or hangs) every boot.
    calls: list[tuple[Any, Any, Any]] = []

    def probe(
        argv: Any, *, check: Any, timeout: Any, **rest: Any
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, check, timeout))
        return completed(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", probe)
    assert _is_mounted(tmp_path) is True
    assert calls == [(["mountpoint", "-q", str(tmp_path)], False, 5)]


def test_the_fallback_reports_not_mounted_when_the_mountpoint_check_itself_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An is_mount() that errors (kernel refusing the stat) must still read as
    # "not mounted" — flipping that to True remounts over a live mount.
    def boom(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("no mountpoint")

    def broken_is_mount(_self: Any) -> bool:
        raise OSError("stat failed")

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    monkeypatch.setattr(bootstrap.Path, "is_mount", broken_is_mount)
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
    assert path == bootstrap._ENCRYPTION_KEY_FILE
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


def test_a_non_directory_key_parent_still_falls_back_to_a_temp_file(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The explicit is_dir() guard raises PermissionError — which is an OSError
    # subclass — so the same except clause swallows it and the fallback runs.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    monkeypatch.setattr(bootstrap.Path, "is_dir", lambda _self: False)
    path = _materialize_encryption_key()
    assert path is not None
    assert path.read_text() == "KEYDATA\n"


def test_the_fallback_key_file_uses_the_exact_mkstemp_template(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The fallback path must stay namespaced (jfs-master-*.pem) so a stray key
    # file is recognizable and traceable to this bootstrap.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr(bootstrap, "_ENCRYPTION_KEY_FILE", blocker / "gaia" / "jfs.pem")
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    seen: list[dict[str, str]] = []
    fallback = tmp_path / "fallback.pem"

    def fake_mkstemp(**kwargs: Any) -> tuple[int, str]:
        seen.append(dict(kwargs))
        return 7, str(fallback)

    monkeypatch.setattr(bootstrap.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(bootstrap.os, "close", lambda _fd: None)
    path = _materialize_encryption_key()
    assert path == fallback
    assert path is not None
    assert path.read_text() == "KEYDATA\n"
    assert seen == [{"prefix": "jfs-master-", "suffix": ".pem"}]


def test_a_key_that_already_ends_in_a_newline_is_not_doubled(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # PEM files end with a newline; appending another on a retry pass grows
    # the file until juicefs cannot parse it.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA\n")
    path = _materialize_encryption_key()
    assert path is not None
    assert path.read_text() == "KEYDATA\n"


def test_the_key_file_is_written_with_an_explicit_utf8_encoding(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # write_text defaults to the locale encoding; the explicit "utf-8" keeps the
    # PEM bytes identical on every host. Dropping the arg (or passing None / a
    # differently-cased alias) is invisible to the returned path, so pin the
    # exact call instead of the file contents.
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    calls: list[tuple[Path, str, dict[str, Any]]] = []
    original_write_text = Path.write_text

    def fake_write_text(self: Path, data: str, **kwargs: Any) -> None:
        calls.append((self, data, dict(kwargs)))
        original_write_text(self, data, **kwargs)

    monkeypatch.setattr(bootstrap.Path, "write_text", fake_write_text)
    path = _materialize_encryption_key()
    assert path is not None
    assert calls == [(path, "KEYDATA\n", {"encoding": "utf-8"})]


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


def test_the_status_probe_uses_the_exact_timeout_and_records_the_op(
    cfg: Path, clock: Clock, runs: RunRecorder, ops: OpRecorder
) -> None:
    runs.replies["juicefs status"] = completed(returncode=0)
    assert _format_if_needed(META, None) == "ok"
    assert runs.timeouts == [20]
    assert runs.envs == [None]
    assert ops.calls == [("juicefs_status", {"duration_ms": 0.0, "outcome": "ok"})]


def test_a_failed_status_probe_records_a_miss_outcome(
    cfg: Path, clock: Clock, runs: RunRecorder, ops: OpRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(returncode=0)
    assert _format_if_needed(META, None) == "ok"
    assert ops.calls == [
        ("juicefs_status", {"duration_ms": 0.0, "outcome": "miss"}),
        ("juicefs_format", {"duration_ms": 0.0, "outcome": "ok"}),
    ]


def test_the_op_durations_are_computed_in_milliseconds(
    cfg: Path, runs: RunRecorder, ops: OpRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq = SeqClock([1000.0, 1002.0, 1004.0, 1006.0])
    monkeypatch.setattr(bootstrap, "time", seq)
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(returncode=0)
    assert _format_if_needed(META, None) == "ok"
    assert ops.calls == [
        ("juicefs_status", {"duration_ms": 2000.0, "outcome": "miss"}),
        ("juicefs_format", {"duration_ms": 2000.0, "outcome": "ok"}),
    ]


def test_the_key_directory_is_created_recursively(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The key lives several levels deep (/etc/gaia/jfs-master.pem); a mkdir
    # without parents=True falls back to a temp file and the mount command
    # never reads the key that was written.
    deep = tmp_path / "a" / "b" / "c"
    monkeypatch.setattr(bootstrap, "_ENCRYPTION_KEY_FILE", deep / "jfs-master.pem")
    monkeypatch.setattr(bootstrap.settings, "JFS_ENCRYPTION_KEY", "KEYDATA")
    path = _materialize_encryption_key()
    assert path == bootstrap._ENCRYPTION_KEY_FILE
    assert path is not None
    assert path.read_text() == "KEYDATA\n"


def test_the_format_command_runs_with_the_exact_timeout_and_env(
    cfg: Path, clock: Clock, runs: RunRecorder
) -> None:
    # R2 credentials ride in the (empty, merged) env, never argv; the format
    # timeout must stay 120s so a slow cold meta does not die mid-format.
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(returncode=0)
    _format_if_needed(META, None)
    assert runs.timeouts == [20, 120]
    assert runs.envs == [None, {}]


def test_a_blank_access_key_is_passed_as_an_empty_flag_not_a_placeholder(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.settings, "R2_ACCESS_KEY", "")
    monkeypatch.setattr(bootstrap.settings, "R2_SECRET_KEY", "")
    runs.replies["juicefs status"] = completed(1, "not formatted")
    _format_if_needed(META, None)
    argv = runs.argv("juicefs format")
    assert flag_value(argv, "--access-key") == ""
    assert flag_value(argv, "--secret-key") == ""


def test_an_already_formatted_volume_logs_the_confirmation(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(returncode=0)
    _format_if_needed(META, None)
    assert logs.info_calls == [(f"{LogTag.STORAGE} filesystem already formatted", {})]


def test_the_format_attempt_logs_the_bucket_url(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(returncode=0)
    _format_if_needed(META, None)
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} formatting filesystem",
            {"bucket_url": "https://acct123.r2.cloudflarestorage.com/gaia-workspaces"},
        )
    ]


def test_the_peer_formatted_volume_logs_the_init_confirmation(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "the volume is not empty")
    assert _format_if_needed(META, None) == "ok"
    assert logs.info_calls[-1] == (
        f"{LogTag.STORAGE} volume already initialized; proceeding to mount",
        {},
    )


def test_the_permanent_status_failure_logs_the_masked_meta_and_diagnostic_tail(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(
        1, "FATAL: password authentication failed for user gaia"
    )
    assert _format_if_needed(META, None) == "fatal"
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} permanent error during status",
            {
                "meta": "meta.example.com:5432/jfs",
                "detail": "FATAL: password authentication failed for user gaia",
            },
        )
    ]


def test_the_permanent_format_failure_logs_the_masked_meta_and_tail(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "AccessDenied: invalid access key id")
    assert _format_if_needed(META, None) == "fatal"
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} permanent error during format",
            {
                "meta": "meta.example.com:5432/jfs",
                "detail": "AccessDenied: invalid access key id",
            },
        )
    ]


def test_the_transient_format_failure_logs_the_masked_meta_and_tail(
    cfg: Path, clock: Clock, runs: RunRecorder, logs: LogRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "dial tcp: i/o timeout")
    assert _format_if_needed(META, None) == "transient"
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} format failed (transient; will retry)",
            {
                "meta": "meta.example.com:5432/jfs",
                "detail": "dial tcp: i/o timeout",
            },
        )
    ]


def test_a_failed_format_records_a_fail_outcome(
    cfg: Path, clock: Clock, runs: RunRecorder, ops: OpRecorder
) -> None:
    runs.replies["juicefs status"] = completed(1, "not formatted")
    runs.replies["juicefs format"] = completed(1, "dial tcp: i/o timeout")
    assert _format_if_needed(META, None) == "transient"
    assert ops.calls[1] == ("juicefs_format", {"duration_ms": 0.0, "outcome": "fail"})


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
    assert runs.timeouts == [5, 40]


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


def test_an_already_mounted_path_logs_the_mount_path(
    cfg: Path, clock: Clock, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: True)
    assert _mount(META, cfg) == "ok"
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} already mounted at",
            {"mount_path": cfg},
        )
    ]


def test_the_mount_command_carries_the_full_flag_set(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cache/upload/buffer tuning is what keeps the FUSE mount stable at
    # startup; a mutated flag (or a missing one) silently runs with defaults.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    _mount(META, cfg)
    assert runs.argv("juicefs mount") == [
        "juicefs",
        "mount",
        "--background",
        "--backup-meta=0",
        f"--cache-dir={bootstrap._CACHE_DIR}",
        "--cache-size=4096",
        "--max-uploads=20",
        "--buffer-size=600",
        META,
        str(cfg),
    ]


def test_mounting_twice_tolerates_the_existing_cache_directory(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every retry re-runs _mount; exist_ok must survive the second pass or a
    # converged mount keeps throwing FileExistsError instead of mounting.
    cfg.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    assert _mount(META, cfg) == "ok"
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(1))
    assert _mount(META, cfg) == "ok"


def test_the_mount_supervisor_records_the_ok_op_with_exact_fields(
    cfg: Path,
    clock: Clock,
    runs: RunRecorder,
    ops: OpRecorder,
    logs: LogRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The poll runs for 99 virtual seconds so a `/1001`-style scale bug in the
    # elapsed computation no longer rounds to the same value.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_MOUNT_READY_TIMEOUT", 120)
    runs.replies["juicefs mount"] = completed(returncode=1, stderr="mountpoint not ready in 10s")
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(100))
    assert _mount(META, cfg) == "ok"
    assert ops.calls == [("juicefs_mount", {"duration_ms": 99000.0, "outcome": "ok"})]
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} mounted",
            {"mount": str(cfg), "elapsed_s": 99.0},
        )
    ]
    assert isinstance(logs.info_calls[0][1]["elapsed_s"], float)


def test_the_elapsed_seconds_are_rounded_to_one_decimal_place(
    cfg: Path,
    runs: RunRecorder,
    ops: OpRecorder,
    logs: LogRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The "mounted" line reports elapsed_s for operators judging slow mounts; a
    # poll that ends mid-second must keep the second decimal (a round-to-2
    # mutant is invisible at whole-second elapsed values, so force a fraction).
    class FracClock(Clock):
        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            self.now += 1.25

    monkeypatch.setattr(bootstrap, "time", FracClock())
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_MOUNT_READY_TIMEOUT", 200)
    runs.replies["juicefs mount"] = completed(returncode=1)
    # 99 failed polls x 1.25s = 123.75s: round(123.75, 1) == 123.8, but a
    # round(..., 2) mutant yields 123.75.
    monkeypatch.setattr(bootstrap, "_is_mounted", mounted_after(100))
    assert _mount(META, cfg) == "ok"
    assert ops.calls == [("juicefs_mount", {"duration_ms": 123750.0, "outcome": "ok"})]
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} mounted",
            {"mount": str(cfg), "elapsed_s": 123.8},
        )
    ]


def test_the_failed_mount_records_the_op_and_logs_the_exact_fields(
    cfg: Path,
    clock: Clock,
    runs: RunRecorder,
    ops: OpRecorder,
    logs: LogRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs.replies["juicefs mount"] = completed(1, "SIGSEGV: segmentation violation")
    seen: list[Path] = []

    def never(path: Path) -> bool:
        seen.append(path)
        return False

    monkeypatch.setattr(bootstrap, "_is_mounted", never)
    assert _mount(META, cfg) == "transient"
    assert seen == [cfg] * 16
    assert ops.calls == [("juicefs_mount", {"duration_ms": 15000.0, "outcome": "transient"})]
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} mount not ready within s",
            {
                "timeout": 15,
                "kind": "transient",
                "meta": "meta.example.com:5432/jfs",
                "detail": "SIGSEGV: segmentation violation",
            },
        )
    ]


def test_the_failure_classification_uses_exactly_the_last_4000_characters_of_stderr(
    cfg: Path, clock: Clock, runs: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A permanent marker sitting exactly one char before the 4000-char window
    # must be cut off — the classification window is a policy boundary.
    stderr = "permission denied" + "x" * (4001 - len("permission denied"))
    assert len(stderr) == 4001
    runs.replies["juicefs mount"] = completed(1, stderr)
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


def test_a_healthy_mount_logs_the_mount_path(
    cfg: Path, clock: Clock, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path] = []

    def mounted(path: Path) -> bool:
        seen.append(path)
        return True

    monkeypatch.setattr(bootstrap, "_is_mounted", mounted)
    assert _bootstrap_once() == "ok"
    assert seen == [cfg]
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} mount already healthy at",
            {"mount_path": cfg},
        )
    ]


def test_bootstrap_once_passes_the_materialized_key_and_resolved_meta_url_down(
    cfg: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The encrypt key (never re-read from settings by the format path) and the
    # resolved shard URL are the two values the caller hands down; dropping
    # either silently formats an unencrypted volume or the wrong shard.
    seen: list[Path] = []
    key = cfg.parent / "key.pem"
    fmt_args: list[tuple[str, Path | None]] = []
    mount_args: list[tuple[str, Path]] = []

    def unmounted(path: Path) -> bool:
        seen.append(path)
        return False

    def fake_format(meta_url: str, encrypt_key: Path | None) -> str:
        fmt_args.append((meta_url, encrypt_key))
        return "ok"

    def fake_mount(meta_url: str, mount_path: Path) -> str:
        mount_args.append((meta_url, mount_path))
        return "ok"

    monkeypatch.setattr(bootstrap, "_is_mounted", unmounted)
    monkeypatch.setattr(bootstrap, "_materialize_encryption_key", lambda: key)
    monkeypatch.setattr(bootstrap, "_format_if_needed", fake_format)
    monkeypatch.setattr(bootstrap, "_mount", fake_mount)
    assert _bootstrap_once() == "ok"
    assert seen == [cfg]
    assert fmt_args == [(META, key)]
    assert mount_args == [(META, cfg)]


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


def test_the_supervisor_logs_the_exact_error_fields_when_an_attempt_errors(
    cfg: Path, clock: Clock, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 2)

    def once() -> str:
        raise OSError("meta socket closed")

    monkeypatch.setattr(bootstrap, "_bootstrap_once", once)
    _bootstrap_loop()
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} bootstrap attempt errored",
            {"error": "meta socket closed", "error_type": "OSError"},
        ),
        (
            f"{LogTag.STORAGE} bootstrap attempt errored",
            {"error": "meta socket closed", "error_type": "OSError"},
        ),
        (
            f"{LogTag.STORAGE} mount still unavailable after attempts; "
            "storage helpers will soft-fail (next app start retries)",
            {"attempts": 2},
        ),
    ]


def test_a_fatal_result_logs_the_exact_give_up_message(
    cfg: Path, clock: Clock, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The give-up line is what operators grep for when storage is down — a
    # mutated condition (result != "fatal") suppresses it entirely.
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: "fatal")
    _bootstrap_loop()
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} bootstrap gave up (non-transient failure); "
            "storage helpers will soft-fail until reconfigured",
            {},
        )
    ]


def test_transient_backoff_logs_the_attempt_and_delay_fields(
    cfg: Path, clock: Clock, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(bootstrap.settings, "JUICEFS_BOOTSTRAP_RETRY_BACKOFF", 2)
    monkeypatch.setattr(bootstrap, "_bootstrap_once", lambda: "transient")
    _bootstrap_loop()
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} transient mount failure; backing off",
            {"attempt": 1, "of": 3, "retry_in_s": 2},
        ),
        (
            f"{LogTag.STORAGE} transient mount failure; backing off",
            {"attempt": 2, "of": 3, "retry_in_s": 4},
        ),
    ]


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


async def test_the_probe_requests_the_exact_binary_name_and_logs_its_absence(
    cfg: Path, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A mutated probe name ("JUICEFS", "juicefsx") silently finds nothing and
    # the mount never starts, with no error anywhere.
    requested: list[str] = []

    def no_binary(name: str) -> None:
        requested.append(name)

    monkeypatch.setattr(bootstrap.shutil, "which", no_binary)
    assert await _init_juicefs_mount()() == str(cfg)
    assert requested == ["juicefs"]
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} CLI not found on PATH — skipping bootstrap",
            {},
        )
    ]


async def test_missing_settings_logs_the_exact_missing_names(
    cfg: Path, logs: LogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operators grep the skip line for the env var names to fix; the names
    # must be joined with ", " so the list is greppable as written.
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _n: "/usr/local/bin/juicefs")
    monkeypatch.setattr(bootstrap.settings, "R2_BUCKET", None)
    monkeypatch.setattr(bootstrap.settings, "R2_ACCESS_KEY", None)
    assert await _init_juicefs_mount()() == str(cfg)
    assert logs.info_calls == [
        (
            f"{LogTag.STORAGE} skipping bootstrap; missing settings: R2_BUCKET, R2_ACCESS_KEY",
            {},
        )
    ]


async def test_a_healthy_probe_logs_the_skip_with_the_exact_message(
    cfg: Path,
    logs: LogRecorder,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: True)
    assert await _init_juicefs_mount()() == str(cfg)
    assert logs.info_calls == [(f"{LogTag.STORAGE} mount already healthy", {})]


async def test_the_probe_runs_off_the_event_loop_with_the_exact_mount_path(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # The probe must pass the ACTUAL mount path off the loop — a mutated
    # argument probes /mnt/jfs while the configured path is somewhere else.
    calls: list[tuple[Any, tuple[Path, ...]]] = []

    async def fake_to_thread(func: Any, *args: Any) -> Any:
        calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(bootstrap.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    await _init_juicefs_mount()()
    assert calls[0][1] == (cfg,)


async def test_the_provider_probes_with_the_configured_mount_path(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A mutated probe argument (None) would check /mnt/jfs while the
    # configured path is elsewhere and the bootstrap never runs.
    args: list[Any] = []

    async def fake_needed(mount_path: Any) -> bool:
        args.append(mount_path)
        return False

    monkeypatch.setattr(bootstrap, "_bootstrap_needed", fake_needed)
    assert await _init_juicefs_mount()() == str(cfg)
    assert args == [cfg]
    assert bootstrap._bootstrap_thread is None


async def test_the_provider_yields_control_with_a_zero_sleep(
    cfg: Path,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # The sleep is a pure yield point so startup is never blocked; a nonzero
    # sleep parks the provider (and the startup path awaiting it) for real time.
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(bootstrap.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(bootstrap, "_is_mounted", lambda _p: False)
    await _init_juicefs_mount()()
    assert slept == [0.0]
    assert bootstrap._bootstrap_thread is not None


async def test_a_wedged_probe_logs_the_timeout_fields_and_still_starts_the_bootstrap(
    cfg: Path,
    logs: LogRecorder,
    juicefs_on_path: None,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[threading.Event],
) -> None:
    # A wedged FUSE stat must time out loudly (with the exact window in the
    # event) and still fall through to a remount, never hang startup.
    monkeypatch.setattr(bootstrap, "_MOUNT_PROBE_TIMEOUT_SECONDS", 0.05)

    async def forever(*_args: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(bootstrap.asyncio, "to_thread", forever)
    assert await _init_juicefs_mount()() == str(cfg)
    assert logs.warning_calls == [
        (
            f"{LogTag.STORAGE} mount probe timed out — mount likely unresponsive; (re)starting bootstrap",
            {"_mount_probe_timeout_seconds": 0.05},
        )
    ]
    assert bootstrap._bootstrap_thread is not None


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
