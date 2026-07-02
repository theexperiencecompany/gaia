"""One-time, idempotent reseed of Composio integration triggers.

Fixes two production problems in one pass:

1. **Stale trigger ids.** Workflows store the Composio trigger nano-id in
   `trigger_config.composio_trigger_ids`, but reconnects recreate triggers on
   Composio's side, leaving many workflows pointing at ids that no longer
   exist — those workflows never fire. Re-creating the trigger (Composio
   upserts per user+slug+config) returns the current live id, which is
   written back to the workflow.

2. **Per-email aggressiveness of Gmail system workflows.** The auto-provisioned
   "Inbox Triage" / "Auto-Draft Replies" workflows fire one full agent run per
   inbound email. Their triggers are re-created with a `labelIds` filter
   (default: IMPORTANT) so Composio only fires for mail Gmail marks important.
   The filter lives entirely in Composio's trigger config — no workflow schema
   or API changes needed.

Finally, Composio triggers that remain referenced by no workflow (orphans from
deletes/reconnects) are removed so they stop generating dead webhooks.

Dry-run by default; pass --apply to write. Safe to re-run: an already-reseeded
workflow upserts to the same trigger id and nothing changes.

Run from repo root:
    cd apps/api && uv run python scripts/reseed_system_triggers.py           # dry-run
    cd apps/api && uv run python scripts/reseed_system_triggers.py --apply
"""

import argparse
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# In the production container, Infisical credentials live in docker secrets and
# are exported by the entrypoint — exec'd scripts must load them themselves.
_SECRET_ENV = {
    "INFISICAL_TOKEN": "gaia_infisical_token",
    "INFISICAL_PROJECT_ID": "gaia_infisical_project_id",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_ID": "gaia_infisical_machine_identity_client_id",
    "INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET": "gaia_infisical_machine_identity_client_secret",
}
for _env, _file in _SECRET_ENV.items():
    _p = Path("/run/secrets") / _file
    if _p.exists() and not os.environ.get(_env):
        os.environ[_env] = _p.read_text().strip()

from composio import Composio  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.db.mongodb.collections import workflows_collection  # noqa: E402

GMAIL_SLUG = "GMAIL_NEW_GMAIL_MESSAGE"
CALENDAR_STARTING_SOON_SLUG = "GOOGLECALENDAR_EVENT_STARTING_SOON_TRIGGER"

# trigger_name -> Composio toolkit slug (for the active-connection guard)
TOOLKIT_FOR_TRIGGER = {
    "gmail_poll_inbox": "gmail",
    "calendar_event_starting_soon": "googlecalendar",
}


def list_active_trigger_ids(client: Composio) -> set[str]:
    """All trigger nano-ids currently active on Composio (paginated)."""
    ids: set[str] = set()
    cursor: str | None = None
    for _ in range(100):
        kwargs: dict = {"limit": 100}
        if cursor:
            kwargs["cursor"] = cursor
        res = client.triggers.list_active(**kwargs)
        items = list(getattr(res, "items", res) or [])
        for t in items:
            tid = getattr(t, "id", None)
            if tid:
                ids.add(tid)
        cursor = getattr(res, "next_cursor", None)
        if not items or not cursor:
            break
    return ids


class ConnectionGuard:
    """Per-user cache of which toolkits have an ACTIVE Composio connection."""

    def __init__(self, client: Composio):
        self._client = client
        self._cache: dict[str, set[str]] = {}

    def active_toolkits(self, user_id: str) -> set[str]:
        if user_id not in self._cache:
            toolkits: set[str] = set()
            try:
                accounts = self._client.connected_accounts.list(user_ids=[user_id])
                for acc in getattr(accounts, "items", []) or []:
                    if getattr(acc, "status", "") == "ACTIVE":
                        toolkit = getattr(getattr(acc, "toolkit", None), "slug", None)
                        if toolkit:
                            toolkits.add(toolkit)
            except Exception as e:
                print(f"    WARN connected_accounts.list failed for {user_id}: {e}")
            self._cache[user_id] = toolkits
        return self._cache[user_id]

    def has(self, user_id: str, trigger_name: str) -> bool:
        toolkit = TOOLKIT_FOR_TRIGGER.get(trigger_name)
        return toolkit in self.active_toolkits(user_id) if toolkit else False


