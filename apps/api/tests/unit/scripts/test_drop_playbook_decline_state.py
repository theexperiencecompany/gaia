"""drop_playbook_decline_state: the one-off that removes the retired decline tally."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.scripts import drop_playbook_decline_state as script

MODULE = "app.scripts.drop_playbook_decline_state"
CARRYING = {
    "$or": [
        {"playbook_declines": {"$exists": True}},
        {"playbook_declined_hash": {"$exists": True}},
        {"playbook_declined_run": {"$exists": True}},
    ]
}


def _collection(affected: int) -> MagicMock:
    collection = MagicMock()
    collection.count_documents = AsyncMock(return_value=affected)
    collection.update_many = AsyncMock(return_value=MagicMock(modified_count=affected))
    return collection


def _mongo(collection: MagicMock) -> MagicMock:
    database = MagicMock()
    database.get_collection = MagicMock(return_value=collection)
    mongo = MagicMock()
    mongo.return_value.database = database
    return mongo


@pytest.mark.unit
class TestDropPlaybookDeclineState:
    async def test_a_dry_run_counts_and_writes_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        collection = _collection(affected=345)
        mongo = _mongo(collection)
        with patch(f"{MODULE}.MongoDB", mongo):
            await script._run(argparse.Namespace(apply=False))

        mongo.assert_called_once_with(settings.MONGO_DB, MONGO_DATABASE_NAME)
        mongo.return_value.database.get_collection.assert_called_once_with("workflows")
        collection.count_documents.assert_awaited_once_with(CARRYING)
        collection.update_many.assert_not_awaited()
        assert capsys.readouterr().out.splitlines() == [
            "workflows carrying decline state: 345",
            "",
            "dry run: nothing written. Re-run with --apply to remove it.",
        ]

    async def test_apply_unsets_every_decline_field(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        collection = _collection(affected=345)
        with patch(f"{MODULE}.MongoDB", _mongo(collection)):
            await script._run(argparse.Namespace(apply=True))

        collection.update_many.assert_awaited_once_with(
            CARRYING,
            {
                "$unset": {
                    "playbook_declines": "",
                    "playbook_declined_hash": "",
                    "playbook_declined_run": "",
                }
            },
        )
        assert (
            capsys.readouterr().out.splitlines()[-1] == "removed decline state from 345 workflow(s)"
        )
