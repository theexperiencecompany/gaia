"""Two worktrees never share a slot, so they never share a port, a database, a Redis or a vhost."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wt_env  # the path insert above must precede this import
from wt_env import ENV_FILE, RESERVED_PORTS, SLOT_COUNT, Allocation, allocate, preferred_slot

SCRIPT = Path(__file__).resolve().parents[1] / "wt_env.py"


def _env(path: Path) -> dict[str, str]:
    lines = (path / ENV_FILE).read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _hold(root: Path, slot: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ENV_FILE).write_text(f"GAIA_WT_SLOT={slot}\n")
    return root


def test_a_worktree_whose_hashed_slot_is_held_takes_the_next_free_one(tmp_path: Path) -> None:
    root = tmp_path / "mine"
    wanted = preferred_slot(root)
    holder = _hold(tmp_path / "other", wanted)

    slot = allocate(root, [holder])

    assert slot != wanted
    assert Allocation(slot).is_clear_of_reserved()


def test_a_worktree_keeps_its_slot_while_no_one_else_holds_it(tmp_path: Path) -> None:
    root = _hold(tmp_path / "mine", 42)
    assert allocate(root, [_hold(tmp_path / "other", 43)]) == 42


def test_a_slot_written_by_the_old_port_scheme_counts_as_held(tmp_path: Path) -> None:
    root = tmp_path / "mine"
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / ENV_FILE).write_text(f"API_PORT={8000 + preferred_slot(root) * 10}\n")
    assert allocate(root, [legacy]) != preferred_slot(root)


def test_allocation_refuses_when_every_slot_is_held(tmp_path: Path) -> None:
    holders = [_hold(tmp_path / str(slot), slot) for slot in range(1, SLOT_COUNT + 1)]
    with pytest.raises(SystemExit, match="slots are taken"):
        allocate(tmp_path / "mine", holders)


def test_no_two_usable_slots_share_a_port_and_none_takes_a_reserved_one() -> None:
    seen: dict[int, int] = {}
    for slot in range(1, SLOT_COUNT + 1):
        allocation = Allocation(slot)
        if not allocation.is_clear_of_reserved():
            continue
        for port in allocation.ports().values():
            assert port not in RESERVED_PORTS
            assert seen.setdefault(port, slot) == slot, (
                f"slots {seen[port]} and {slot} share {port}"
            )


def test_a_linked_slot_names_its_own_database_redis_and_vhost() -> None:
    lines = dict(
        line.split("=", 1) for line in Allocation(5).env_lines() if not line.startswith("#")
    )
    assert lines["MONGO_DB_NAME"] == "gaia_wt50"
    assert lines["REDIS_URL"] == f"redis://localhost:{lines['WT_REDIS_PORT']}/0"
    assert lines["RABBITMQ_URL"].endswith("/gaia_wt50")
    assert lines["ENV"] == "development"


def test_the_main_checkout_keeps_the_shared_defaults() -> None:
    lines = dict(
        line.split("=", 1) for line in Allocation(0).env_lines() if not line.startswith("#")
    )
    assert lines["API_PORT"] == "8000"
    assert lines["WEB_PORT"] == "3000"
    assert "MONGO_DB_NAME" not in lines
    assert "REDIS_URL" not in lines


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_two_linked_worktrees_that_hash_alike_get_different_slots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
        cwd=main,
    )
    a, b = tmp_path / "a", tmp_path / "b"
    _git("worktree", "add", "-q", "--detach", str(a), cwd=main)
    _git("worktree", "add", "-q", "--detach", str(b), cwd=main)
    # The real hash rarely collides on two paths; force it to, which is the case that bit us.
    monkeypatch.setattr(wt_env, "preferred_slot", lambda _root: 7)

    for root in (a, b, main):
        monkeypatch.chdir(root)
        wt_env.main([])

    env_a, env_b, env_main = _env(a), _env(b), _env(main)
    assert env_a["GAIA_WT_SLOT"] != env_b["GAIA_WT_SLOT"]
    assert env_a["API_PORT"] != env_b["API_PORT"]
    assert env_a["MONGO_DB_NAME"] != env_b["MONGO_DB_NAME"]
    assert env_a["REDIS_URL"] != env_b["REDIS_URL"]
    assert env_main["GAIA_WT_SLOT"] == "0"


def test_the_script_runs_standalone(tmp_path: Path) -> None:
    _git("init", "-q", cwd=tmp_path)
    subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, check=True, capture_output=True)
    assert _env(tmp_path)["API_PORT"] == "8000"


def test_default_ports_gives_a_linked_worktree_the_main_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git(
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
        cwd=main,
    )
    linked = tmp_path / "linked"
    _git("worktree", "add", "-q", "--detach", str(linked), cwd=main)
    monkeypatch.chdir(linked)

    wt_env.main(["--default-ports"])

    assert _env(linked)["API_PORT"] == "8000"
    assert _env(linked)["GAIA_WT_SLOT"] == "0"