def create_trigger(client: Composio, user_id: str, slug: str, config: dict) -> str | None:
    """Create (upsert) a Composio trigger; returns its nano-id."""
    result = client.triggers.create(user_id=user_id, slug=slug, trigger_config=config)
    return getattr(result, "trigger_id", None)


def expand_all_calendars(user_id: str) -> list[str]:
    """Expand calendar_ids=["all"] exactly like CalendarTriggerHandler._fetch_user_calendars."""
    try:
        from app.services import calendar_service

        calendars = calendar_service.list_calendars(user_id)
        if isinstance(calendars, dict) and "items" in calendars:
            return [cal.get("id", "primary") for cal in calendars["items"] if cal.get("id")]
        return ["primary"]
    except Exception as e:
        print(f"    WARN could not list calendars for {user_id} ({e}); falling back to primary")
        return ["primary"]


async def other_workflows_reference(trigger_id: str, excluding_workflow_id: str) -> bool:
    n = await workflows_collection.count_documents(
        {
            "_id": {"$ne": excluding_workflow_id},
            "trigger_config.composio_trigger_ids": trigger_id,
        }
    )
    return n > 0


async def reseed_gmail_system(
    client: Composio, guard: ConnectionGuard, label: str, apply: bool
) -> tuple[int, int, int]:
    """Re-create Gmail system-workflow triggers with a labelIds filter."""
    print("\n== SECTION 1: Gmail system workflows -> filtered poll trigger ==")
    query = {
        "is_system_workflow": True,
        "activated": True,
        "trigger_config.trigger_name": "gmail_poll_inbox",
        "trigger_config.enabled": True,
    }
    updated = unchanged = skipped = 0
    async for wf in workflows_collection.find(query):
        wf_id, user_id = wf["_id"], wf["user_id"]
        tc = wf.get("trigger_config") or {}
        old_ids: list[str] = tc.get("composio_trigger_ids") or []
        interval = ((tc.get("trigger_data") or {}).get("interval")) or 15

        if not guard.has(user_id, "gmail_poll_inbox"):
            print(f"  SKIP {wf_id} ({wf.get('title')}): no active gmail connection")
            skipped += 1
            continue

        config = {"interval": interval, "labelIds": label, "user_id": "me"}
        if not apply:
            print(
                f"  DRY  {wf_id} ({wf.get('title')}): would create {GMAIL_SLUG} {config}, replace {old_ids}"
            )
            updated += 1
            continue

        new_id = create_trigger(client, user_id, GMAIL_SLUG, config)
        if not new_id:
            print(f"  FAIL {wf_id}: trigger create returned no id")
            skipped += 1
            continue
        if old_ids == [new_id]:
            unchanged += 1
            continue
        await workflows_collection.update_one(
            {"_id": wf_id}, {"$set": {"trigger_config.composio_trigger_ids": [new_id]}}
        )
        for old in old_ids:
            if old != new_id and not await other_workflows_reference(old, wf_id):
                try:
                    client.triggers.delete(trigger_id=old)
                except Exception as e:
                    print(f"    WARN could not delete old trigger {old}: {e}")
        print(f"  OK   {wf_id} ({wf.get('title')}): {old_ids} -> [{new_id}]")
        updated += 1
    print(f"  gmail: updated={updated} unchanged={unchanged} skipped={skipped}")
    return updated, unchanged, skipped


