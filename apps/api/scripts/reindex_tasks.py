"""Write every task's entry in the task search index (see scripts/tasks_migration/search_index.py).

Run after migrate_to_tasks.py, in the API's environment: it embeds through the deployment's
Chroma and embedding model. Idempotent; rerun it to finish an interrupted run or to repair
entries a failed index write left out. check_tasks_parity.py --index proves coverage.

    cd apps/api && uv run python scripts/reindex_tasks.py --mongo-uri URI [--db GAIA]
        [--user USER_ID ...]
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
from scripts.tasks_migration.search_index import reindex

DEFAULT_DB = "GAIA"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mongo-uri", required=True)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--user", action="append", dest="users", help="index only this user")
    return parser.parse_args()


async def _main(args: argparse.Namespace) -> int:
    boot_process("main_app")
    client: AsyncIOMotorClient[Document] = AsyncIOMotorClient(args.mongo_uri, tz_aware=True)
    try:
        report = await reindex(client[args.db], await task_index(), user_ids=args.users)
    finally:
        client.close()
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(_arguments())))
