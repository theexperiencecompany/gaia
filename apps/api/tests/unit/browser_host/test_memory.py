"""Cgroup/psutil memory probe: _read_int, _cgroup_used_and_limit_bytes, memory_usage_mb."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser_host import memory

_MB = 1024 * 1024


def _patch_cgroup_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    v2_current: str | None = None,
    v2_max: str | None = None,
    v1_usage: str | None = None,
    v1_limit: str | None = None,
) -> None:
    def _make(name: str, content: str | None) -> Path:
        path = tmp_path / name
        if content is not None:
            path.write_text(content)
        return path

    monkeypatch.setattr(memory, "_V2_CURRENT", _make("v2_current", v2_current))
    monkeypatch.setattr(memory, "_V2_MAX", _make("v2_max", v2_max))
    monkeypatch.setattr(memory, "_V1_USAGE", _make("v1_usage", v1_usage))
    monkeypatch.setattr(memory, "_V1_LIMIT", _make("v1_limit", v1_limit))


@pytest.mark.unit
def test_read_int_returns_none_for_missing_file(tmp_path):
    assert memory._read_int(tmp_path / "does-not-exist") is None


@pytest.mark.unit
def test_read_int_returns_none_for_non_numeric_content(tmp_path):
    path = tmp_path / "junk"
    path.write_text("not-a-number")

    assert memory._read_int(path) is None


@pytest.mark.unit
def test_read_int_strips_whitespace_and_parses(tmp_path):
    path = tmp_path / "value"
    path.write_text("  123\n")

    assert memory._read_int(path) == 123


@pytest.mark.unit
def test_cgroup_v2_numeric_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current="268435456", v2_max="1073741824")

    assert memory._cgroup_used_and_limit_bytes() == (268435456, 1073741824)


@pytest.mark.unit
def test_cgroup_v2_max_literal_is_unlimited(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current="600000000", v2_max="max")

    assert memory._cgroup_used_and_limit_bytes() == (600000000, None)


@pytest.mark.unit
def test_cgroup_v2_non_numeric_non_max_content_is_treated_unlimited(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current="150000000", v2_max="bogus")

    assert memory._cgroup_used_and_limit_bytes() == (150000000, None)


@pytest.mark.unit
def test_cgroup_v2_missing_max_file_defaults_to_unlimited(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current="700000000")

    assert memory._cgroup_used_and_limit_bytes() == (700000000, None)


@pytest.mark.unit
def test_cgroup_v2_limit_at_unlimited_sentinel_is_treated_unlimited(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v2_current="800000000",
        v2_max=str(memory._UNLIMITED_BYTES),
    )

    assert memory._cgroup_used_and_limit_bytes() == (800000000, None)


@pytest.mark.unit
def test_cgroup_v2_limit_just_under_sentinel_is_kept(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v2_current="900000000",
        v2_max=str(memory._UNLIMITED_BYTES - 1),
    )

    assert memory._cgroup_used_and_limit_bytes() == (900000000, memory._UNLIMITED_BYTES - 1)


@pytest.mark.unit
def test_cgroup_v1_fallback_with_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v1_usage="500000000", v1_limit="2500000000")

    assert memory._cgroup_used_and_limit_bytes() == (500000000, 2500000000)


@pytest.mark.unit
def test_cgroup_v1_fallback_without_limit_file(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v1_usage="400000000")

    assert memory._cgroup_used_and_limit_bytes() == (400000000, None)


@pytest.mark.unit
def test_cgroup_v1_limit_at_unlimited_sentinel_is_treated_unlimited(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v1_usage="300000000",
        v1_limit=str(memory._UNLIMITED_BYTES),
    )

    assert memory._cgroup_used_and_limit_bytes() == (300000000, None)


@pytest.mark.unit
def test_cgroup_absent_entirely_returns_none(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path)

    assert memory._cgroup_used_and_limit_bytes() is None


@pytest.mark.unit
def test_memory_usage_mb_uses_cgroup_limit_without_override(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v2_current=str(256 * _MB),
        v2_max=str(1024 * _MB),
    )
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", None)

    used, limit = memory.memory_usage_mb()

    assert used == 256.0
    assert limit == 1024.0


@pytest.mark.unit
def test_memory_usage_mb_override_caps_cgroup_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v2_current=str(256 * _MB),
        v2_max=str(1024 * _MB),
    )
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 300)

    used, limit = memory.memory_usage_mb()

    assert used == 256.0
    assert limit == 300.0


@pytest.mark.unit
def test_memory_usage_mb_override_above_cgroup_limit_keeps_cgroup_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(
        monkeypatch,
        tmp_path,
        v2_current=str(256 * _MB),
        v2_max=str(1024 * _MB),
    )
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 2000)

    used, limit = memory.memory_usage_mb()

    assert used == 256.0
    assert limit == 1024.0


@pytest.mark.unit
def test_memory_usage_mb_no_cgroup_limit_uses_psutil_total_without_override(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current=str(123 * _MB), v2_max="max")
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", None)
    monkeypatch.setattr(
        memory.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=4096 * _MB, available=1024 * _MB),
    )

    used, limit = memory.memory_usage_mb()

    assert used == 123.0
    assert limit == 4096.0


@pytest.mark.unit
def test_memory_usage_mb_no_cgroup_limit_override_supplies_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path, v2_current=str(123 * _MB), v2_max="max")
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 500)
    monkeypatch.setattr(
        memory.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=4096 * _MB, available=1024 * _MB),
    )

    used, limit = memory.memory_usage_mb()

    assert used == 123.0
    assert limit == 500.0


@pytest.mark.unit
def test_memory_usage_mb_off_cgroup_uses_psutil_used_and_total(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", None)
    monkeypatch.setattr(
        memory.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8192 * _MB, available=2048 * _MB),
    )

    used, limit = memory.memory_usage_mb()

    assert used == 6144.0
    assert limit == 8192.0


@pytest.mark.unit
def test_memory_usage_mb_off_cgroup_with_override_limit(monkeypatch, tmp_path):
    _patch_cgroup_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(memory.settings, "BROWSER_HOST_MEMORY_LIMIT_MB", 700)
    monkeypatch.setattr(
        memory.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=8192 * _MB, available=2048 * _MB),
    )

    used, limit = memory.memory_usage_mb()

    assert used == 6144.0
    assert limit == 700.0
