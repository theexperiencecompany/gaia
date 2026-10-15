"""What the multi-account migration keeps and revokes for one legacy record.

It deletes Composio accounts, so the plan is pinned case by case: the profile
call (identity) is the only seam mocked; the grouping and choices are real.
"""

import argparse
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
import itertools
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson import ObjectId
import pytest

from app.config.oauth_config import get_integration_by_id
from app.constants.integrations import ComposioAuthConfigSource
from app.models.integration_models import IntegrationAccount
from app.models.oauth_models import OAuthIntegration
from app.scripts import migrate_integration_accounts as migration
from app.scripts.migrate_integration_accounts import (
    _LegacyRecord,
    _Plan,
    _plan,
    connect_args_with_mode,
    migrate_connect_approvals,
)
from app.services.composio.auth_config_resolver import ResolvedAuthConfig
from app.services.hil.fingerprint import approval_fingerprint
from tests.integration_account_factories import make_integration_account, provider_account_id

EMAILS = {
    "ca_old": "me@gmail.com",
    "ca_new": "me@gmail.com",
    "ca_work": "work@acme.com",
    "ca_work_old": "work@acme.com",
    "ca_dead": "me@gmail.com",
    "ca_abandoned": "me@gmail.com",
    provider_account_id("acct_work"): "work@acme.com",
    provider_account_id("acct_me"): "me@gmail.com",
}


def _account(account_id: str, status: str = "ACTIVE", created: str = "2026-01-01") -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.status = status
    account.is_disabled = False
    account.created_at = f"{created}T00:00:00Z"
    return account


@pytest.fixture(autouse=True)
def identity() -> Iterator[AsyncMock]:
    async def profile(
        _user: str, _integration: OAuthIntegration, account_id: str
    ) -> dict[str, str]:
        return {"email": EMAILS[account_id]}

    with patch(
        "app.scripts.migrate_integration_accounts.fetch_account_identity",
        AsyncMock(side_effect=profile),
    ) as fetch:
        yield fetch


@pytest.fixture(autouse=True)
def gaia_ids() -> Iterator[None]:
    """Mint GAIA account ids in order (acct_1, acct_2, ...) so a plan reads deterministically."""
    minted = (f"acct_{n}" for n in itertools.count(1))
    with patch(
        "app.scripts.migrate_integration_accounts.new_account_id", side_effect=lambda: next(minted)
    ):
        yield


def _record(
    stored_id: str | None,
    status: str,
    tracked: list[IntegrationAccount],
    primary: str | None,
) -> _LegacyRecord:
    return _LegacyRecord.model_validate(
        {
            "_id": ObjectId(),
            "user_id": "u1",
            "integration_id": "gmail",
            "status": status,
            "connected_account_id": stored_id,
            "accounts": tracked,
            "primary_account_id": primary,
        }
    )


def _primary_provider_id(plan: _Plan) -> str | None:
    """Return the Composio account behind the plan's primary, which GAIA names by its own id."""
    return next((a.connected_account_id for a in plan.keep if a.id == plan.primary), None)


def _gmail() -> OAuthIntegration:
    gmail = get_integration_by_id("gmail")
    assert gmail is not None
    return gmail


async def test_reconnect_leftovers_of_one_identity_collapse_to_the_stored_account() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [], None),
        [_account("ca_old", created="2026-01-01"), _account("ca_new", created="2026-02-01")],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_old"]
    assert plan.revoke == ["ca_new"]
    assert _primary_provider_id(plan) == "ca_old"


async def test_two_real_mailboxes_both_survive_with_the_stored_one_primary() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_work", "connected", [], None),
        [_account("ca_old", created="2026-01-01"), _account("ca_work", created="2026-03-01")],
    )

    assert [(a.connected_account_id, a.label) for a in plan.keep] == [
        ("ca_old", "me@gmail.com"),
        ("ca_work", "work@acme.com"),
    ]
    assert plan.revoke == []
    assert _primary_provider_id(plan) == "ca_work"


async def test_dead_and_abandoned_accounts_are_revoked_but_a_disabled_one_is_left_alone() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [], None),
        [
            _account("ca_old"),
            _account("ca_dead", status="EXPIRED"),
            _account("ca_abandoned", status="INITIATED"),
            _account("ca_off", status="INACTIVE"),
        ],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_old"]
    assert sorted(plan.revoke) == ["ca_abandoned", "ca_dead"]


async def test_without_the_stored_account_the_newest_of_an_identity_is_kept() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_gone", "connected", [], None),
        [_account("ca_old", created="2026-01-01"), _account("ca_new", created="2026-02-01")],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_new"]
    assert plan.revoke == ["ca_old"]
    assert _primary_provider_id(plan) == "ca_new"


