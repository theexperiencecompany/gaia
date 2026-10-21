"""The Inbox desk backfill: a dry run writes nothing, and one user's failure stops nobody else."""

from unittest.mock import AsyncMock, patch

from scripts.provision_inbox_desks import BackfillResult, run_backfill

MODULE = "scripts.provision_inbox_desks"


async def _run(provision: AsyncMock, *, dry_run: bool) -> BackfillResult:
    with (
        patch(
            f"{MODULE}.user_integration_repository.user_ids_with_integration",
            AsyncMock(return_value=["u2", "u3", "u9"]),
        ) as gmail,
        patch(
            f"{MODULE}.subscription_repository.active_user_ids",
            AsyncMock(return_value=["u1", "u2", "u3"]),
        ),
        patch(f"{MODULE}.provision_inbox_desk", provision),
    ):
        result = await run_backfill(dry_run=dry_run)
    gmail.assert_awaited_once_with("gmail")
    return result


async def test_a_dry_run_names_the_paying_gmail_users_and_opens_nothing() -> None:
    provision = AsyncMock()

    result = await _run(provision, dry_run=True)

    assert result.user_ids == ["u2", "u3"]
    provision.assert_not_awaited()


async def test_it_provisions_each_paying_gmail_user_past_a_failure() -> None:
    provision = AsyncMock(side_effect=[ConnectionError("mongo down"), None])

    result = await _run(provision, dry_run=False)

    assert [c.args[0] for c in provision.await_args_list] == ["u2", "u3"]
    assert result.failures == {"u2": "ConnectionError: mongo down"}
