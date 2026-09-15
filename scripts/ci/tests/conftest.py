"""Every harness test runs against a CPU-slot pool and a verdict dir of its own.

The scripts under test are the real lane scripts, and they reach for the job's
shared state through the environment:

* `lib/cpu-slots.sh` — `mutation.sh shard` and `pytest.sh slice` take nproc-2
  host tokens before their first real step. Run on the self-hosted box with
  the pool inherited, each sandboxed shard in this suite queued behind the
  real mutation shards for the semaphore's full 600 s fail-open wait, and the
  harness lane died at its cap with the last tests never reached (job
  103243166187) — invisible locally, where the governor is a no-op.
* `verdict.py emit` — resolves `$GAIA_VERDICT_DIR > $RUNNER_TEMP/verdicts`, and
  a runner always sets RUNNER_TEMP. A sandboxed shard that inherits it writes
  a verdict for a lane the harness job does not own into the job's real upload
  directory, and the ownership check fails the job (run 34595547568).

A private pool with room for any request keeps the semaphore code path live,
and a private verdict dir is the top rung so the real resolution still runs;
tests that prove the lower rungs strip it themselves.
"""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

# More than any lane requests (nproc-2 on the 16-core box), so a test only
# waits when it deliberately makes a smaller pool of its own.
PRIVATE_POOL_TOKENS = "64"


@pytest.fixture(autouse=True)
def _private_job_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GAIA_CPU_SLOTS_DIR", str(tmp_path / "cpu-slots"))
    monkeypatch.setenv("GAIA_CPU_TOKENS", PRIVATE_POOL_TOKENS)
    monkeypatch.setenv("GAIA_VERDICT_DIR", str(tmp_path / "verdicts"))


@pytest.fixture
def flock() -> str:
    """The semaphore's atomicity primitive. Absent on a stock macOS dev box,
    where acquire fails open before it touches any pool — so a proof that
    needs the pool to be used skips here and runs on every Linux runner."""
    path = shutil.which("flock")
    if path is None:
        pytest.skip("flock absent (governor is Linux-box-only)")
    return path
