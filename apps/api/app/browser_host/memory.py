"""Container-aware memory probe backing the host's memory-based admission control.

Reports (used_mb, limit_mb) for the environment the browser host runs in. The
limit that matters is the one the OOM killer enforces, the container's cgroup
limit, and the usage that matters is its working set: memory.current also counts
page cache the kernel reclaims before it would ever kill anything. Off a
container (native dev) the host's own process tree is the usage and what the
machine still has free is the room. BROWSER_HOST_MEMORY_LIMIT_MB pins or caps it.
"""

from __future__ import annotations

from pathlib import Path

import psutil

from app.config.browser_host_settings import browser_host_settings

# cgroup v2 (unified) then v1 (legacy): usage, limit, and the stat file whose
# inactive file pages are reclaimable cache.
_V2 = (
    Path("/sys/fs/cgroup/memory.current"),
    Path("/sys/fs/cgroup/memory.max"),
    Path("/sys/fs/cgroup/memory.stat"),
    "inactive_file",
)
_V1 = (
    Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    Path("/sys/fs/cgroup/memory/memory.stat"),
    "total_inactive_file",
)

_BYTES_PER_MB = 1024 * 1024
# cgroup "no limit" is the literal "max" (v2) or a near-INT64 sentinel (v1).
_UNLIMITED_BYTES = 1 << 62


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _stat_value(path: Path, key: str) -> int:
    """One counter from a cgroup memory.stat file; 0 when the file or the key is absent."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    for line in lines:
        name, _, value = line.partition(" ")
        if name == key and value.strip().isdigit():
            return int(value)
    return 0


def _cgroup_working_set_and_limit_bytes() -> tuple[int, int] | None:
    """Return (working set, limit) from a memory-limited cgroup; None when there is none."""
    for usage_path, limit_path, stat_path, inactive_key in (_V2, _V1):
        used = _read_int(usage_path)
        limit = _read_int(limit_path)
        if used is not None and limit is not None and limit < _UNLIMITED_BYTES:
            return max(used - _stat_value(stat_path, inactive_key), 0), limit
    return None


def _own_tree_rss_bytes() -> int:
    """Resident memory of this process and every process it started (the engines)."""
    me = psutil.Process()
    total: int = me.memory_info().rss
    for child in me.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.NoSuchProcess:
            continue
    return total


def memory_usage_mb() -> tuple[float, float]:
    """Return the current (used_mb, limit_mb) the host admits sessions against."""
    override = browser_host_settings.BROWSER_HOST_MEMORY_LIMIT_MB
    cgroup = _cgroup_working_set_and_limit_bytes()
    if cgroup is not None:
        used = cgroup[0] / _BYTES_PER_MB
        limit = cgroup[1] / _BYTES_PER_MB
        return used, (min(limit, float(override)) if override else limit)
    used = _own_tree_rss_bytes() / _BYTES_PER_MB
    room = psutil.virtual_memory().available / _BYTES_PER_MB
    return used, (float(override) if override else used + room)
