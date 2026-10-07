#!/usr/bin/env python3
"""Move Composio connections onto the multi-account model.

Before multi-account, a user_integrations document held one connected_account_id
while every connect minted a fresh Composio account (link with allow_multiple),
so Composio accumulated reconnect leftovers: expired and abandoned accounts, and
live duplicates of the same identity. Tools then ran as whichever one Composio
picked.

Per Composio integration document this:

- reads every account Composio holds for the user on that auth config;
- keeps one live account per identity (the stored one when it is among them,
  else the newest), so a user who really linked two mailboxes keeps both;
- keeps the stored account as expired when the integration had expired and no
  live account is left, so the UI still offers Reconnect;
- revokes the rest (live duplicates, expired, failed, abandoned) on Composio;
  INACTIVE accounts were switched off on purpose and are left untouched;
- writes accounts + primary_account_id and drops the legacy field;
- subscribes every kept account to the integration's account-level triggers
  and re-registers workflow triggers on the primary.

It also drops the retired users.provider_metadata field.

Dry run by default. Nothing is written or revoked without ``--apply``.

Usage::

    cd apps/api
    uv run python -m app.scripts.migrate_integration_accounts            # report only
    uv run python -m app.scripts.migrate_integration_accounts --apply
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bson import ObjectId
from composio_client.types.connected_account_list_response import Item
from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import BaseModel, ConfigDict, Field

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.config.settings import settings
from app.constants.integrations import COMPOSIO_ACCOUNT_LIST_LIMIT
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.models.integration_models import IntegrationAccount
from app.models.oauth_models import OAuthIntegration
from app.services.composio.composio_service import get_composio_service, init_composio_service
from app.services.integrations.account_identity import account_label, fetch_account_identity
from app.services.integrations.integration_account_lifecycle import resync_primary_bound_triggers
from app.services.integrations.integration_accounts import derive_status, pick_primary
from app.utils.concurrency import capture_running_loop

_LIVE = "ACTIVE"
_UNTOUCHED = frozenset({"INACTIVE"})


class _LegacyRecord(BaseModel):
    """A user_integrations document as it stood before accounts: one stored account id."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")
    user_id: str
    integration_id: str
    status: str = "created"
    connected_account_id: str | None = None


@dataclass
class _Plan:
    keep: list[IntegrationAccount] = field(default_factory=list)
    revoke: list[str] = field(default_factory=list)
    primary: str | None = None


@dataclass
class _Totals:
    documents: int = 0
    accounts_kept: int = 0
    multi_account_documents: int = 0
    revoked: int = 0
    failures: list[str] = field(default_factory=list)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _identity(user_id: str, integration: OAuthIntegration, account_id: str) -> dict[str, str]:
    try:
        return await fetch_account_identity(user_id, integration, account_id)
    except Exception as e:
        print(f"  ! identity unavailable for {account_id}: {type(e).__name__}: {e}")
        return {}


async def _plan(
    user_id: str,
    integration: OAuthIntegration,
    stored_id: str | None,
    record_status: str,
    composio_accounts: list[Item],
) -> _Plan:
    plan = _Plan()
    live = sorted(
        (a for a in composio_accounts if a.status == _LIVE and not a.is_disabled),
        key=lambda a: _parse_time(a.created_at),
    )
    by_identity: dict[str, list[tuple[Item, dict[str, str]]]] = {}
    for account in live:
        identity = await _identity(user_id, integration, account.id)
        # No identity means duplicates cannot be told apart, so each stands alone.
        key = repr(sorted(identity.items())) if identity else account.id
        by_identity.setdefault(key, []).append((account, identity))

    for group in by_identity.values():
        chosen, identity = next(((a, i) for a, i in group if a.id == stored_id), group[-1])
        plan.keep.append(
            IntegrationAccount(
                connected_account_id=chosen.id,
                identity=identity,
                label=account_label(integration, identity, {k.label for k in plan.keep}),
                connected_at=_parse_time(chosen.created_at),
            )
        )
        plan.revoke += [a.id for a, _ in group if a.id != chosen.id]

    kept_ids = {k.connected_account_id for k in plan.keep}
    if not plan.keep and record_status == "expired" and stored_id:
        stored = next((a for a in composio_accounts if a.id == stored_id), None)
        if stored is not None:
            plan.keep.append(
                IntegrationAccount(
                    connected_account_id=stored.id,
                    label=account_label(integration, {}, set()),
                    status="expired",
                    connected_at=_parse_time(stored.created_at),
                    expired_at=datetime.now(UTC),
                )
            )
            kept_ids.add(stored.id)

    plan.revoke += [
        a.id
        for a in composio_accounts
        if a.id not in kept_ids and a.status != _LIVE and a.status not in _UNTOUCHED
    ]
    plan.keep.sort(key=lambda a: a.connected_at)
    plan.primary = pick_primary(plan.keep, stored_id)
    return plan


