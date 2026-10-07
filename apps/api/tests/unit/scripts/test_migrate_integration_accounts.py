"""What the multi-account migration keeps and revokes for one legacy record.

It deletes Composio accounts, so the plan is pinned case by case: the profile
call (identity) is the only seam mocked; the grouping and choices are real.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.oauth_config import get_integration_by_id
from app.models.oauth_models import OAuthIntegration
from app.scripts.migrate_integration_accounts import _plan

EMAILS = {
    "ca_old": "me@gmail.com",
    "ca_new": "me@gmail.com",
    "ca_work": "work@acme.com",
    "ca_dead": "me@gmail.com",
    "ca_abandoned": "me@gmail.com",
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


def _gmail() -> OAuthIntegration:
    gmail = get_integration_by_id("gmail")
    assert gmail is not None
    return gmail


async def test_reconnect_leftovers_of_one_identity_collapse_to_the_stored_account() -> None:
    plan = await _plan(
        "u1",
        _gmail(),
        "ca_old",
        "connected",
        [_account("ca_old", created="2026-01-01"), _account("ca_new", created="2026-02-01")],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_old"]
    assert plan.revoke == ["ca_new"]
    assert plan.primary == "ca_old"


async def test_two_real_mailboxes_both_survive_with_the_stored_one_primary() -> None:
    plan = await _plan(
        "u1",
        _gmail(),
        "ca_work",
        "connected",
        [_account("ca_old", created="2026-01-01"), _account("ca_work", created="2026-03-01")],
    )

    assert [(a.connected_account_id, a.label) for a in plan.keep] == [
        ("ca_old", "me@gmail.com"),
        ("ca_work", "work@acme.com"),
    ]
    assert plan.revoke == []
    assert plan.primary == "ca_work"


async def test_dead_and_abandoned_accounts_are_revoked_but_a_disabled_one_is_left_alone() -> None:
    plan = await _plan(
        "u1",
        _gmail(),
        "ca_old",
        "connected",
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
        "u1",
        _gmail(),
        "ca_gone",
        "connected",
        [_account("ca_old", created="2026-01-01"), _account("ca_new", created="2026-02-01")],
    )

    assert [a.connected_account_id for a in plan.keep] == ["ca_new"]
    assert plan.revoke == ["ca_old"]
    assert plan.primary == "ca_new"


async def test_an_expired_integration_keeps_its_dead_account_so_reconnect_is_offered() -> None:
    plan = await _plan(
        "u1", _gmail(), "ca_dead", "expired", [_account("ca_dead", status="EXPIRED")]
    )

    assert [(a.connected_account_id, a.status) for a in plan.keep] == [("ca_dead", "expired")]
    assert plan.revoke == []
    assert plan.primary == "ca_dead"
