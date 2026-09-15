#!/usr/bin/env python3
"""Developer tool: send every LOCAL user back through onboarding from scratch.

For each user in the local Mongo this runs the ``reset_onboarding`` behind the
product's "Restart onboarding" button with ``keep_connections``: seeded
conversations, onboarding todos and legacy suggested workflows are deleted and
the ``onboarding`` subdocument is unset, while connected integrations and
memories stay. Every subscription record of the user is deleted too, so the
wizard shows the paywall again, and every linked chat platform (Telegram,
WhatsApp, iMessage, ...) is unlinked so the one-tap link can be tested fresh (the Dodo test-mode side is untouched: run a
fresh test checkout, with ``dodo wh listen`` pointed at this API so the
activation webhook lands). It then empties the local Redis so no cached user
document, cached plan, rate-limit bucket or link code survives.

The wizard also keeps in-progress answers in the browser under
``gaia-onboarding-state-v3:<userId>``; clear site data (or use the product's
Restart button once) if a stale draft resurfaces.

Refuses to run unless ``ENV`` is development and both ``MONGO_DB`` and
``REDIS_URL`` point at this machine. It is not a migration and must never see
production credentials.

Run from the repo root so Infisical's dev secrets are injected:

    infisical run --env=development -- uv run --project apps/api \
        python apps/api/scripts/reset_local_onboarding.py --dry-run
    infisical run --env=development -- uv run --project apps/api \
        python apps/api/scripts/reset_local_onboarding.py --execute

Flags:
--dry-run  List the users that would be reset. Default.
--execute  Actually reset them, drop subscriptions, unlink platforms and flush Redis.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys
from urllib.parse import urlsplit

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import settings
from app.db.redis import redis_cache
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.services.onboarding.onboarding_service import reset_onboarding
from app.services.platform_link_service import linked_platforms_of

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
REDIS_DELETE_BATCH = 500


class NotALocalStackError(RuntimeError):
    """Raised when the configured Mongo or Redis is not on this machine."""


def is_local_url(url: str) -> bool:
    """Whether every host in a Mongo/Redis URL is a loopback address.

    Mongo URLs may list several ``host:port`` pairs separated by commas; all of
    them must be local. ``mongodb+srv://`` is a DNS seed list and is never local.
    """
    parts = urlsplit(url)
    if parts.scheme == "mongodb+srv":
        return False
    netloc = parts.netloc.rsplit("@", 1)[-1]
    hosts = [host.rsplit(":", 1)[0].strip("[]") for host in netloc.split(",")]
    return bool(hosts) and all(host in LOCAL_HOSTS for host in hosts)


def assert_local_stack(env: str, mongo_url: str, redis_url: str) -> None:
    """Fail loud unless the configured stack is the developer's own machine."""
    if env != "development":
        raise NotALocalStackError(f"ENV is {env!r}, not development")
    if not is_local_url(mongo_url):
        raise NotALocalStackError("MONGO_DB does not point at localhost")
    if not is_local_url(redis_url):
        raise NotALocalStackError("REDIS_URL does not point at localhost")


@dataclass
class ResetResult:
    dry_run: bool
    user_ids: list[str] = field(default_factory=list)
    users_reset: int = 0
    subscriptions_deleted: int = 0
    platforms_unlinked: int = 0
    redis_keys_deleted: int = 0


async def flush_local_redis() -> int:
    """Delete every key in the local Redis; returns how many went."""
    client = redis_cache.client
    keys = await client.keys("*")
    for start in range(0, len(keys), REDIS_DELETE_BATCH):
        await client.delete(*keys[start : start + REDIS_DELETE_BATCH])
    return len(keys)


async def unlink_every_platform(user_id: str) -> int:
    """Unlink every chat platform on the user; returns how many were linked."""
    user = await user_repository.get(user_id)
    if user is None:
        return 0
    platforms = list(linked_platforms_of(user))
    for platform in platforms:
        await user_repository.unlink_platform(user_id, platform)
    return len(platforms)


async def run_reset(*, dry_run: bool) -> ResetResult:
    """Reset onboarding state for every local user, then flush Redis (unless dry-run)."""
    assert_local_stack(settings.ENV, settings.MONGO_DB, settings.REDIS_URL)
    result = ResetResult(dry_run=dry_run, user_ids=await user_repository.list_all_ids())
    if dry_run:
        return result
    for user_id in result.user_ids:
        await reset_onboarding(user_id, keep_connections=True)
        result.users_reset += 1
        result.subscriptions_deleted += await subscription_repository.delete_all_for_user(user_id)
        result.platforms_unlinked += await unlink_every_platform(user_id)
    result.redis_keys_deleted = await flush_local_redis()
    return result


def _render(result: ResetResult) -> None:
    mode = "DRY RUN" if result.dry_run else "EXECUTED"
    print(f"[{mode}] local users: {len(result.user_ids)}")
    for user_id in result.user_ids:
        print(f"  {user_id}")
    if not result.dry_run:
        print(f"onboarding reset: {result.users_reset}")
        print(f"subscriptions deleted: {result.subscriptions_deleted}")
        print(f"platforms unlinked: {result.platforms_unlinked}")
        print(f"redis keys deleted: {result.redis_keys_deleted}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="reset every local user, drop subscriptions, unlink platforms and flush Redis",
    )
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args()

    result = await run_reset(dry_run=not args.execute)
    _render(result)

    if not args.execute:
        print("\nRe-run with --execute to reset these users.")


if __name__ == "__main__":
    asyncio.run(main())