async def test_an_expired_integration_keeps_its_dead_account_so_reconnect_is_offered() -> None:
    before = datetime.now(UTC)
    plan = await _plan(
        _gmail(), _record("ca_dead", "expired", [], None), [_account("ca_dead", status="EXPIRED")]
    )
    after = datetime.now(UTC)

    [kept] = plan.keep
    assert (kept.connected_account_id, kept.status, kept.label) == (
        "ca_dead",
        "expired",
        "Gmail account 1",
    )
    assert kept.connected_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert kept.expired_at is not None
    assert before <= kept.expired_at <= after
    assert plan.revoke == []
    assert _primary_provider_id(plan) == "ca_dead"


async def test_the_kept_account_carries_the_identity_read_as_the_record_owner(
    identity: AsyncMock,
) -> None:
    gmail = _gmail()
    plan = await _plan(
        gmail,
        _record("ca_old", "connected", [], None),
        [
            _account("ca_old", created="2026-01-01"),
            _account("ca_new", created="2026-02-01"),
            _account("ca_dead", status="EXPIRED"),
        ],
    )

    assert identity.await_args_list == [call("u1", gmail, "ca_old"), call("u1", gmail, "ca_new")]
    assert plan.keep == [
        IntegrationAccount(
            id="acct_1",
            connected_account_id="ca_old",
            identity={"email": "me@gmail.com"},
            label="me@gmail.com",
            connected_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    ]


async def test_an_account_whose_identity_is_unreadable_is_kept_alone_and_reported(
    identity: AsyncMock, capsys: pytest.CaptureFixture[str]
) -> None:
    async def profile(
        _user: str, _integration: OAuthIntegration, account_id: str
    ) -> dict[str, str]:
        if account_id == "ca_new":
            raise RuntimeError("profile 500")
        return {"email": EMAILS[account_id]}

    identity.side_effect = profile
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [], None),
        [_account("ca_old", created="2026-01-01"), _account("ca_new", created="2026-02-01")],
    )

    assert [(a.connected_account_id, a.label, a.identity) for a in plan.keep] == [
        ("ca_old", "me@gmail.com", {"email": "me@gmail.com"}),
        ("ca_new", "Gmail account 2", {}),
    ]
    assert plan.revoke == []
    assert (
        capsys.readouterr().out
        == "  ! identity unavailable for ca_new: RuntimeError: profile 500\n"
    )


async def test_the_duplicates_of_every_identity_are_revoked() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [], None),
        [
            _account("ca_old", created="2026-01-01"),
            _account("ca_work_old", created="2026-01-15"),
            _account("ca_new", created="2026-02-01"),
            _account("ca_work", created="2026-03-01"),
        ],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_old", "ca_work"]
    assert plan.revoke == ["ca_new", "ca_work_old"]


async def test_an_expired_integration_with_a_live_account_left_revokes_its_dead_one() -> None:
    plan = await _plan(
        _gmail(),
        _record("ca_dead", "expired", [], None),
        [_account("ca_dead", status="EXPIRED"), _account("ca_new", created="2026-02-01")],
    )

    assert [(a.connected_account_id, a.status) for a in plan.keep] == [("ca_new", "connected")]
    assert plan.revoke == ["ca_dead"]
    assert _primary_provider_id(plan) == "ca_new"


async def test_an_expired_integration_whose_account_composio_dropped_keeps_nothing() -> None:
    plan = await _plan(
        _gmail(), _record("ca_gone", "expired", [], None), [_account("ca_off", status="INACTIVE")]
    )

    assert plan.keep == []
    assert plan.revoke == []
    assert plan.primary is None


async def test_a_record_that_gained_accounts_keeps_them_and_folds_in_its_live_legacy_one() -> None:
    work = make_integration_account("acct_work", label="Work").model_copy(
        update={"connected_at": datetime(2025, 12, 1, tzinfo=UTC)}
    )
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [work], "acct_work"),
        [_account(work.connected_account_id, created="2025-12-01"), _account("ca_old")],
    )

    assert [(a.id, a.connected_account_id, a.label) for a in plan.keep] == [
        ("acct_work", work.connected_account_id, "Work"),
        ("acct_1", "ca_old", "me@gmail.com"),
    ]
    assert plan.revoke == []
    assert plan.primary == "acct_work"


async def test_untracked_copies_of_every_tracked_identity_are_revoked() -> None:
    me = make_integration_account("acct_me")
    work = make_integration_account("acct_work")
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [me, work], "acct_me"),
        [
            _account("ca_old"),
            _account(me.connected_account_id, created="2026-02-01"),
            _account("ca_work_old", created="2026-03-01"),
            _account(work.connected_account_id, created="2026-04-01"),
        ],
    )

    assert plan.keep == [me, work]
    assert plan.revoke == ["ca_old", "ca_work_old"]
    assert plan.primary == "acct_me"


async def test_a_tracked_account_composio_reports_dead_stays_as_gaia_has_it() -> None:
    expired = make_integration_account("acct_work", "expired")
    plan = await _plan(
        _gmail(),
        _record("ca_old", "connected", [expired], "acct_work"),
        [_account("ca_old"), _account(expired.connected_account_id, status="EXPIRED")],
    )

    assert [a.id for a in plan.keep] == ["acct_1", "acct_work"]
    assert plan.keep[1] == expired
    assert plan.revoke == []
    assert plan.primary == "acct_work"


