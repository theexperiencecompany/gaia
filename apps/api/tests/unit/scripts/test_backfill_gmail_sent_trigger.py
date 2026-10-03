"""The sent-mail trigger backfill: --dry-run never writes, and --execute arms only the unarmed.

Composio is the seam: the two listings are faked page by page, and trigger
creation is the live connect path (handle_subscribe_trigger) on a stand-in service.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.backfill_gmail_sent_trigger import BackfillResult, main, run_backfill

pytestmark = pytest.mark.unit

GMAIL_AUTH_CONFIG = "ac_svLPDmjcTVMX"


def _page(items: list[SimpleNamespace], next_cursor: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(items=items, next_cursor=next_cursor)


def _service(
    account_pages: list[SimpleNamespace],
    trigger_pages: list[SimpleNamespace],
    subscribe_results: dict[str, object] | None = None,
) -> MagicMock:
    service = MagicMock()
    service.composio.connected_accounts.list = MagicMock(side_effect=account_pages)
    service.composio.triggers.list_active = MagicMock(side_effect=trigger_pages)
    results = subscribe_results or {}
    service.handle_subscribe_trigger = AsyncMock(
        side_effect=lambda user_id, _triggers: results.get(user_id, [SimpleNamespace()])
    )
    return service


def _accounts(*user_ids: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(user_id=user_id) for user_id in user_ids]


class TestRunBackfill:
    async def test_dry_run_reports_the_unarmed_users_and_creates_nothing(self) -> None:
        service = _service(
            [_page(_accounts("u1", "u2", "u3"))],
            [_page(_accounts("u2"))],
        )

        result = await run_backfill(service, dry_run=True)

        assert result.pending_user_ids == ["u1", "u3"]
        assert result.already_armed == 1
        service.handle_subscribe_trigger.assert_not_awaited()

    async def test_execute_arms_each_unarmed_user_through_the_connect_path(self) -> None:
        service = _service(
            [_page(_accounts("u1", "u2"))],
            [_page(_accounts("u2"))],
        )

        result = await run_backfill(service, dry_run=False)

        assert result.armed_user_ids == ["u1"]
        assert result.failed_user_ids == []
        service.handle_subscribe_trigger.assert_awaited_once()
        user_id, (trigger,) = service.handle_subscribe_trigger.await_args.args
        assert user_id == "u1"
        assert trigger.slug == "GMAIL_EMAIL_SENT_TRIGGER"
        assert trigger.config == {"interval": 1}
        assert trigger.auto_activate is True

    async def test_a_rerun_after_everyone_is_armed_creates_nothing(self) -> None:
        service = _service(
            [_page(_accounts("u1", "u2"))],
            [_page(_accounts("u1", "u2"))],
        )

        result = await run_backfill(service, dry_run=False)

        assert result.pending_user_ids == []
        assert result.already_armed == 2
        service.handle_subscribe_trigger.assert_not_awaited()

    async def test_both_listings_are_scoped_to_gaias_gmail_auth_config(self) -> None:
        # Another auth config in the same Composio project is not GAIA's Gmail;
        # arming its users would create triggers nothing here ever reads.
        service = _service([_page([])], [_page([])])

        await run_backfill(service, dry_run=True)

        accounts = service.composio.connected_accounts.list.call_args.kwargs
        assert accounts["auth_config_ids"] == [GMAIL_AUTH_CONFIG]
        assert accounts["statuses"] == ["ACTIVE"]
        triggers = service.composio.triggers.list_active.call_args.kwargs
        assert triggers["auth_config_ids"] == [GMAIL_AUTH_CONFIG]
        assert triggers["trigger_names"] == ["GMAIL_EMAIL_SENT_TRIGGER"]

    async def test_every_page_of_both_listings_is_read(self) -> None:
        # Stopping at page one would re-arm every armed user on a later page
        # and skip every unarmed one.
        service = _service(
            [_page(_accounts("u1"), next_cursor="a2"), _page(_accounts("u2", "u3"))],
            [_page(_accounts("u1"), next_cursor="t2"), _page(_accounts("u3"))],
        )

        result = await run_backfill(service, dry_run=True)

        assert result.pending_user_ids == ["u2"]
        assert service.composio.connected_accounts.list.call_args.kwargs["cursor"] == "a2"
        assert service.composio.triggers.list_active.call_args.kwargs["cursor"] == "t2"

    async def test_a_failed_create_is_reported_and_does_not_stop_the_rest(self) -> None:
        # handle_subscribe_trigger answers None when Composio refused the create.
        service = _service(
            [_page(_accounts("u1", "u2"))],
            [_page([])],
            subscribe_results={"u1": None},
        )

        result = await run_backfill(service, dry_run=False)

        assert result.failed_user_ids == ["u1"]
        assert result.armed_user_ids == ["u2"]


async def _main_with(monkeypatch: pytest.MonkeyPatch, failed_user_ids: list[str]) -> None:
    result = BackfillResult(
        dry_run=False, pending_user_ids=["u1"], already_armed=0, failed_user_ids=failed_user_ids
    )
    monkeypatch.setattr("sys.argv", ["backfill_gmail_sent_trigger.py", "--execute"])
    with (
        patch("scripts.backfill_gmail_sent_trigger.init_composio_service"),
        patch("scripts.backfill_gmail_sent_trigger.get_composio_service"),
        patch("scripts.backfill_gmail_sent_trigger.run_backfill", AsyncMock(return_value=result)),
    ):
        await main()


async def test_a_user_left_unarmed_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exited:
        await _main_with(monkeypatch, ["u1"])

    assert exited.value.code == 1


async def test_a_run_that_armed_everyone_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    await _main_with(monkeypatch, [])
