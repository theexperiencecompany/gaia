"""``reset_playbook_declines``: the one-off that gives back chances blocked runs spent."""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.scripts import reset_playbook_declines as script

MODULE = "app.scripts.reset_playbook_declines"


def _args(**overrides: bool) -> argparse.Namespace:
    values: dict[str, Any] = {"apply": False, "at_limit_only": False, **overrides}
    return argparse.Namespace(**values)


def _workflows(affected: int = 4, at_limit: int = 1) -> MagicMock:
    collection = MagicMock()
    collection.count_documents = AsyncMock(side_effect=[affected, at_limit])
    collection.update_many = AsyncMock(return_value=MagicMock(modified_count=affected))
    return collection


def _database(collection: MagicMock) -> MagicMock:
    database = MagicMock()
    database.__getitem__ = MagicMock(return_value=collection)
    mongo = MagicMock()
    mongo.return_value.database = database
    return mongo


@pytest.mark.unit
class TestResetPlaybookDeclines:
    async def test_a_dry_run_counts_and_writes_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        collection = _workflows(affected=4, at_limit=1)
        with patch(f"{MODULE}.MongoDB", _database(collection)):
            code = await script._run(_args())

        assert code == 0
        collection.update_many.assert_not_awaited()
        assert collection.count_documents.await_args_list[0].args[0] == {
            "playbook_declines": {"$gte": 1}
        }
        out = capsys.readouterr().out
        assert "at least 1 decline(s): 4" in out
        assert f"limit of {PLAYBOOK_DECLINE_LIMIT}: 1" in out
        assert "dry run" in out

    async def test_apply_clears_the_tally_and_the_hash_together(self) -> None:
        """The hash goes with the count: left behind, the next decline would read
        as a continuation of a tally that no longer exists."""
        collection = _workflows(affected=4, at_limit=1)
        with patch(f"{MODULE}.MongoDB", _database(collection)):
            code = await script._run(_args(apply=True))

        assert code == 0
        collection.update_many.assert_awaited_once_with(
            {"playbook_declines": {"$gte": 1}},
            {"$set": {"playbook_declines": 0, "playbook_declined_hash": None}},
        )

    async def test_at_limit_only_touches_the_locked_out_workflows(self) -> None:
        collection = _workflows(affected=1, at_limit=1)
        with patch(f"{MODULE}.MongoDB", _database(collection)):
            await script._run(_args(apply=True, at_limit_only=True))

        query = collection.update_many.await_args.args[0]
        assert query == {"playbook_declines": {"$gte": PLAYBOOK_DECLINE_LIMIT}}
