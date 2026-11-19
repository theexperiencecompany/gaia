"""Snapshot every live file link minted before link snapshots existed.

Dry run by default: prints how many links are pending. --apply publishes each
file's snapshot, or revokes the link as target_deleted when the file is gone.
The deploy gate for removing the live-file read path is a dry run reporting 0.

    cd apps/api && uv run python scripts/backfill_link_snapshots.py [--apply]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.links.backfill import backfill_snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="publish snapshots (default: dry run)")
    args = parser.parse_args()
    report = asyncio.run(backfill_snapshots(apply=args.apply))
    mode = "applied" if args.apply else "dry run"
    print(
        f"{mode}: {report.pending} pending, {report.published} published, "
        f"{report.target_deleted} target deleted"
    )


if __name__ == "__main__":
    main()
