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
- on a record that gained accounts before this ran (a connect after the deploy),
  keeps those accounts and their GAIA ids as they are, folds the legacy account
  in only when it is live and not one of their identities, and revokes nothing
  they track;
- subscribes every kept account to the integration's account-level triggers
  and re-registers workflow triggers on the primary.

It also drops the retired users.provider_metadata field, and moves live
connect_integration approvals off the retired force_reconnect argument (a
reconnect becomes mode=reconnect), so one approved after the deploy still
reconnects instead of answering "already connected".

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

from app.config.settings import settings
from app.constants.integrations import (
    COMPOSIO_ACCOUNT_LIST_LIMIT,
    CONNECT_INTEGRATION_TOOL,
    ConnectMode,
)
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB
from app.db.repositories.user_integrations import user_integration_repository
from app.models.hil_models import LIVE_LEDGER_STATES
from app.models.integration_models import IntegrationAccount, new_account_id
from app.models.oauth_models import OAuthIntegration
from app.services.composio.auth_config_resolver import (
    composio_integrations,
    resolve_auth_configs,
)
from app.services.composio.composio_service import get_composio_service, init_composio_service
from app.services.hil.fingerprint import approval_fingerprint
from app.services.integrations.account_identity import account_label, fetch_account_identity
from app.services.integrations.integration_account_lifecycle import resync_primary_bound_triggers
from app.services.integrations.integration_accounts import derive_status, pick_primary
from app.utils.concurrency import capture_running_loop

_LIVE = "ACTIVE"
_UNTOUCHED = frozenset({"INACTIVE"})


class _LegacyRecord(BaseModel):
    """A user_integrations document still carrying the single stored account id, with any accounts it gained."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True, arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")
    user_id: str
    integration_id: str
    status: str = "created"
    connected_account_id: str | None = None
    accounts: list[IntegrationAccount] = Field(default_factory=list)
    primary_account_id: str | None = None


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


async def _identity(user_id: str, integration: OAuthIntegration, account_id: str) -> dict[str, str]:
    try:
        return await fetch_account_identity(user_id, integration, account_id)
    except Exception as e:
        print(f"  ! identity unavailable for {account_id}: {type(e).__name__}: {e}")
        return {}


async def _plan(
    integration: OAuthIntegration, record: _LegacyRecord, composio_accounts: list[Item]
) -> _Plan:
    plan = _Plan()
    user_id, stored_id, tracked = record.user_id, record.connected_account_id, record.accounts
    held = {a.connected_account_id: a for a in tracked}
    live = sorted(
        (a for a in composio_accounts if a.status == _LIVE and not a.is_disabled),
        key=lambda a: datetime.fromisoformat(a.created_at),
    )
    by_identity: dict[str, list[tuple[Item, dict[str, str]]]] = {}
    for account in live:
        identity = await _identity(user_id, integration, account.id)
        # No identity means duplicates cannot be told apart, so each stands alone.
        key = repr(sorted(identity.items())) if identity else account.id
        by_identity.setdefault(key, []).append((account, identity))

    taken = {a.label for a in tracked}
    for group in by_identity.values():
        if any(a.id in held for a, _ in group):
            plan.revoke += [a.id for a, _ in group if a.id not in held]
            continue
        chosen, identity = next(((a, i) for a, i in group if a.id == stored_id), group[-1])
        label = account_label(integration, identity, taken)
        taken.add(label)
        plan.keep.append(
            IntegrationAccount(
                id=new_account_id(),
                connected_account_id=chosen.id,
                identity=identity,
                label=label,
                connected_at=datetime.fromisoformat(chosen.created_at),
            )
        )
        plan.revoke += [a.id for a, _ in group if a.id != chosen.id]

    # Every account the record tracks stays as GAIA has it, live on Composio or not.
    plan.keep += tracked
    kept_ids = {k.connected_account_id for k in plan.keep}
    if not plan.keep and record.status == "expired" and stored_id:
        stored = next((a for a in composio_accounts if a.id == stored_id), None)
        if stored is not None:
            plan.keep.append(
                IntegrationAccount(
                    id=new_account_id(),
                    connected_account_id=stored.id,
                    # Equivalent under mutation: account_label treats a None identity as {}.
                    label=account_label(integration, {}, set()),  # pragma: no mutate
                    status="expired",
                    connected_at=datetime.fromisoformat(stored.created_at),
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
    # The legacy record named its account by Composio's id; the primary is now GAIA's.
    stored_primary = record.primary_account_id or next(
        (k.id for k in plan.keep if k.connected_account_id == stored_id), None
    )
    plan.primary = pick_primary(plan.keep, stored_primary)
    return plan


async def _migrate_document(
    doc: _LegacyRecord,
    integration: OAuthIntegration,
    auth_config_id: str,
    totals: _Totals,
    apply: bool,
) -> None:
    user_id = doc.user_id
    composio = get_composio_service()
    listing = await asyncio.to_thread(
        composio.composio.connected_accounts.list,
        user_ids=[user_id],
        auth_config_ids=[auth_config_id],
        limit=COMPOSIO_ACCOUNT_LIST_LIMIT,
    )
    plan = await _plan(integration, doc, listing.items)

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
    await user_integration_repository.replace_legacy_account(
        user_id,
        integration.id,
        accounts=plan.keep,
        primary_account_id=plan.primary,
        status=derive_status(plan.keep) if plan.keep else "created",
    )
    already_subscribed = {a.connected_account_id for a in doc.accounts}
    for account in plan.keep:
        if account.connected_account_id in already_subscribed:
            continue
        if account.status == "connected" and integration.associated_triggers:
            await composio.handle_subscribe_trigger(
                user_id, account.connected_account_id, integration.associated_triggers
            )
    # Workflow triggers sat on whichever account Composio picked, possibly one just revoked.
    if plan.primary is not None and plan.primary != doc.primary_account_id:
        await resync_primary_bound_triggers(user_id, integration)


_RETIRED_CONNECT_ARG = "force_reconnect"


class _LegacyConnectApproval(BaseModel):
    """A live connect_integration approval stored before mode replaced force_reconnect."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    id: ObjectId = Field(alias="_id")
    args: dict[str, object]
    account: str | None = None


