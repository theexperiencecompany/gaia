"""``reset_playbook_declines``: the one-off that gives back chances blocked runs spent."""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
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
        mongo = _database(collection)
        with patch(f"{MODULE}.MongoDB", mongo):
            await script._run(_args())

        mongo.assert_called_once_with(settings.MONGO_DB, MONGO_DATABASE_NAME)
        mongo.return_value.database.__getitem__.assert_called_once_with("workflows")
        collection.update_many.assert_not_awaited()
        assert [c.args[0] for c in collection.count_documents.await_args_list] == [
            {"playbook_declines": {"$gte": 1}},
            {"playbook_declines": {"$gte": PLAYBOOK_DECLINE_LIMIT}},
        ]
        assert capsys.readouterr().out.splitlines() == [
            "workflows with at least 1 decline(s): 4",
            f"...of which locked out at the limit of {PLAYBOOK_DECLINE_LIMIT}: 1",
            "",
            "dry run: nothing written. Re-run with --apply to clear them.",
        ]

    async def test_apply_clears_the_tally_and_the_hash_together(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The hash goes with the count: left behind, the next decline would read
        as a continuation of a tally that no longer exists."""
        collection = _workflows(affected=4, at_limit=1)
        with patch(f"{MODULE}.MongoDB", _database(collection)):
            await script._run(_args(apply=True))

        collection.update_many.assert_awaited_once_with(
            {"playbook_declines": {"$gte": 1}},
            {"$set": {"playbook_declines": 0, "playbook_declined_hash": None}},
        )
        assert capsys.readouterr().out.splitlines()[-1] == "cleared the tally on 4 workflow(s)"

    async def test_at_limit_only_touches_the_locked_out_workflows(self) -> None:
        collection = _workflows(affected=1, at_limit=1)
        with patch(f"{MODULE}.MongoDB", _database(collection)):
            await script._run(_args(apply=True, at_limit_only=True))

        query = collection.update_many.await_args.args[0]
        assert query == {"playbook_declines": {"$gte": PLAYBOOK_DECLINE_LIMIT}}