async def reregister_stale_calendar(
    client: Composio, guard: ConnectionGuard, active_ids: set[str], apply: bool
) -> tuple[int, int]:
    """Re-create calendar starting-soon triggers whose stored ids are no longer live."""
    print("\n== SECTION 2: stale calendar_event_starting_soon workflows ==")
    query = {
        "activated": True,
        "trigger_config.trigger_name": "calendar_event_starting_soon",
        "trigger_config.enabled": True,
        "trigger_config.composio_trigger_ids": {"$exists": True, "$ne": None, "$not": {"$size": 0}},
    }
    fixed = skipped = 0
    async for wf in workflows_collection.find(query):
        wf_id, user_id = wf["_id"], wf["user_id"]
        tc = wf.get("trigger_config") or {}
        old_ids: list[str] = tc.get("composio_trigger_ids") or []
        if any(i in active_ids for i in old_ids):
            continue  # still live — nothing to fix

        if not guard.has(user_id, "calendar_event_starting_soon"):
            print(f"  SKIP {wf_id} ({wf.get('title')}): no active googlecalendar connection")
            skipped += 1
            continue

        td = tc.get("trigger_data") or {}
        calendar_ids = td.get("calendar_ids") or ["primary"]
        if calendar_ids == ["all"]:
            calendar_ids = expand_all_calendars(user_id)
        new_ids: list[str] = []
        configs = [
            {
                "calendarId": cid,
                "countdown_window_minutes": td.get("minutes_before_start", 10),
                "include_all_day": td.get("include_all_day", False),
            }
            for cid in calendar_ids
        ]
        if not apply:
            print(
                f"  DRY  {wf_id} ({wf.get('title')}): would create {len(configs)}x {CALENDAR_STARTING_SOON_SLUG}, replace {old_ids}"
            )
            fixed += 1
            continue

        ok = True
        for config in configs:
            new_id = create_trigger(client, user_id, CALENDAR_STARTING_SOON_SLUG, config)
            if new_id:
                new_ids.append(new_id)
            else:
                ok = False
        if not ok or not new_ids:
            print(f"  FAIL {wf_id}: trigger create failed")
            skipped += 1
            continue
        await workflows_collection.update_one(
            {"_id": wf_id}, {"$set": {"trigger_config.composio_trigger_ids": new_ids}}
        )
        print(f"  OK   {wf_id} ({wf.get('title')}): {old_ids} -> {new_ids}")
        fixed += 1
    print(f"  calendar: fixed={fixed} skipped={skipped}")
    return fixed, skipped


async def delete_orphans(client: Composio, apply: bool) -> int:
    """Delete active Composio triggers referenced by no workflow."""
    print("\n== SECTION 3: orphan Composio triggers ==")
    active = list_active_trigger_ids(client)
    stored: set[str] = set()
    async for wf in workflows_collection.find(
        {"trigger_config.composio_trigger_ids": {"$exists": True, "$ne": None}}
    ):
        stored.update((wf.get("trigger_config") or {}).get("composio_trigger_ids") or [])
    orphans = sorted(active - stored)
    print(f"  active={len(active)} referenced={len(active & stored)} orphans={len(orphans)}")
    if not apply:
        print(f"  DRY  would delete {len(orphans)} orphan trigger(s)")
        return len(orphans)
    deleted = 0
    for tid in orphans:
        try:
            client.triggers.delete(trigger_id=tid)
            deleted += 1
        except Exception as e:
            print(f"    WARN could not delete {tid}: {e}")
    print(f"  deleted {deleted}/{len(orphans)} orphan trigger(s)")
    return deleted


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write changes (requires --yes; default: dry-run)"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm writes; --apply without --yes aborts (accidental-apply guard)",
    )
    parser.add_argument(
        "--label",
        default="IMPORTANT",
        help="Gmail labelIds filter for system poll triggers (default: IMPORTANT)",
    )
    parser.add_argument("--skip-orphans", action="store_true", help="skip orphan deletion pass")
    args = parser.parse_args()

    if args.apply and not args.yes:
        print("ABORT: --apply requires --yes. Run without --apply first and review the dry-run.")
        raise SystemExit(2)

    client = Composio(api_key=settings.COMPOSIO_KEY)
    guard = ConnectionGuard(client)
    mode = "APPLY" if args.apply else "DRY-RUN (no writes will be performed)"
    print(f"reseed_system_triggers — mode: {mode}, gmail label filter: {args.label!r}")

    active_ids = list_active_trigger_ids(client)
    await reseed_gmail_system(client, guard, args.label, args.apply)
    await reregister_stale_calendar(client, guard, active_ids, args.apply)
    if not args.skip_orphans:
        # Orphans are recomputed AFTER the sections above so freshly re-adopted
        # or replaced ids are classified against the post-reseed state.
        await delete_orphans(client, args.apply)
    print(f"\ndone ({mode}).")


if __name__ == "__main__":
    asyncio.run(main())
