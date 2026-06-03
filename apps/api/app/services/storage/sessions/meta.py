"""``.meta.json`` I/O for session directories.

Each session has a single ``.meta.json`` file at the session root with two
load-bearing fields: ``created_at`` (immutable) and ``last_active``
(idle-prune cutoff). ``schema_version`` is stamped on every write so a
future migration can detect old payloads without scanning every key.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

SESSION_META_FILENAME = ".meta.json"
SESSION_META_SCHEMA_VERSION = 1


def now_iso() -> str:
    """ISO-8601 timestamp in UTC. Stable shape for the session meta files."""
    return datetime.now(UTC).isoformat()


def read_session_meta(meta: Path) -> dict[str, object]:
    """Best-effort read of a session ``.meta.json``.

    Returns an empty dict for missing files, malformed JSON, or non-object
    payloads — callers treat absence and corruption identically (recreate).
    """
    if not meta.exists():
        return {}
    try:
        loaded = json.loads(meta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_session_meta(meta: Path, data: dict[str, object]) -> None:
    """Stamp ``schema_version`` and write compactly. Caller owns the dict."""
    data["schema_version"] = SESSION_META_SCHEMA_VERSION
    meta.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def parse_last_active(meta: Path) -> datetime | None:
    """Return the parsed ``last_active`` timestamp or ``None`` if unparseable.

    Used by the stale-session scanner — naive values are coerced to UTC so
    comparisons against ``datetime.now(tz=UTC)`` don't blow up. Anything we
    can't read is treated as "unknown" rather than "stale": callers skip it
    rather than pruning a session whose timestamp got truncated.
    """
    data = read_session_meta(meta)
    raw = data.get("last_active")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