async def _migrate_document(
    doc: _LegacyRecord,
    integration: OAuthIntegration,
    auth_config_id: str,
    totals: _Totals,
    apply: bool,
    collection: AsyncIOMotorCollection[dict[str, object]],
) -> None:
    user_id = doc.user_id
    stored_id = doc.connected_account_id
    composio = get_composio_service()
    listing = await asyncio.to_thread(
        composio.composio.connected_accounts.list,
        user_ids=[user_id],
        auth_config_ids=[auth_config_id],
        limit=COMPOSIO_ACCOUNT_LIST_LIMIT,
    )
    plan = await _plan(user_id, integration, stored_id, doc.status, listing.items)

    totals.documents += 1
    totals.accounts_kept += len(plan.keep)
    totals.revoked += len(plan.revoke)
    if len(plan.keep) > 1:
        totals.multi_account_documents += 1
    print(
        f"{user_id} {integration.id}: keep {len(plan.keep)} "
        f"({', '.join(a.label for a in plan.keep) or '-'}), revoke {len(plan.revoke)}"
    )
    if not apply:
        return

    for account_id in plan.revoke:
        await composio.delete_connected_account(account_id)
    await collection.update_one(
        {"_id": doc.id},
        {
            "$set": {
                "accounts": [a.model_dump() for a in plan.keep],
                "primary_account_id": plan.primary,
                "status": derive_status(plan.keep) if plan.keep else "created",
            },
            "$unset": {"connected_account_id": ""},
        },
    )
    for account in plan.keep:
        if account.status == "connected" and integration.associated_triggers:
            await composio.handle_subscribe_trigger(
                user_id, account.connected_account_id, integration.associated_triggers
            )
    # Workflow triggers sat on whichever account Composio picked, possibly one just revoked.
    if plan.primary is not None:
        await resync_primary_bound_triggers(user_id, integration)


async def _run(args: argparse.Namespace) -> None:
    capture_running_loop()
    init_composio_service()
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    user_integrations = database.user_integrations
    composio_integrations = {
        i.id: (i, i.composio_config.auth_config_id) for i in OAUTH_INTEGRATIONS if i.composio_config
    }

    totals = _Totals()
    cursor = user_integrations.find(
        {
            "integration_id": {"$in": list(composio_integrations)},
            "accounts.0": {"$exists": False},
        }
    )
    async for raw in cursor:
        doc = _LegacyRecord.model_validate(raw)
        integration, auth_config_id = composio_integrations[doc.integration_id]
        try:
            await _migrate_document(
                doc, integration, auth_config_id, totals, args.apply, user_integrations
            )
        except Exception as e:
            totals.failures.append(f"{doc.user_id} {integration.id}: {e}")

    print(
        f"\ndocuments: {totals.documents}  accounts kept: {totals.accounts_kept}  "
        f"multi-account: {totals.multi_account_documents}  revoked: {totals.revoked}"
    )
    if totals.failures:
        print(f"\nFAILED ({len(totals.failures)}):")
        for failure in totals.failures:
            print(f"  {failure}")

    users_with_metadata = await database.users.count_documents(
        {"provider_metadata": {"$exists": True}}
    )
    print(f"users carrying the retired provider_metadata field: {users_with_metadata}")
    if not args.apply:
        print("\ndry run: nothing written or revoked. Re-run with --apply.")
        return
    await database.users.update_many(
        {"provider_metadata": {"$exists": True}}, {"$unset": {"provider_metadata": ""}}
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write and revoke; default is report-only."
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
