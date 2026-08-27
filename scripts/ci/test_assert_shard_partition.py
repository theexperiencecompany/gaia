"""The shard-partition guard, pinned against the failure it was written for:
six pytest-split shards that each shuffled collection with their own random
seed, so they overlapped and left a third of the suite unrun while every shard
reported green (run 32639649013).
"""

from pathlib import Path

from assert_shard_partition import main


def write_shard(path: Path, ids: list[tuple[str, str]]) -> str:
    cases = "".join(f'<testcase classname="{c}" name="{n}" />' for c, n in ids)
    path.write_text(f'<testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>')
    return str(path)


def test_disjoint_shards_pass(tmp_path: Path) -> None:
    shards = [
        write_shard(tmp_path / "pytest-1.xml", [("mod.TestA", "test_one")]),
        write_shard(tmp_path / "pytest-2.xml", [("mod.TestA", "test_two")]),
    ]
    assert main(shards) == 0


def test_a_test_running_in_two_shards_fails(tmp_path: Path) -> None:
    shared = ("mod.TestA", "test_one")
    shards = [
        write_shard(tmp_path / "pytest-1.xml", [shared]),
        write_shard(tmp_path / "pytest-2.xml", [shared]),
    ]
    assert main(shards) == 1


def test_same_name_in_different_classes_is_not_an_overlap(tmp_path: Path) -> None:
    shards = [
        write_shard(tmp_path / "pytest-1.xml", [("mod.TestA", "test_one")]),
        write_shard(tmp_path / "pytest-2.xml", [("mod.TestB", "test_one")]),
    ]
    assert main(shards) == 0


def test_no_junit_files_is_an_error() -> None:
    assert main([]) == 1