async def test_unnamed_accounts_are_numbered_after_the_tracked_ones() -> None:
    first = make_integration_account("acct_first", label="Gmail account 2").model_copy(
        update={"connected_at": datetime(2025, 12, 1, tzinfo=UTC)}
    )
    plan = await _plan(
        _gmail(),
        _record(None, "connected", [first], "acct_first"),
        [
            _account(first.connected_account_id, created="2025-12-01"),
            _account("ca_unnamed_a", created="2026-02-01"),
            _account("ca_unnamed_b", created="2026-03-01"),
        ],
    )

    assert [a.label for a in plan.keep] == ["Gmail account 2", "Gmail account 3", "Gmail account 4"]


@pytest.mark.parametrize(
    ("stored", "migrated"),
    [
        (
            {"integration_ids": ["gmail"], "force_reconnect": True},
            {"integration_ids": ["gmail"], "mode": "reconnect"},
        ),
        ({"integration_ids": ["gmail"], "force_reconnect": False}, {"integration_ids": ["gmail"]}),
    ],
    ids=["reconnect", "plain_connect"],
)
def test_a_stored_connect_approval_keeps_what_it_asked_for(
    stored: dict[str, object], migrated: dict[str, object]
) -> None:
    assert connect_args_with_mode(stored) == migrated


async def _cursor(rows: list[dict[str, object]]) -> AsyncIterator[dict[str, object]]:
    for row in rows:
        yield row


def _approvals(*rows: dict[str, object]) -> MagicMock:
    """Fake the approval_ledger slice the rewrite touches: find's cursor and update_one."""
    approvals = MagicMock()
    approvals.find.return_value = _cursor(list(rows))
    approvals.update_one = AsyncMock()
    return approvals


async def test_live_connect_approvals_are_rewritten_with_a_matching_fingerprint() -> None:
    row_id = ObjectId()
    approvals = _approvals(
        {"_id": row_id, "args": {"integration_ids": ["gmail"], "force_reconnect": True}}
    )

    count = await migrate_connect_approvals(approvals, apply=True)

    assert count == 1
    approvals.find.assert_called_once_with(
        {
            "tool_name": "connect_integration",
            "state": {"$in": ["approved", "pending"]},
            "args.force_reconnect": {"$exists": True},
        }
    )
    new_args = {"integration_ids": ["gmail"], "mode": "reconnect"}
    approvals.update_one.assert_awaited_once_with(
        {"_id": row_id},
        {
            "$set": {
                "args": new_args,
                "fingerprint": approval_fingerprint("connect_integration", new_args),
            }
        },
    )


async def test_an_approval_for_a_named_account_keeps_it_in_the_fingerprint() -> None:
    approvals = _approvals(
        {
            "_id": ObjectId(),
            "args": {"integration_ids": ["gmail"], "force_reconnect": True},
            "account": "Work",
        }
    )

    await migrate_connect_approvals(approvals, apply=True)

    new_args = {"integration_ids": ["gmail"], "mode": "reconnect"}
    fingerprint = approvals.update_one.await_args.args[1]["$set"]["fingerprint"]
    assert fingerprint == approval_fingerprint("connect_integration", new_args, "Work")


async def test_a_dry_run_counts_the_approvals_and_writes_nothing() -> None:
    approvals = _approvals(
        {"_id": ObjectId(), "args": {"integration_ids": ["slack"], "force_reconnect": False}},
        {"_id": ObjectId(), "args": {"integration_ids": ["gmail"], "force_reconnect": True}},
    )

    assert await migrate_connect_approvals(approvals, apply=False) == 2
    approvals.update_one.assert_not_awaited()


async def test_the_run_migrates_only_resolvable_integrations_through_their_resolved_auth_config() -> (
    None
):
    """A stored or env auth config replaces the catalog one; an unresolvable integration is skipped."""
    legacy = {"_id": ObjectId(), "user_id": "u1", "integration_id": "gmail", "status": "created"}
    database = MagicMock()
    database.user_integrations.find.return_value = _cursor([legacy])
    database.approval_ledger = _approvals()
    database.users.count_documents = AsyncMock(return_value=0)
    resolved = {"gmail": ResolvedAuthConfig("ac_stored", ComposioAuthConfigSource.STORED)}
    with (
        patch.object(migration, "capture_running_loop"),
        patch.object(migration, "init_composio_service"),
        patch.object(migration, "MongoDB", return_value=MagicMock(database=database)),
        patch.object(migration, "resolve_auth_configs", AsyncMock(return_value=resolved)),
        patch.object(migration, "_migrate_document", AsyncMock()) as migrate_document,
    ):
        await migration._run(argparse.Namespace(apply=False))

    query = database.user_integrations.find.call_args.args[0]
    assert query["integration_id"] == {"$in": ["gmail"]}
    doc, integration, auth_config_id, _totals, apply = migrate_document.await_args.args
    assert (doc.id, integration.id, auth_config_id, apply) == (
        legacy["_id"],
        "gmail",
        "ac_stored",
        False,
    )
