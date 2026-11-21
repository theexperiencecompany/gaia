"""Move todos and workflows into tasks (see scripts/tasks_migration/migrate.py for the rules).

Dry run by default; --apply writes. Point it at any copy of the database by URI. Run with
the workers stopped, then run check_tasks_parity.py; exits 1 when a document could not move.

    cd apps/api && uv run python scripts/migrate_to_tasks.py --mongo-uri URI [--db GAIA]
        [--apply] [--restart] [--user USER_ID ...]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from scripts.tasks_migration.migrate import Document, migrate

DEFAULT_DB = "GAIA"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="write; without it nothing is written")
    parser.add_argument(
        "--restart", action="store_true", help="ignore the progress of an earlier run"
    )
    parser.add_argument(
        "--user", action="append", dest="users", help="move only this user's documents (repeatable)"
    )
    return parser.parse_args()


async def _main(args: argparse.Namespace) -> int:
    client: AsyncIOMotorClient[Document] = AsyncIOMotorClient(args.mongo_uri, tz_aware=True)
    try:
        report = await migrate(
            client[args.db], apply=args.apply, restart=args.restart, user_ids=args.users
        )
    finally:
        client.close()
    print(report.summary())
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_arguments())))
