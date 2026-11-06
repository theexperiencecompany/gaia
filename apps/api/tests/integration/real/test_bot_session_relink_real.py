"""A platform account unlinked from one GAIA user and relinked to another starts a fresh bot conversation.

Runs the real link, unlink and session code against real Mongo and Redis. The
session's conversation_id is also the LangGraph thread id, so reusing it would
put the second user on the first user's agent state.
"""

from __future__ import annotations

from bson import ObjectId
import pytest

from app.db.repositories.conversations import conversation_repository
from app.services.bot_service import BotService
from app.services.platform_link_service import PlatformLinkService, disconnect_platform_account
from tests.factories import make_authenticated_user

pytestmark = pytest.mark.service

PLATFORM = "telegram"
PLATFORM_USER_ID = "tg-relink-1"
GROUP_CHANNEL_ID = "-100777"
OTHER_PLATFORM_USER_ID = "tg-bystander-2"
FIRST_OID = ObjectId("6acc0dac0cc0a00000000101")
SECOND_OID = ObjectId("6acc0dac0cc0a00000000102")
BYSTANDER_OID = ObjectId("6acc0dac0cc0a00000000103")


@pytest.fixture(autouse=True)
async def _users(mongo_db, real_redis):
    oids = [FIRST_OID, SECOND_OID, BYSTANDER_OID]
    await mongo_db["users"].delete_many({"_id": {"$in": oids}})
    await mongo_db["bot_sessions"].delete_many({})
    await mongo_db["bot_sessions"].create_index("session_key", unique=True)
    await mongo_db["users"].insert_many(
        [{"_id": oid, "email": f"relink-{oid}@gaia.local", "platform_links": {}} for oid in oids]
    )
    yield
    await mongo_db["users"].delete_many({"_id": {"$in": oids}})
    await mongo_db["bot_sessions"].delete_many({})


@pytest.mark.regression
async def test_relinked_account_does_not_inherit_previous_users_conversation(mongo_db):
    first = make_authenticated_user(user_id=str(FIRST_OID))
    second = make_authenticated_user(user_id=str(SECOND_OID))

    await PlatformLinkService.link_account(first.user_id, PLATFORM, PLATFORM_USER_ID)
    first_dm = await BotService.get_or_create_session(PLATFORM, PLATFORM_USER_ID, None, first)
    first_group = await BotService.get_or_create_session(
        PLATFORM, PLATFORM_USER_ID, GROUP_CHANNEL_ID, first
    )

    await disconnect_platform_account(first.user_id, PLATFORM)
    await PlatformLinkService.link_account(second.user_id, PLATFORM, PLATFORM_USER_ID)

    second_dm = await BotService.get_or_create_session(PLATFORM, PLATFORM_USER_ID, None, second)
    second_group = await BotService.get_or_create_session(
        PLATFORM, PLATFORM_USER_ID, GROUP_CHANNEL_ID, second
    )

    assert second_dm not in {first_dm, first_group}
    assert second_group not in {first_dm, first_group}
    # The first user keeps their history; only the platform session ended.
    assert await conversation_repository.exists(first_dm, user_id=first.user_id)
    assert await conversation_repository.exists(first_group, user_id=first.user_id)
    assert await mongo_db["conversations"].count_documents({"conversation_id": first_dm}) == 1


@pytest.mark.regression
async def test_unlink_leaves_other_platform_accounts_sessions_alone(mongo_db):
    first = make_authenticated_user(user_id=str(FIRST_OID))
    bystander = make_authenticated_user(user_id=str(BYSTANDER_OID))

    await PlatformLinkService.link_account(first.user_id, PLATFORM, PLATFORM_USER_ID)
    await PlatformLinkService.link_account(bystander.user_id, PLATFORM, OTHER_PLATFORM_USER_ID)
    await BotService.get_or_create_session(PLATFORM, PLATFORM_USER_ID, None, first)
    bystander_dm = await BotService.get_or_create_session(
        PLATFORM, OTHER_PLATFORM_USER_ID, None, bystander
    )

    await PlatformLinkService.unlink_account(first.user_id, PLATFORM)

    remaining = await mongo_db["bot_sessions"].find({}, {"_id": 0}).to_list(None)
    assert [(s["platform_user_id"], s["conversation_id"]) for s in remaining] == [
        (OTHER_PLATFORM_USER_ID, bystander_dm)
    ]
