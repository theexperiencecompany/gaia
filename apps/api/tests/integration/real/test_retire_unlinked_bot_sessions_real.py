"""The repair script retires exactly the sessions whose account no longer belongs to the conversation's owner."""

from __future__ import annotations

import argparse

from bson import ObjectId
import pytest

from app.scripts.retire_unlinked_bot_sessions import Verdict, _plan, _run

pytestmark = pytest.mark.service

HEALTHY_OID = ObjectId("6acc0dac0cc0a00000000201")
FOREIGN_OID = ObjectId("6acc0dac0cc0a00000000202")
SHARED_OID = ObjectId("6acc0dac0cc0a00000000203")
PREVIOUS_OID = ObjectId("6acc0dac0cc0a00000000204")
PREVIOUS = str(PREVIOUS_OID)


def _user(oid: ObjectId, telegram_id: str | None) -> dict[str, object]:
    links = {} if telegram_id is None else {"telegram": {"id": telegram_id}}
    return {"_id": oid, "email": f"{oid}@gaia.local", "platform_links": links}


def _session(platform_user_id: str, conversation_id: str) -> dict[str, str]:
    return {
        "session_key": f"telegram:{platform_user_id}:{platform_user_id}",
        "platform": "telegram",
        "platform_user_id": platform_user_id,
        "conversation_id": conversation_id,
    }


def _conversation(user_id: str, conversation_id: str) -> dict[str, str]:
    return {"user_id": user_id, "conversation_id": conversation_id, "description": "Telegram Chat"}


@pytest.fixture(autouse=True)
async def _seed(mongo_db, real_redis):
    for name in ("users", "bot_sessions", "conversations"):
        await mongo_db[name].delete_many({})
    await mongo_db["users"].insert_many(
        [
            _user(HEALTHY_OID, "tg-healthy"),
            _user(FOREIGN_OID, "tg-foreign"),
            _user(SHARED_OID, "tg-shared"),
            _user(PREVIOUS_OID, None),
        ]
    )
    await mongo_db["bot_sessions"].insert_many(
        [
            _session("tg-healthy", "c-healthy"),
            _session("tg-unlinked", "c-unlinked"),
            _session("tg-foreign", "c-foreign"),
            _session("tg-shared", "c-shared"),
        ]
    )
    await mongo_db["conversations"].insert_many(
        [
            _conversation(str(HEALTHY_OID), "c-healthy"),
            _conversation(PREVIOUS, "c-unlinked"),
            _conversation(PREVIOUS, "c-foreign"),
            _conversation(PREVIOUS, "c-shared"),
            _conversation(str(SHARED_OID), "c-shared"),
        ]
    )
    yield
    for name in ("users", "bot_sessions", "conversations"):
        await mongo_db[name].delete_many({})


async def test_plan_judges_each_session():
    plan = {r.session.platform_user_id: r.verdict for r in await _plan(None)}

    assert plan == {
        "tg-unlinked": Verdict.UNLINKED,
        "tg-foreign": Verdict.FOREIGN,
        "tg-shared": Verdict.SHARED,
    }


async def test_dry_run_writes_nothing_and_apply_keeps_only_the_healthy_session(mongo_db):
    assert await _run(argparse.Namespace(apply=False, platform=None)) == 0
    assert await mongo_db["bot_sessions"].count_documents({}) == 4

    assert await _run(argparse.Namespace(apply=True, platform=None)) == 0

    left = [s["platform_user_id"] async for s in mongo_db["bot_sessions"].find({})]
    assert left == ["tg-healthy"]
    # Conversations are never touched.
    assert await mongo_db["conversations"].count_documents({}) == 5
