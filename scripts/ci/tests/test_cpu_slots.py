"""cpu-slots.sh: the host CPU semaphore never oversubscribes and never hangs.

These drive the REAL library (`scripts/ci/lib/cpu-slots.sh`) through a tiny bash
actor that sources it exactly as a lane does — never a reimplementation of the
counting logic. The atomicity primitive is `flock`, so the concurrency proofs
skip where it is absent (a stock macOS dev box); they run on every Linux runner,
which is the only environment the governor is ever live in
(`RUNNER_ENVIRONMENT=self-hosted`). The two fail-open guards that need no lock
run everywhere.

The core invariant under test is the one the whole feature rests on: at no
instant does the sum of live grants exceed the pool, no matter how many
acquirers pile on — and when everyone is done the pool is whole again.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import pytest

CI = Path(__file__).parent.parent
LIB = CI / "lib" / "cpu-slots.sh"
LOG = CI / "lib" / "log.sh"
MUTATION = CI / "mutation.sh"

HAVE_FLOCK = shutil.which("flock") is not None
needs_flock = pytest.mark.skipif(not HAVE_FLOCK, reason="flock absent (governor is Linux-box-only)")


def _run(script: str, env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess:
    full = {**os.environ, **env}
    return subprocess.run(
        ["bash", "-c", f"source {LOG}\nsource {LIB}\n{script}"],
        capture_output=True,
        text=True,
        env=full,
        timeout=timeout,
        check=False,
    )


def _base_env(slots_dir: Path, tokens: int) -> dict[str, str]:
    return {
        "RUNNER_ENVIRONMENT": "self-hosted",
        "GAIA_CPU_SLOTS_DIR": str(slots_dir),
        "GAIA_CPU_TOKENS": str(tokens),
    }


def _live_sum(holders: Path) -> int:
    total = 0
    for f in holders.glob("*"):
        try:
            total += int(f.read_text().strip())
        except (ValueError, OSError):
            # A file mid-write reads empty: undercount, never overcount — safe
            # for the "never exceeds TOTAL" assertion.
            continue
    return total


# ── fail-open guards (no lock needed, run everywhere) ───────────────────────


def test_failopen_when_not_self_hosted(tmp_path: Path) -> None:
    """With RUNNER_ENVIRONMENT unset, acquire takes nothing and succeeds (GitHub-hosted VMs)."""
    env = _base_env(tmp_path / "pool", 8)
    del env["RUNNER_ENVIRONMENT"]
    r = _run("cpu_slots_acquire 5 && echo OK", env)
    assert r.returncode == 0 and "OK" in r.stdout
    assert not (tmp_path / "pool" / "holders").exists() or not list(
        (tmp_path / "pool" / "holders").glob("*")
    )


def test_failopen_on_unwritable_dir(tmp_path: Path) -> None:
    """A pool dir that cannot be created → warn and proceed, never fail."""
    if not HAVE_FLOCK:
        # Without flock acquire fails open before it ever reaches the dir check;
        # still a no-op success, which is all the caller needs.
        pass
    env = _base_env(tmp_path / "pool", 8)
    # A path under a regular file cannot be mkdir'd.
    (tmp_path / "afile").write_text("x")
    env["GAIA_CPU_SLOTS_DIR"] = str(tmp_path / "afile" / "nope")
    r = _run("cpu_slots_acquire 5 && echo OK", env)
    assert r.returncode == 0 and "OK" in r.stdout
    assert "fail-open" in r.stderr


def test_zero_and_noninteger_are_noops(tmp_path: Path) -> None:
    env = _base_env(tmp_path / "pool", 8)
    r = _run('cpu_slots_acquire 0 && cpu_slots_acquire "" && cpu_slots_acquire abc && echo OK', env)
    assert r.returncode == 0 and "OK" in r.stdout


# ── the pool size (the default is the thing that gets tuned) ────────────────


def _nproc() -> int:
    return int(subprocess.run(["nproc"], capture_output=True, text=True, check=True).stdout)


@pytest.mark.skipif(shutil.which("nproc") is None, reason="nproc absent")
def test_pool_defaults_to_one_and_a_half_times_the_thread_count(tmp_path: Path) -> None:
    """The measured default: nproc * 3 / 2, room for three mutation shards.

    At exactly nproc a shard could not fit beside another one and the lane
    serialised; at 2 x nproc four shards thrashed the box.
    """
    # Emptied, not deleted: `_run` layers this over os.environ, where conftest's
    # autouse fixture has already put the suite's private pool — dropping the
    # key here leaves that one inherited and the default never runs. Empty is
    # not a uint, so cpu-slots takes exactly the branch under test.
    env = {**_base_env(tmp_path / "pool", 8), "GAIA_CPU_TOKENS": ""}
    r = _run("_cpu_slots_total", env)
    assert r.returncode == 0
    assert r.stdout.strip() == str(_nproc() * 3 // 2)


def test_an_explicit_pool_size_wins_over_the_default(tmp_path: Path) -> None:
    r = _run("_cpu_slots_total", _base_env(tmp_path / "pool", 5))
    assert r.returncode == 0 and r.stdout.strip() == "5"


# ── the mutation lane's weight in that pool ─────────────────────────────────
#
# The governor only works if each lane asks for what it really runs, so the
# shard's own arithmetic belongs with the pool's. Driven through the REAL
# `mutation.sh shard`, in a sandbox with no apps/api, so it prints its budget
# and then fails on the missing module — the budget line is the contract.


def _shard_budget(tmp_path: Path, env: dict[str, str]) -> tuple[int, int]:
    """Run `mutation.sh shard` in a sandbox and return (workers, tokens)."""
    scripts = tmp_path / "scripts" / "ci"
    (scripts / "lib").mkdir(parents=True)
    shutil.copy(MUTATION, scripts / "mutation.sh")
    shutil.copy(LOG, scripts / "lib" / "log.sh")
    shutil.copy(LIB, scripts / "lib" / "cpu-slots.sh")
    group = json.dumps([{"module": "app/nope.py", "testfiles": '["t.py"]', "ranges": "[[1,1]]"}])
    r = subprocess.run(
        ["bash", str(scripts / "mutation.sh"), "shard"],
        capture_output=True,
        text=True,
        env={**os.environ, **env, "GROUP": group, "SHARD_LOG": str(tmp_path / "shard.log")},
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    line = next(li for li in r.stdout.splitlines() if li.startswith("mutation shard: "))
    workers, tokens = (int(word) for word in line.split() if word.isdigit())
    return workers, tokens


@pytest.mark.skipif(shutil.which("nproc") is None, reason="nproc absent")
def test_a_shard_defaults_to_half_the_threads_and_takes_exactly_that(tmp_path: Path) -> None:
    """nproc/2 mutant workers, and the same number of host tokens.

    Taking more than it runs (the old nproc-2 floor) is what made two shards
    mutually exclusive in the pool; taking fewer would let it outrun its grant.
    """
    env = {**_base_env(tmp_path / "pool", 24), "MUTMUT_MAX_CHILDREN": ""}
    workers, tokens = _shard_budget(tmp_path, env)
    assert workers == max(_nproc() // 2, 1)
    assert tokens == workers


def test_a_smaller_explicit_worker_count_is_not_raised_back_up(tmp_path: Path) -> None:
    """An explicit MUTMUT_MAX_CHILDREN is honoured as given, in both numbers."""
    env = {**_base_env(tmp_path / "pool", 24), "MUTMUT_MAX_CHILDREN": "2"}
    assert _shard_budget(tmp_path, env) == (2, 2)


def test_a_larger_explicit_worker_count_takes_matching_tokens(tmp_path: Path) -> None:
    env = {**_base_env(tmp_path / "pool", 24), "MUTMUT_MAX_CHILDREN": "30"}
    assert _shard_budget(tmp_path, env) == (30, 30)


# ── the real semaphore (flock required) ─────────────────────────────────────

# One actor: acquire W, mark that it is holding, hold HOLD_MS, release. Run
# from a distinct working dir per actor so nothing but the lib coordinates them.
ACTOR = """\
cpu_slots_acquire "$W"
: > "$MARK"
sleep "$HOLD"
cpu_slots_release "$W"
rm -f "$MARK"
"""


@needs_flock
def test_never_oversubscribed_and_drains(tmp_path: Path) -> None:
    """Twelve acquirers of 3 tokens on a pool of 8 never hold more than 8, and leave it whole."""
    pool = tmp_path / "pool"
    holders = pool / "holders"
    tokens, want, actors, hold = 8, 3, 12, 1.0
    env = _base_env(pool, tokens)

    procs = []
    for _ in range(actors):
        e = {
            **os.environ,
            **env,
            "W": str(want),
            "HOLD": str(hold),
            "MARK": str(tmp_path / f"m{_}"),
        }
        procs.append(
            subprocess.Popen(
                ["bash", "-c", f"source {LOG}\nsource {LIB}\n{ACTOR}"],
                env=e,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    peak = 0
    deadline = time.time() + 40
    while any(p.poll() is None for p in procs) and time.time() < deadline:
        peak = max(peak, _live_sum(holders))
        assert _live_sum(holders) <= tokens, f"OVERSUBSCRIBED: {_live_sum(holders)} > {tokens}"
        time.sleep(0.01)

    for p in procs:
        p.wait(timeout=40)

    # The pool actually filled (proves the actors really contended, not just ran
    # one at a time by luck) and then drained completely.
    assert peak >= tokens - want + 1, f"pool never filled: peak={peak}"
    assert _live_sum(holders) == 0, "tokens leaked — pool did not drain to TOTAL"
    assert not list(holders.glob("*"))


@needs_flock
def test_dead_holder_is_reclaimed(tmp_path: Path) -> None:
    """Reclaim a SIGKILL'd holder's tokens, which its skipped EXIT trap would otherwise leak."""
    pool = tmp_path / "pool"
    holders = pool / "holders"
    tokens, want = 8, 8
    env = _base_env(pool, tokens)

    # Actor takes the whole pool and blocks forever.
    e = {**os.environ, **env, "W": str(want), "HOLD": "600", "MARK": str(tmp_path / "m")}
    hog = subprocess.Popen(
        ["bash", "-c", f"source {LOG}\nsource {LIB}\n{ACTOR}"],
        env=e,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait until it is actually holding.
    for _ in range(500):
        if (tmp_path / "m").exists():
            break
        time.sleep(0.01)
    assert _live_sum(holders) == tokens

    # SIGKILL: no trap runs, the holder file is orphaned.
    hog.kill()
    hog.wait(timeout=10)
    assert _live_sum(holders) == tokens, "precondition: orphaned grant still on disk"

    # A fresh acquirer for the whole pool must succeed quickly by reclaiming it.
    r = _run(
        f"GAIA_CPU_SLOTS_TIMEOUT=30 cpu_slots_acquire {want} && echo GOT && cpu_slots_release {want}",
        env,
        timeout=40,
    )
    assert r.returncode == 0 and "GOT" in r.stdout
    assert _live_sum(holders) == 0


@needs_flock
def test_timeout_fails_open_with_warning(tmp_path: Path) -> None:
    """Proceed without tokens (warning, exit 0) after the timeout — the governor never hangs a gate."""
    pool = tmp_path / "pool"
    holders = pool / "holders"
    tokens = 8
    env = _base_env(pool, tokens)

    e = {**os.environ, **env, "W": str(tokens), "HOLD": "600", "MARK": str(tmp_path / "m")}
    hog = subprocess.Popen(
        ["bash", "-c", f"source {LOG}\nsource {LIB}\n{ACTOR}"],
        env=e,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(500):
            if (tmp_path / "m").exists():
                break
            time.sleep(0.01)
        assert _live_sum(holders) == tokens

        start = time.time()
        r = _run("GAIA_CPU_SLOTS_TIMEOUT=2 cpu_slots_acquire 4 && echo PROCEEDED", env, timeout=30)
        waited = time.time() - start
        assert r.returncode == 0 and "PROCEEDED" in r.stdout
        assert "fail-open" in r.stderr
        assert 2 <= waited < 20, f"did not wait its timeout before failing open: {waited:.1f}s"
        # It barged in WITHOUT taking tokens — the pool is not oversubscribed on disk.
        assert _live_sum(holders) == tokens
    finally:
        hog.kill()
        hog.wait(timeout=10)
