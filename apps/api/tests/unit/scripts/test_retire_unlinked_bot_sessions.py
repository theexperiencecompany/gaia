"""Unit tests for the stale bot-session repair: its verdicts, its plan and what --apply deletes.

The three repositories it reads and writes are its seams; the same flow runs against real
Mongo in tests/integration/real/test_retire_unlinked_bot_sessions_real.py.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from unittest.mock import AsyncMock, call, patch

import pytest

from app.models.bot_models import BotSessionDocument
from app.models.user_models import UserDocument
from app.scripts import retire_unlinked_bot_sessions as script
from app.scripts.retire_unlinked_bot_sessions import Retirement, Verdict, judge

MODULE = "app.scripts.retire_unlinked_bot_sessions"


def _session(platform_user_id: str, platform: str = "telegram") -> BotSessionDocument:
    return BotSessionDocument(
        session_key=f"{platform}:{platform_user_id}:{platform_user_id}",
        conversation_id=f"c-{platform_user_id}",
        platform=platform,
        platform_user_id=platform_user_id,
    )


@pytest.fixture
def repos() -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock]]:
    with (
        patch(f"{MODULE}.bot_session_repository") as sessions,
        patch(f"{MODULE}.user_repository") as users,
        patch(f"{MODULE}.conversation_repository") as conversations,
    ):
        sessions.list_sessions = AsyncMock(return_value=[])
        sessions.delete_by_session_key = AsyncMock(return_value=1)
        users.get_by_platform_id = AsyncMock(return_value=None)
        conversations.owner_ids = AsyncMock(return_value=set())
        yield sessions, users, conversations


@pytest.mark.parametrize(
    ("linked", "owners", "verdict"),
    [
        (None, set(), Verdict.UNLINKED),
        (None, {"a"}, Verdict.UNLINKED),
        ("a", set(), Verdict.OWNERLESS),
        ("a", {"a"}, None),
        ("a", {"b"}, Verdict.FOREIGN),
        ("a", {"a", "b"}, Verdict.SHARED),
    ],
)
def test_judge(linked: str | None, owners: set[str], verdict: Verdict | None) -> None:
    assert judge(linked, owners) is verdict


async def test_plan_looks_up_each_sessions_account_and_owners_and_keeps_only_the_healthy(
    repos: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    sessions, users, conversations = repos
    healthy, orphan = _session("tg-ok", "slack"), _session("tg-gone", "slack")
    sessions.list_sessions.return_value = [healthy, orphan]
    owner = UserDocument.model_validate({"id": "u-1", "email": "o@gaia.local"})
    users.get_by_platform_id.side_effect = lambda platform, pid: owner if pid == "tg-ok" else None
    conversations.owner_ids.return_value = {"u-1"}

    plan = await script._plan("slack")

    assert plan == [Retirement(orphan, Verdict.UNLINKED)]
    sessions.list_sessions.assert_awaited_once_with(platform="slack")
    assert users.get_by_platform_id.await_args_list == [
        call("slack", "tg-ok"),
        call("slack", "tg-gone"),
    ]
    assert conversations.owner_ids.await_args_list == [call("c-tg-ok"), call("c-tg-gone")]


def _plan_of(*retirements: Retirement) -> AsyncMock:
    return AsyncMock(return_value=list(retirements))


async def test_dry_run_reports_every_retirement_and_writes_nothing(
    repos: tuple[AsyncMock, AsyncMock, AsyncMock], capsys: pytest.CaptureFixture[str]
) -> None:
    sessions, _, _ = repos
    orphan, shared = _session("tg-1"), _session("tg-2")
    plan = _plan_of(Retirement(orphan, Verdict.UNLINKED), Retirement(shared, Verdict.SHARED))

    with patch(f"{MODULE}._plan", plan):
        rc = await script._run(argparse.Namespace(apply=False, platform="telegram"))

    assert rc == 0
    plan.assert_awaited_once_with("telegram")
    sessions.delete_by_session_key.assert_not_awaited()
    # The operator decides --apply from this output, so it is the contract.
    assert capsys.readouterr().out.splitlines() == [
        f"  [unlinked] {orphan.session_key} -> {orphan.conversation_id}",
        f"  [shared] {shared.session_key} -> {shared.conversation_id}",
        "Summary: 1 unlinked, 0 ownerless, 0 foreign, 1 shared",
        (
            "SHARED conversations already mix two users' agent threads; review them by hand "
            "(this script does not touch conversations or threads)."
        ),
        "Dry run only. Re-run with --apply to commit.",
    ]


async def test_no_shared_conversation_means_no_review_notice(
    repos: tuple[AsyncMock, AsyncMock, AsyncMock], capsys: pytest.CaptureFixture[str]
) -> None:
    with patch(f"{MODULE}._plan", _plan_of(Retirement(_session("tg-1"), Verdict.FOREIGN))):
        await script._run(argparse.Namespace(apply=False, platform=None))

    out = capsys.readouterr().out
    assert "Summary: 0 unlinked, 0 ownerless, 1 foreign, 0 shared" in out
    assert "review them by hand" not in out


async def test_apply_deletes_exactly_the_planned_sessions(
    repos: tuple[AsyncMock, AsyncMock, AsyncMock], capsys: pytest.CaptureFixture[str]
) -> None:
    sessions, _, _ = repos
    first, second = _session("tg-1"), _session("tg-2")
    plan = _plan_of(Retirement(first, Verdict.UNLINKED), Retirement(second, Verdict.FOREIGN))

    with patch(f"{MODULE}._plan", plan):
        rc = await script._run(argparse.Namespace(apply=True, platform=None))

    assert rc == 0
    assert sessions.delete_by_session_key.await_args_list == [
        call(first.session_key),
        call(second.session_key),
    ]
    out = capsys.readouterr().out
    assert "Retired 2/2 session(s)." in out
    assert "Dry run only" not in out


async def test_apply_fails_when_a_planned_session_was_already_gone(
    repos: tuple[AsyncMock, AsyncMock, AsyncMock], capsys: pytest.CaptureFixture[str]
) -> None:
    sessions, _, _ = repos
    sessions.delete_by_session_key.side_effect = [1, 0]
    plan = _plan_of(
        Retirement(_session("tg-1"), Verdict.UNLINKED),
        Retirement(_session("tg-2"), Verdict.UNLINKED),
    )

    with patch(f"{MODULE}._plan", plan):
        rc = await script._run(argparse.Namespace(apply=True, platform=None))

    assert rc == 1
    assert "Retired 1/2 session(s)." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], argparse.Namespace(apply=False, platform=None)),
        (["--apply", "--platform", "slack"], argparse.Namespace(apply=True, platform="slack")),
    ],
)
def test_main_parses_its_flags_and_exits_with_the_runs_code(
    argv: list[str], expected: argparse.Namespace
) -> None:
    run = AsyncMock(return_value=3)
    with (
        patch(f"{MODULE}._run", run),
        patch("sys.argv", ["retire_unlinked_bot_sessions", *argv]),
        pytest.raises(SystemExit) as exit_info,
    ):
        script.main()

    assert exit_info.value.code == 3
    run.assert_awaited_once_with(expected)


def test_help_documents_the_script_and_both_flags(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("sys.argv", ["retire_unlinked_bot_sessions", "--help"]), pytest.raises(SystemExit):
        script.main()

    out = " ".join(capsys.readouterr().out.split())
    assert script.__doc__ is not None
    assert " ".join(script.__doc__.split()[:12]) in out
    assert "--apply Persist (otherwise dry run)." in out
    assert "--platform PLATFORM Restrict to one platform." in out
