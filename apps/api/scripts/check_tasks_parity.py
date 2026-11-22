"""Prove tasks match todos and workflows (see scripts/tasks_migration/parity.py for every check).

Reads only. Prints a short summary and one line per difference; exits 1 on any difference.
--index also counts the task search index against the tasks (needs the API's environment).

    cd apps/api && uv run python scripts/check_tasks_parity.py --mongo-uri URI [--db GAIA]
        [--user USER_ID ...] [--index]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.provider_registration import boot_process
from app.services.tasks.search_index import task_index
from scripts.tasks_migration.migrate import Document
from scripts.tasks_migration.parity import TRANSFORMS, ParityReport, check_parity
from scripts.tasks_migration.search_index import check_index

DEFAULT_DB = "GAIA"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--user", action="append", dest="users", help="check only this user")
    parser.add_argument(
        "--index", action="store_true", help="also prove every task has its search index entry"
    )
    return parser.parse_args()


async def _main(args: argparse.Namespace) -> int:
    client: AsyncIOMotorClient[Document] = AsyncIOMotorClient(args.mongo_uri, tz_aware=True)
    reports: list[ParityReport] = []
    try:
        reports.append(await check_parity(client[args.db], user_ids=args.users))
        if args.index:
            boot_process("main_app")
            reports.append(
                await check_index(client[args.db], await task_index(), user_ids=args.users)
            )
    finally:
        client.close()
    print("intentional transforms:")
    print("\n".join(f"  - {transform}" for transform in TRANSFORMS))
    for report in reports:
        print(report.summary())
    return 0 if all(report.clean for report in reports) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_arguments())))
