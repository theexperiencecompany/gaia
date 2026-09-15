"""`mutation.sh shard` refuses to run contract-mapped work without services.

The plan sends contract-mapped modules to the services pool, but nothing about
a runner guarantees the services are actually there — the composite can be
skipped, a lane can be rejected, a developer can run the shard by hand. Every
one of those ends the same way if the shard proceeds: the contract tier's
autouse fixture calls `pytest.skip`, mutmut sees no covering test, and the
mutants of the changed repository lines are reported as uncovered. That is
informational. It fails nothing. It is the false green the pool split exists to
remove, so the shard asserts its own preconditions rather than degrading.

The mirror case is just as bad and much less obvious: USE_REAL_SERVICES=1 on a
unit-only shard swaps tests/conftest.py's global mongodb mock for a real
client, so every mutant dies of a connection error and the shard passes having
proven nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[3]
MUTATION_SH = REPO_ROOT / "scripts" / "ci" / "mutation.sh"

# A port nothing listens on, so the reachability probe fails the way an absent
# service does rather than by name resolution.
DEAD_ENDPOINT = 1


def _group(testfile: str) -> str:
    return json.dumps(
        [
            {
                "module": "app/does_not_exist.py",
                "testfiles": json.dumps([testfile]),
                "ranges": "[[1,2]]",
            }
        ],
        separators=(",", ":"),
    )


def _shard(tmp_path: Path, testfile: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(MUTATION_SH), "shard"],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(tmp_path),
            "GROUP": _group(testfile),
            "SHARD_LOG": str(tmp_path / "shard.log"),
            # Without this the shard reports its deliberately bogus module into
            # the CHECKOUT's verdict tree, where the lane's upload composite
            # ships it and the quality gate reads it as a real failing lane:
            # `mutation/app/does_not_exist.py` reached the gate of run
            # 34586506166 from a fixture just like this one.
            "GAIA_VERDICT_DIR": str(tmp_path / "verdicts"),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def test_a_contract_shard_without_the_variable_stops(tmp_path: Path) -> None:
    process = _shard(tmp_path, "tests/contracts/test_repo.py")

    assert process.returncode != 0
    combined = process.stdout + process.stderr
    assert "USE_REAL_SERVICES" in combined
    # It stopped BEFORE mutating: the guard sits ahead of the log the shard
    # truncates on entry, so an absent log is the proof that no module ran. A
    # run that got as far as mutmut would have reported the uncovered mutants
    # this check exists to prevent.
    assert not (tmp_path / "shard.log").exists()


def test_a_contract_shard_with_unreachable_services_stops(tmp_path: Path) -> None:
    # The worse half of the same bug: with the variable set and nothing
    # listening, the contract tests ERROR on connect, and an erroring test
    # kills every mutant it touches — a clean shard that proved nothing.
    process = _shard(
        tmp_path,
        "tests/contracts/test_repo.py",
        USE_REAL_SERVICES="1",
        MONGO_DB=f"mongodb://localhost:{DEAD_ENDPOINT}/gaia_test",
        REDIS_URL=f"redis://localhost:{DEAD_ENDPOINT}/0",
    )

    assert process.returncode != 0
    assert "unreachable" in process.stdout + process.stderr


def test_a_contract_shard_says_which_endpoint_it_could_not_reach(tmp_path: Path) -> None:
    # Naming the endpoint is the difference between "services are down" and
    # "this lane's Mongo namespace was never published to the job".
    process = _shard(
        tmp_path,
        "tests/contracts/test_repo.py",
        USE_REAL_SERVICES="1",
        MONGO_DB=f"mongodb://localhost:{DEAD_ENDPOINT}/gaia_test",
        REDIS_URL=f"redis://localhost:{DEAD_ENDPOINT}/0",
    )

    assert "MONGO_DB" in process.stdout + process.stderr


def test_a_contract_shard_with_no_published_endpoints_stops(tmp_path: Path) -> None:
    # USE_REAL_SERVICES=1 with no URLs at all is what a shard sees when the
    # services step was skipped but the variable came from somewhere else.
    process = _shard(tmp_path, "tests/contracts/test_repo.py", USE_REAL_SERVICES="1")

    assert process.returncode != 0
    assert "unset" in process.stdout + process.stderr


def test_a_unit_only_shard_drops_an_inherited_services_flag(tmp_path: Path) -> None:
    # It must not stop — a unit-only shard is legitimate work — but it must not
    # carry the flag into mutmut either.
    process = _shard(tmp_path, "tests/unit/test_nope.py", USE_REAL_SERVICES="1")

    combined = process.stdout + process.stderr
    assert "unsetting USE_REAL_SERVICES" in combined
    assert "unreachable" not in combined
