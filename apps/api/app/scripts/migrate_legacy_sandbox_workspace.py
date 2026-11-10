#!/usr/bin/env python3
"""Copy the pre-isolation shared sandbox volume into per-user workspaces.

`gaia start`, `gaia up` and `gaia update` run this automatically while the old
gaia-sandbox-workspace volume exists, mounted read-only at --legacy-root::

    docker compose -f docker-compose.selfhost.yml run --rm --no-deps \\
      -v gaia-sandbox-workspace:/legacy-sandbox-workspace:ro gaia-backend \\
      python -m app.scripts.migrate_legacy_sandbox_workspace \\
      --legacy-root /legacy-sandbox-workspace

Idempotent: the report it writes into the workspace volume marks it done.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.services.sandbox.legacy_workspace_migration import (
    migrate_legacy_sandbox_workspace,
    report_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--legacy-root", type=Path, required=True)
    args = parser.parse_args()

    report = asyncio.run(migrate_legacy_sandbox_workspace(args.legacy_root))
    if report is None:
        print(f"Legacy sandbox workspace already migrated (report: {report_path()})")
        return
    print(
        f"Migrated {len(report.migrated_sessions)} session(s), {report.copied_files} file(s); "
        f"skipped {report.skipped_existing} already present."
    )
    for label, paths in (
        ("no provable owner", report.unresolved),
        ("unreadable", report.unreadable),
    ):
        if paths:
            print(f"Left in the legacy volume ({label}): " + ", ".join(paths))
    print(f"Report: {report_path()}")


if __name__ == "__main__":
    main()
