#!/usr/bin/env python3
"""Rename the legacy ``content_type`` field on ``files`` documents to ``type``.

``FileDocument`` requires ``type``, but six uploads from March 2025 stored the
same value under ``content_type`` and no ``type`` at all. Because legacy files
without a ``conversation_id`` stay visible to every conversation's file search
(``find_ids_for_conversation``), one of those rows is enough to make
``search_uploaded_files`` raise a validation error for that user.

This is a data fix, not a compatibility shim: the model stays strict, and the
six rows are corrected once.

Safety:

- report-only by default; nothing is written without ``--apply``;
- a document with neither field, or with conflicting values, blocks the run
  before anything is written (exit 1);
- each update is filtered on the exact state the plan saw, so a concurrent
  write cannot be clobbered;
- ``--restore <backup.json>`` reverses an apply exactly, using the ids and
  values recorded in the backup.

Usage::

    cd apps/api
    uv run python -m app.scripts.migrate_file_type_field                 # report only
    uv run python -m app.scripts.migrate_file_type_field --apply         # writes backup + migrates
    uv run python -m app.scripts.migrate_file_type_field --restore file_type_migration_backup.json
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys

from app.db.repositories.files import file_repository

LEGACY_FIELD = "content_type"
CANONICAL_FIELD = "type"
DEFAULT_BACKUP_PATH = "file_type_migration_backup.json"


def _backup_path(raw: Path) -> Path:
    """Resolve a backup file name inside the working directory.

    The operator names the file, never its directory: anything with a parent or
    an absolute path is refused, so a mistyped or injected argument cannot read
    or write outside the directory the script was started in.
    """
    if raw.is_absolute() or raw.name != str(raw) or raw.name in {"", ".", ".."}:
        raise SystemExit(f"backup path must be a file name in the current directory: {raw}")
    return Path.cwd() / raw


@dataclass(frozen=True)
class LegacyFile:
    """One document that stores its mimetype under the legacy field name."""

    file_id: str
    filename: str
    content_type: str


@dataclass(frozen=True)
class Conflict:
    """A document this script refuses to touch, with the reason."""

    file_id: str
    filename: str
    reason: str


async def plan() -> tuple[list[LegacyFile], list[Conflict]]:
    """Return what would be renamed, plus every document that blocks the run."""
    legacy: list[LegacyFile] = []
    conflicts: list[Conflict] = []

    for row in await file_repository.find_mimetype_rows():
        if row.type is not None and row.content_type is not None:
            if row.type != row.content_type:
                conflicts.append(
                    Conflict(
                        file_id=row.file_id,
                        filename=row.filename,
                        reason=(
                            f"both fields present and different: "
                            f"{CANONICAL_FIELD}={row.type!r}, "
                            f"{LEGACY_FIELD}={row.content_type!r}"
                        ),
                    )
                )
        elif row.type is None and row.content_type is None:
            conflicts.append(
                Conflict(
                    file_id=row.file_id,
                    filename=row.filename,
                    reason=f"neither {CANONICAL_FIELD} nor {LEGACY_FIELD} is set",
                )
            )
        elif row.type is None and row.content_type is not None:
            legacy.append(
                LegacyFile(
                    file_id=row.file_id,
                    filename=row.filename,
                    content_type=row.content_type,
                )
            )

    return legacy, conflicts


async def apply(files: list[LegacyFile], backup_path: Path) -> int:
    """Rename the field on each planned document, after writing the rollback file."""
    if not files:
        # Never clobber a previous run's rollback file with an empty plan.
        return 0

    backup_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "files": [asdict(file) for file in files],
            },
            indent=2,
        )
        + "\n"
    )

    migrated = 0
    for file in files:
        if await file_repository.rename_legacy_mimetype(file.file_id, file.content_type):
            migrated += 1
    return migrated


async def restore(backup_path: Path) -> int:
    """Reverse an apply using the ids and values recorded in its backup file."""
    payload = json.loads(backup_path.read_text())
    restored = 0
    for entry in payload["files"]:
        if await file_repository.restore_legacy_mimetype(entry["file_id"], entry["content_type"]):
            restored += 1
    return restored


async def _run(args: argparse.Namespace) -> int:
    if args.restore is not None:
        restore_path = _backup_path(args.restore)
        restored = await restore(restore_path)
        print(f"restored {restored} document(s) from {restore_path}")
        return 0

    files, conflicts = await plan()
    print(f"legacy documents to rename: {len(files)}")
    for file in files:
        print(f"  {file.file_id}  {file.content_type:<32}  {file.filename}")

    if conflicts:
        print(f"\nblocking documents: {len(conflicts)}", file=sys.stderr)
        for conflict in conflicts:
            print(
                f"  {conflict.file_id}  {conflict.reason}  ({conflict.filename})",
                file=sys.stderr,
            )
        print(
            "\nrefusing to run: fix or account for the blocking documents first.", file=sys.stderr
        )
        return 1

    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply.")
        return 0

    if not files:
        print("\nnothing to migrate.")
        return 0

    backup_path = _backup_path(Path(args.backup))
    migrated = await apply(files, backup_path)
    print(f"\nmigrated {migrated} of {len(files)} document(s); rollback at {backup_path}")

    # The writes are filtered on the state the plan saw, so a row that changed
    # under us is skipped. Verify the end state instead of trusting the count.
    remaining, conflicts = await plan()
    if remaining:
        print(
            f"{len(remaining)} document(s) still need migration: "
            f"{', '.join(file.file_id for file in remaining)}",
            file=sys.stderr,
        )
        return 1
    if conflicts:
        print(
            f"{len(conflicts)} document(s) are in a conflicting state; review them.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write the rename; default is report-only."
    )
    parser.add_argument(
        "--backup",
        default=DEFAULT_BACKUP_PATH,
        metavar="PATH",
        help=f"File name in the current directory for the rollback data (default: {DEFAULT_BACKUP_PATH}).",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        metavar="PATH",
        help="Reverse a previous --apply using a backup file in the current directory.",
    )
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
