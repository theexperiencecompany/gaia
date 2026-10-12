"""Delete core memory documents whose doc_type is no longer a MemoryDocType.

#1094 removed insights.md end to end: it was an LLM digest of experience facts
with no grounding, and those facts stay in the memories table, so it has no
successor document and dropping it loses no user-authored content. Its rows were
never cleaned up, and every read mapping doc_type through MemoryDocType (overview,
documents API, the /workspace/memory projection) crashes on them.

Selects every memory_documents row whose doc_type is not a current MemoryDocType
value, prints each (user, type, version, size), and deletes exactly those with
--apply. The stale file leaves the workspace projection on the user's next memory sync.

    cd apps/api && uv run python scripts/drop_retired_memory_documents.py [--apply]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, select

from app.constants.memory import MemoryDocType
from app.core.provider_registration import register_lazy_providers
from app.db.postgresql import close_postgresql_db
from app.memory.pg_store._session import memory_session
from app.models.memory_db_models import MemoryDocument

_CURRENT_DOC_TYPES = [doc_type.value for doc_type in MemoryDocType]


async def drop_retired_documents(*, apply: bool) -> list[MemoryDocument]:
    """Print every retired-type document, delete them when apply is set, and return them."""
    async with memory_session() as session:
        retired = list(
            (
                await session.execute(
                    select(MemoryDocument)
                    .where(MemoryDocument.doc_type.not_in(_CURRENT_DOC_TYPES))
                    .order_by(MemoryDocument.user_id, MemoryDocument.doc_type)
                )
            )
            .scalars()
            .all()
        )
        for row in retired:
            print(
                f"  {row.user_id}  {row.doc_type}  v{row.version}  "
                f"{len(row.content)} chars  updated {row.updated_at:%Y-%m-%d}"
            )
        print(
            f"{len(retired)} retired document(s) across {len({r.user_id for r in retired})} user(s)"
        )
        if apply and retired:
            await session.execute(
                delete(MemoryDocument).where(MemoryDocument.id.in_([row.id for row in retired]))
            )
            await session.commit()
            print("Deleted.")
        elif retired:
            print("Dry run only. Re-run with --apply to delete.")
    return retired


async def _run(apply: bool) -> None:
    # A script has no lifespan, so nobody registers the lazy Postgres engine otherwise.
    register_lazy_providers("main_app")
    try:
        await drop_retired_documents(apply=apply)
    finally:
        await close_postgresql_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete (otherwise dry run only).")
    asyncio.run(_run(parser.parse_args().apply))


if __name__ == "__main__":
    main()
