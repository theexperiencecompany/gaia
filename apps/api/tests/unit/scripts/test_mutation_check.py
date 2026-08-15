"""The mutation gate's orchestrator (scripts/ci/mutation-check.sh).

The orchestrator decides which modules a shard mutates and whether the lane
goes red. Both answers are invisible from mutmut's own output, so a regression
here reads as a clean run rather than a broken one — the exact failure mode the
gate exists to prevent.

Driven as a real script against stubbed siblings: the harness copies
mutation-check.sh into a throwaway tree next to a fake ``mutation-matrix.sh``
(prints a chosen module list) and a fake ``mutation.sh`` (records its module
and exits how the test says). Nothing here runs mutmut.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "ci" / "mutation-check.sh"

# The orchestrator reaps its parallel jobs with `wait -n` (bash 4.3+), and
# macOS ships 3.2 as /bin/bash. The lane runs on ubuntu-latest, so skipping the
# file on such a machine loses nothing CI does not still prove.
_HAS_WAIT_N = (
    subprocess.run(["bash", "-c", "true & wait -n"], capture_output=True, check=False).returncode
    == 0
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        not _HAS_WAIT_N, reason="bash lacks `wait -n` (needs 4.3+; macOS ships 3.2)"
    ),
]


@pytest.fixture
def harness(tmp_path: Path):
    """Return a runner for mutation-check.sh over a stubbed module list."""
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    (tmp_path / "scripts" / "test").mkdir(parents=True)
    shutil.copy(CHECK_SCRIPT, tmp_path / "scripts" / "ci" / "mutation-check.sh")
    ran = tmp_path / "ran.txt"

    def run(
        modules: list[str], *, failing: tuple[str, ...] = (), env: dict[str, str] | None = None
    ):
        matrix = [
            {"module": m, "testfiles": [f"tests/unit/test_{i}.py"], "changed_lines": [[1, 2]]}
            for i, m in enumerate(modules)
        ]
        (tmp_path / "scripts" / "ci" / "mutation-matrix.sh").write_text(
            f"#!/usr/bin/env bash\ncat <<'JSON'\n{json.dumps(matrix)}\nJSON\n"
        )
        # Records every module it was handed, then fails for the named ones.
        (tmp_path / "scripts" / "test" / "mutation.sh").write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$1" >> {ran}\n'
            f'case "$1" in {"|".join(failing) or "__none__"}) exit 1 ;; esac\n'
            "exit 0\n"
        )
        result = subprocess.run(
            ["bash", str(tmp_path / "scripts" / "ci" / "mutation-check.sh")],
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", **(env or {})},
        )
        recorded = ran.read_text().splitlines() if ran.exists() else []
        ran.unlink(missing_ok=True)
        return result, recorded

    return run


def modules_of(recorded: list[str]) -> list[str]:
    """Just the module paths from the stub's "<module> children=<n>" lines."""
    return [line.split(" ", 1)[0] for line in recorded]


class TestShardSelection:
    """MUTATION_SHARD / MUTATION_SHARDS slice the changed-module list."""

    def test_the_shards_together_cover_every_module_exactly_once(self, harness) -> None:
        modules = [f"app/m{i}.py" for i in range(10)]
        covered: list[str] = []
        for shard in range(1, 5):
            result, mutated = harness(
                modules, env={"MUTATION_SHARDS": "4", "MUTATION_SHARD": str(shard)}
            )
            assert result.returncode == 0, result.stderr
            covered += modules_of(mutated)

        assert sorted(covered) == sorted(modules)

    def test_neighbouring_modules_land_on_different_shards(self, harness) -> None:
        # Round-robin, not contiguous blocks: the matrix comes out grouped by
        # directory and a directory's modules share test files, so chunking
        # would pile the expensive ones onto one shard.
        #
        # Sorted, never the recorded order: a shard runs its modules
        # concurrently, so which one writes its line first is a race.
        _, mutated = harness(
            [f"app/m{i}.py" for i in range(10)],
            env={"MUTATION_SHARDS": "4", "MUTATION_SHARD": "1"},
        )

        assert sorted(modules_of(mutated)) == ["app/m0.py", "app/m4.py", "app/m8.py"]

    def test_unset_shard_vars_mutate_everything(self, harness) -> None:
        modules = [f"app/m{i}.py" for i in range(5)]
        result, mutated = harness(modules)

        assert result.returncode == 0, result.stderr
        assert sorted(modules_of(mutated)) == sorted(modules)

    def test_a_shard_outside_the_range_fails_loudly(self, harness) -> None:
        result, mutated = harness(
            ["app/m0.py"], env={"MUTATION_SHARDS": "4", "MUTATION_SHARD": "5"}
        )

        assert result.returncode != 0
        assert "not in 1..4" in result.stderr
        assert mutated == []

    def test_an_empty_shard_passes_without_mutating(self, harness) -> None:
        result, mutated = harness(
            ["app/m0.py"], env={"MUTATION_SHARDS": "4", "MUTATION_SHARD": "3"}
        )

        assert result.returncode == 0, result.stderr
        assert mutated == []


class TestFailurePropagation:
    """A surviving mutant has to reach the lane's exit code from ANY slot."""

    def test_a_failure_in_the_first_batch_fails_the_lane(self, harness) -> None:
        result, _ = harness([f"app/m{i}.py" for i in range(8)], failing=("app/m0.py",))

        assert result.returncode == 1

    def test_a_failure_in_the_trailing_batch_fails_the_lane(self, harness) -> None:
        # The regression: the loop reaped only while at capacity and drained
        # the rest with a bare `wait`, which bash documents as returning zero
        # no matter how its children exited. With parallelism 4, the last
        # module of a 6-module shard could survive a mutant and still report
        # green.
        result, mutated = harness([f"app/m{i}.py" for i in range(6)], failing=("app/m5.py",))

        assert len(mutated) == 6, "every module still runs"
        assert result.returncode == 1

    def test_a_clean_run_passes(self, harness) -> None:
        result, mutated = harness([f"app/m{i}.py" for i in range(6)])

        assert result.returncode == 0, result.stderr
        assert len(mutated) == 6

