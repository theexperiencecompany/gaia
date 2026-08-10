"""Session ``.meta.json`` I/O: corruption tolerance and timestamp semantics.

Two consumers depend on this module and both fail silently when it is wrong.
``touch_session_last_active`` read-modify-writes the file on every chat turn, so
a read that raises instead of returning ``{}`` takes down the turn. The
idle-prune scanner turns ``last_active`` into a delete decision, so a timestamp
misread by a timezone offset either deletes a live session's workspace or keeps
a dead one forever.

Boundaries mocked: none — the files are real, under ``tmp_path``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from app.services.storage.sessions.meta import (
    SESSION_META_FILENAME,
    SESSION_META_SCHEMA_VERSION,
    now_iso,
    parse_last_active,
    read_session_meta,
    write_session_meta,
)


@pytest.fixture
def meta(tmp_path: Path) -> Path:
    return tmp_path / SESSION_META_FILENAME


# ── read_session_meta: corruption tolerance ──────────────────────────


def test_a_session_without_a_meta_file_reads_as_empty(meta: Path) -> None:
    assert read_session_meta(meta) == {}


def test_a_truncated_meta_file_reads_as_empty_instead_of_raising(meta: Path) -> None:
    # A crash mid-write leaves exactly this. Propagating the JSONDecodeError
    # would make every later turn on that conversation fail to start.
    meta.write_text('{"last_active":"2026-01-0', encoding="utf-8")

    assert read_session_meta(meta) == {}


def test_an_empty_meta_file_reads_as_empty(meta: Path) -> None:
    meta.write_text("", encoding="utf-8")

    assert read_session_meta(meta) == {}


@pytest.mark.parametrize("payload", ["[]", '"just a string"', "null", "42", "true"])
def test_a_meta_file_that_is_not_a_json_object_reads_as_empty(meta: Path, payload: str) -> None:
    # Without the isinstance guard a JSON array parses fine and the caller's
    # `data.setdefault(...)` blows up on a list — an AttributeError three frames
    # away from the actual corruption.
    meta.write_text(payload, encoding="utf-8")

    assert read_session_meta(meta) == {}


def test_a_meta_file_with_invalid_utf8_bytes_reads_as_empty(meta: Path) -> None:
    # UnicodeDecodeError is a ValueError, not a JSONDecodeError. Narrowing the
    # except clause to json errors alone would let this escape.
    meta.write_bytes(b'{"last_active":"\xff\xfe"}')

    assert read_session_meta(meta) == {}


def test_a_meta_path_that_is_a_directory_reads_as_empty(meta: Path) -> None:
    # `exists()` is True for a directory; the read is what fails. Dropping OSError
    # from the except clause turns a stray directory into a hard 500.
    meta.mkdir()

    assert read_session_meta(meta) == {}


def test_a_dangling_symlink_meta_reads_as_empty(tmp_path: Path) -> None:
    link = tmp_path / SESSION_META_FILENAME
    link.symlink_to(tmp_path / "gone.json")

    assert read_session_meta(link) == {}


def test_a_valid_meta_file_is_returned_with_every_key_intact(meta: Path) -> None:
    meta.write_text(
        json.dumps({"created_at": "2026-01-01T00:00:00+00:00", "msg_count": 4}),
        encoding="utf-8",
    )

    assert read_session_meta(meta) == {"created_at": "2026-01-01T00:00:00+00:00", "msg_count": 4}


# ── write_session_meta ───────────────────────────────────────────────


def test_every_write_stamps_the_current_schema_version(meta: Path) -> None:
    # The stamp is what a future migration keys off; an unstamped payload would
    # be indistinguishable from a v0 file.
    write_session_meta(meta, {"last_active": "2026-01-01T00:00:00+00:00"})

    assert read_session_meta(meta)["schema_version"] == SESSION_META_SCHEMA_VERSION


def test_writing_replaces_the_previous_contents_rather_than_appending(meta: Path) -> None:
    # An append (or a shorter payload written over a longer one without
    # truncating) leaves trailing bytes that make the next read return {} and
    # silently reset created_at.
    write_session_meta(meta, {"created_at": "old", "msg_count": 999, "extra": "x" * 200})
    write_session_meta(meta, {"msg_count": 1})

    data = read_session_meta(meta)
    assert data == {"msg_count": 1, "schema_version": SESSION_META_SCHEMA_VERSION}


def test_an_empty_payload_still_writes_a_readable_object(meta: Path) -> None:
    write_session_meta(meta, {})

    assert read_session_meta(meta) == {"schema_version": SESSION_META_SCHEMA_VERSION}


def test_unicode_values_survive_the_write_read_round_trip(meta: Path) -> None:
    payload = {"title": "café 日本語 🎉", "path": "réunion/notes.md"}
    write_session_meta(meta, dict(payload))

    data = read_session_meta(meta)
    assert data["title"] == payload["title"]
    assert data["path"] == payload["path"]


def test_the_file_is_written_compactly_without_padding_whitespace(meta: Path) -> None:
    # Written on every chat turn for every session; the default separators add
    # two bytes per key for nothing.
    write_session_meta(meta, {"a": 1, "b": 2})

    raw = meta.read_text(encoding="utf-8")
    assert ", " not in raw
    assert ": " not in raw


def test_writing_into_a_missing_directory_fails_loudly(tmp_path: Path) -> None:
    # Callers create the session dir first. Swallowing this would drop the
    # session's timestamps forever while reporting success.
    with pytest.raises(OSError):
        write_session_meta(tmp_path / "no-such-session" / SESSION_META_FILENAME, {"a": 1})


# ── parse_last_active ────────────────────────────────────────────────


def test_a_missing_meta_file_has_no_last_active(meta: Path) -> None:
    assert parse_last_active(meta) is None


def test_a_meta_without_a_last_active_key_is_unknown(meta: Path) -> None:
    write_session_meta(meta, {"created_at": "2026-01-01T00:00:00+00:00"})

    assert parse_last_active(meta) is None


def test_a_corrupt_meta_leaves_the_session_unknown_rather_than_stale(meta: Path) -> None:
    # "Unknown" makes the scanner skip the session. Returning a sentinel epoch
    # instead would delete the workspace of every session whose file got
    # truncated mid-write.
    meta.write_text("{not json", encoding="utf-8")

    assert parse_last_active(meta) is None


@pytest.mark.parametrize("raw", [1735689600, None, {"iso": "2026-01-01"}, ["2026-01-01"], True])
def test_a_non_string_last_active_is_unknown(meta: Path, raw: object) -> None:
    # Without the isinstance guard `datetime.fromisoformat(1735689600)` raises
    # TypeError, which the try/except (ValueError only) does not catch — one bad
    # file would abort the entire stale-session sweep.
    write_session_meta(meta, {"last_active": raw})

    assert parse_last_active(meta) is None


@pytest.mark.parametrize(
    "raw", ["", "yesterday", "2026-13-45T99:00:00", "2026-01-01T00:00:00+99:00", "  "]
)
def test_an_unparseable_last_active_string_is_unknown(meta: Path, raw: str) -> None:
    write_session_meta(meta, {"last_active": raw})

    assert parse_last_active(meta) is None


def test_a_naive_timestamp_is_read_as_utc_so_it_can_be_compared_against_now(meta: Path) -> None:
    # The scanner compares against datetime.now(UTC); a naive return value makes
    # that comparison raise TypeError and kills the prune job.
    write_session_meta(meta, {"last_active": "2026-01-01T00:00:00"})

    parsed = parse_last_active(meta)
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(0)
    assert parsed < datetime.now(UTC)


def test_an_offset_aware_timestamp_keeps_its_own_offset_instead_of_being_restamped_as_utc(
    meta: Path,
) -> None:
    # Coercing unconditionally would shift this instant by 5.5 hours — enough to
    # prune a session that was active minutes ago, or spare one that is dead.
    write_session_meta(meta, {"last_active": "2026-01-01T00:00:00+05:30"})

    parsed = parse_last_active(meta)
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(hours=5, minutes=30)
    assert parsed == datetime(2025, 12, 31, 18, 30, tzinfo=UTC)


def test_a_z_suffixed_timestamp_is_parsed_as_utc(meta: Path) -> None:
    write_session_meta(meta, {"last_active": "2026-01-01T00:00:00Z"})

    assert parse_last_active(meta) == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_date_only_timestamp_is_read_as_midnight_utc(meta: Path) -> None:
    write_session_meta(meta, {"last_active": "2026-01-01"})

    assert parse_last_active(meta) == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_timestamp_this_module_wrote_round_trips_back_to_roughly_now(meta: Path) -> None:
    # The full loop the prune scanner depends on: now_iso() -> file -> parse ->
    # compare. A naive now_iso() would land the value TZ-offset hours away and,
    # west of UTC, in the future.
    write_session_meta(meta, {"last_active": now_iso()})

    parsed = parse_last_active(meta)
    assert parsed is not None
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 5


def test_now_iso_is_timezone_aware_utc() -> None:
    stamp = now_iso()

    assert stamp.endswith("+00:00")
    assert datetime.fromisoformat(stamp).utcoffset() == timedelta(0)


def test_a_session_older_than_the_cutoff_reads_as_stale_and_a_fresh_one_does_not(
    tmp_path: Path,
) -> None:
    # End-to-end of the prune predicate: `last_active < cutoff`.
    cutoff = datetime.now(UTC) - timedelta(days=7)
    old = tmp_path / "old.json"
    fresh = tmp_path / "fresh.json"
    write_session_meta(old, {"last_active": (cutoff - timedelta(days=1)).isoformat()})
    write_session_meta(fresh, {"last_active": (cutoff + timedelta(days=1)).isoformat()})

    old_ts = parse_last_active(old)
    fresh_ts = parse_last_active(fresh)
    assert old_ts is not None and old_ts < cutoff
    assert fresh_ts is not None and fresh_ts >= cutoff