def connect_args_with_mode(args: dict[str, object]) -> dict[str, object]:
    """Return connect_integration args with force_reconnect replaced by the mode it meant."""
    migrated = {k: v for k, v in args.items() if k != _RETIRED_CONNECT_ARG}
    if args.get(_RETIRED_CONNECT_ARG) is True:
        migrated["mode"] = str(ConnectMode.RECONNECT)
    return migrated


async def migrate_connect_approvals(approvals: AsyncIOMotorCollection, *, apply: bool) -> int:
    """Rewrite each live connect approval still carrying force_reconnect; return how many."""
    cursor = approvals.find(
        {
            "tool_name": CONNECT_INTEGRATION_TOOL,
            "state": {"$in": sorted(str(s) for s in LIVE_LEDGER_STATES)},
            f"args.{_RETIRED_CONNECT_ARG}": {"$exists": True},
        }
    )
    count = 0
    async for raw in cursor:
        row = _LegacyConnectApproval.model_validate(raw)
        args = connect_args_with_mode(row.args)
        count += 1
        if apply:
            await approvals.update_one(
                {"_id": row.id},
                {
                    "$set": {
                        "args": args,
                        # The dedup id is the call's exact bytes, so it moves with them.
                        "fingerprint": approval_fingerprint(
                            CONNECT_INTEGRATION_TOOL, args, row.account
                        ),
                    }
                },
            )
    return count


async def _run(args: argparse.Namespace) -> None:
    capture_running_loop()
    init_composio_service()
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    user_integrations = database.user_integrations
    resolved = await resolve_auth_configs()
    integrations_to_migrate = {
        i.id: (i, resolved[i.id].auth_config_id)
        for i in composio_integrations()
        if i.id in resolved
    }

    totals = _Totals()
    cursor = user_integrations.find(
        {
            "integration_id": {"$in": list(integrations_to_migrate)},
            "$or": [
                {"accounts.0": {"$exists": False}},
                {"connected_account_id": {"$exists": True}},
            ],
        }
    )
    async for raw in cursor:
        doc = _LegacyRecord.model_validate(raw)
        integration, auth_config_id = integrations_to_migrate[doc.integration_id]
        try:
            await _migrate_document(doc, integration, auth_config_id, totals, args.apply)
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

    connect_approvals = await migrate_connect_approvals(database.approval_ledger, apply=args.apply)
    print(f"live connect approvals moved off force_reconnect: {connect_approvals}")

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
