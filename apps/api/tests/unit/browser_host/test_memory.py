"""The memory admission gates on: a container's working set, or the host's own tree off one.

The cgroup files are laid out in a temp directory exactly as the kernel writes
them, so the parsing is real.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser_host import memory
from app.config.browser_host_settings import browser_host_settings

pytestmark = pytest.mark.unit

_MB = 1024 * 1024


def _cgroup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    v2: dict[str, str] | None = None,
    v1: dict[str, str] | None = None,
) -> None:
    def _layout(
        prefix: str, files: dict[str, str] | None, names: tuple[str, str, str], key: str
    ) -> tuple[Path, Path, Path, str]:
        base = tmp_path / prefix
        base.mkdir(parents=True, exist_ok=True)
        for name, text in (files or {}).items():
            (base / name).write_text(text)
        return (base / names[0], base / names[1], base / names[2], key)

    monkeypatch.setattr(
        memory,
        "_V2",
        _layout("v2", v2, ("memory.current", "memory.max", "memory.stat"), "inactive_file"),
    )
    monkeypatch.setattr(
        memory,
        "_V1",
        _layout(
            "v1",
            v1,
            ("memory.usage_in_bytes", "memory.limit_in_bytes", "memory.stat"),
            "total_inactive_file",
        ),
    )
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_LIMIT_MB", None)


def test_a_container_is_charged_its_working_set_not_its_page_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(
        tmp_path,
        monkeypatch,
        v2={
            "memory.current": str(900 * _MB),
            "memory.max": str(2048 * _MB),
            "memory.stat": f"anon {500 * _MB}\ninactive_file {300 * _MB}\nactive_file 7\n",
        },
    )

    assert memory.memory_usage_mb() == (600.0, 2048.0)


def test_a_cgroup_v1_container_reads_its_own_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(
        tmp_path,
        monkeypatch,
        v1={
            "memory.usage_in_bytes": str(400 * _MB),
            "memory.limit_in_bytes": str(1024 * _MB),
            "memory.stat": f"total_inactive_file {100 * _MB}\n",
        },
    )

    assert memory.memory_usage_mb() == (300.0, 1024.0)


def test_a_configured_limit_caps_the_container_but_never_raises_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(
        tmp_path,
        monkeypatch,
        v2={"memory.current": str(100 * _MB), "memory.max": str(1024 * _MB)},
    )
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 512)
    assert memory.memory_usage_mb() == (100.0, 512.0)

    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 4096)
    assert memory.memory_usage_mb() == (100.0, 1024.0)


def test_a_working_set_never_reads_below_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(
        tmp_path,
        monkeypatch,
        v2={
            "memory.current": str(10 * _MB),
            "memory.max": str(100 * _MB),
            "memory.stat": f"inactive_file {20 * _MB}\n",
        },
    )

    assert memory.memory_usage_mb()[0] == 0.0


def _off_container(monkeypatch: pytest.MonkeyPatch, *, own: int, available: int) -> list[int]:
    asked: list[int] = []

    def _tree(pid: int) -> float:
        asked.append(pid)
        return own / _MB

    monkeypatch.setattr(memory, "process_tree_rss_mb", _tree)
    monkeypatch.setattr(
        memory.psutil, "virtual_memory", lambda: SimpleNamespace(available=available)
    )
    return asked


@pytest.mark.parametrize(
    "v2",
    [
        None,
        {"memory.current": str(100 * _MB), "memory.max": "max"},
        {"memory.current": str(100 * _MB), "memory.max": str(1 << 62)},
    ],
)
def test_off_a_limited_container_the_host_is_charged_its_own_tree_against_what_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, v2: dict[str, str] | None
) -> None:
    _cgroup(tmp_path, monkeypatch, v2=v2)
    asked = _off_container(monkeypatch, own=300 * _MB, available=1000 * _MB)

    assert memory.memory_usage_mb() == (300.0, 1300.0)
    assert asked == [os.getpid()]


def test_a_host_that_cannot_read_its_own_memory_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(tmp_path, monkeypatch)
    monkeypatch.setattr(memory, "process_tree_rss_mb", lambda pid: None)

    with pytest.raises(RuntimeError) as unread:
        memory.memory_usage_mb()
    assert unread.value.args == ("the browser host cannot read its own memory",)


def test_off_a_container_a_configured_limit_is_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cgroup(tmp_path, monkeypatch)
    _off_container(monkeypatch, own=300 * _MB, available=1000 * _MB)
    monkeypatch.setattr(browser_host_settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 800)

    assert memory.memory_usage_mb() == (300.0, 800.0)


@pytest.mark.parametrize(
    "text",
    ["", "inactive_file\n", "inactive_file lots\n", "other 5\n", "inactive_file 5 extra\n"],
)
def test_an_unreadable_stat_counts_no_cache(tmp_path: Path, text: str) -> None:
    stat = tmp_path / "memory.stat"
    stat.write_text(text)

    assert memory._stat_value(stat, "inactive_file") == 0
    assert memory._stat_value(tmp_path / "missing", "inactive_file") == 0
