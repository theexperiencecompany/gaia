"""Take a heygaia.link down for breaking GAIA's terms, or lift a report suspension.

Takedown revokes the link for good and deletes its file snapshot; --restore
clears a report suspension only, so content a takedown removed stays removed.

    cd apps/api && uv run python scripts/link_takedown.py --slug SLUG [--restore]
"""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.links import abuse
from app.services.links.service import get_link


async def _run(slug: str, *, restore: bool) -> str:
    link = await get_link(slug)
    if link is None:
        return "no such link"
    if restore:
        await abuse.restore(link)
        return "suspension lifted" if link.suspended else "was not suspended; nothing changed"
    await abuse.take_down(link)
    return "taken down"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", required=True, help="the link's slug (heygaia.link/<slug>)")
    parser.add_argument("--restore", action="store_true", help="lift a report suspension")
    args = parser.parse_args()
    print(asyncio.run(_run(args.slug, restore=args.restore)))


if __name__ == "__main__":
    main()
