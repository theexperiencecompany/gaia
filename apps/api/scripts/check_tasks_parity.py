"""Prove tasks match todos and workflows (see scripts/tasks_migration/parity.py for every check).

Reads only. Prints a short summary and one line per difference; exits 1 on any difference.

    cd apps/api && uv run python scripts/check_tasks_parity.py --mongo-uri URI [--db GAIA]
        [--user USER_ID ...]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from scripts.tasks_migration.migrate import Document
from scripts.tasks_migration.parity import TRANSFORMS, check_parity

DEFAULT_DB = "GAIA"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--user", action="append", dest="users", help="check only this user")
    return parser.parse_args()


async def _main(args: argparse.Namespace) -> int:
    client: AsyncIOMotorClient[Document] = AsyncIOMotorClient(args.mongo_uri, tz_aware=True)
    try:
        report = await check_parity(client[args.db], user_ids=args.users)
    finally:
        client.close()
    print("intentional transforms:")
    print("\n".join(f"  - {transform}" for transform in TRANSFORMS))
    print(report.summary())
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_arguments())))
