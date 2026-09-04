"""Account settings mutations against REAL MongoDB.

Every applier behind the account tools runs its actual repository code path
into a real Mongo database (the ``mongo_db`` fixture redirects the whole
repository layer). Only external SaaS seams are substituted — ElevenLabs for
voice validation — per the mock hierarchy: mock third-party APIs, never your
own persistence.

A user document is seeded fresh per test; every assertion reads the document
back from Mongo, not from a mock's call log.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
import pytest

from app.services import account_settings, voice_service
from app.services.platform_link_service import (
    PlatformLinkService,
    disconnect_platform_account,
    start_platform_connect,
)
from app.utils.errors import AppError

pytestmark = pytest.mark.service

USER_OID = ObjectId("6acc0dac0cc0a00000000001")
USER_ID = str(USER_OID)


@pytest.fixture(autouse=True)
async def _user(mongo_db):
    await mongo_db["users"].delete_many({"_id": USER_OID})
    await mongo_db["users"].insert_one(
        {
            "_id": USER_OID,
            "email": "account-real@gaia.local",
            "name": "Real Infra",
            "timezone": "UTC",
            "onboarding": {"preferences": {"profession": "Developer", "response_style": "casual"}},
            "platform_links": {},
            "platform_links_connected_at": {},
        }
    )
    yield
    await mongo_db["users"].delete_many({"_id": USER_OID})


async def user_doc(db) -> dict:
    """Read the user straight from Mongo — assertions never trust mocks."""
    return await db["users"].find_one({"_id": USER_OID})


class TestNotificationChannels:
    async def test_flags_persist_and_unset_channels_survive(self, mongo_db):
        await mongo_db["users"].update_one(
            {"_id": USER_OID},
            {
                "$set": {
                    "notification_channel_prefs": {"telegram": True, "email": True, "discord": True}
                }
            },
        )

        await account_settings.set_notification_channels(USER_ID, email=False)

        prefs = (await user_doc(mongo_db))["notification_channel_prefs"]
        # email flipped; telegram/discord untouched — the real document proves it.
        assert prefs["email"] is False
        assert prefs["telegram"] is True
        assert prefs["discord"] is True


class TestPreferences:
    async def test_style_patch_leaves_profession_intact_in_the_real_document(self, mongo_db):
        await account_settings.set_preferences(USER_ID, response_style="brief")

        prefs = (await user_doc(mongo_db))["onboarding"]["preferences"]
        assert prefs["response_style"] == "brief"
        assert prefs["profession"] == "Developer"

    async def test_timezone_lands_on_the_root_field(self, mongo_db):
        await account_settings.set_preferences(USER_ID, timezone="Asia/Kolkata")

        assert (await user_doc(mongo_db))["timezone"] == "Asia/Kolkata"


class TestCustomInstructions:
    async def test_instructions_persist_verbatim_up_to_the_cap(self, mongo_db):
        text = "Always answer with an example." * 15  # 420 chars

        await account_settings.set_custom_instructions(USER_ID, instructions=text)

        stored = (await user_doc(mongo_db))["onboarding"]["preferences"]["custom_instructions"]
        assert stored == text

    async def test_clearing_writes_null_not_a_stale_string(self, mongo_db):
        await mongo_db["users"].update_one(
            {"_id": USER_OID},
            {"$set": {"onboarding.preferences.custom_instructions": "old rules"}},
        )

        await account_settings.set_custom_instructions(USER_ID, instructions="")

        stored = (await user_doc(mongo_db))["onboarding"]["preferences"]["custom_instructions"]
        assert stored is None


class TestVoiceSelection:
    async def test_selected_voice_id_persists_through_the_real_validator(self, mongo_db):
        """Mock ONLY the ElevenLabs data source; the real ``set_user_voice``
        validation body runs and the real repository write lands."""
        canned_catalog = SimpleNamespace(
            voices=[SimpleNamespace(voice_id="v-real-1", name="Rachel", starred=False)],
            selected_voice_id=None,
        )
        with (
            patch.object(account_settings, "list_voices", return_value=canned_catalog),
            patch.object(voice_service, "_known_voice_ids", return_value={"v-real-1"}),
            patch.object(voice_service, "get_shared_voices", return_value=[]),
        ):
            result = await account_settings.select_voice(USER_ID, voice="Rachel")

        assert "Rachel" in result
        assert (await user_doc(mongo_db))["selected_voice_id"] == "v-real-1"

    async def test_unknown_voice_writes_nothing_to_mongo(self, mongo_db):
        canned_catalog = SimpleNamespace(voices=[], selected_voice_id=None)
        with (
            patch.object(account_settings, "list_voices", return_value=canned_catalog),
            patch.object(voice_service, "_known_voice_ids", return_value=set()),
            patch.object(voice_service, "get_shared_voices", return_value=[]),
        ):
            with pytest.raises(AppError):
                await account_settings.select_voice(USER_ID, voice="Ghost")

        assert "selected_voice_id" not in (await user_doc(mongo_db))


class TestLinkedAccounts:
    async def test_generate_link_returns_instructions_without_touching_mongo(self, mongo_db):
        response = await start_platform_connect(USER_ID, "telegram")

        assert response.auth_type == "manual"
        assert "/auth" in response.instructions
        assert (await user_doc(mongo_db))["platform_links"] == {}

    async def test_disconnect_removes_the_link_from_the_real_document(self, mongo_db):
        await mongo_db["users"].update_one(
            {"_id": USER_OID},
            {
                "$set": {
                    "platform_links.telegram": {"id": "tg-1", "username": "realuser"},
                    "platform_links_connected_at.telegram": "2026-08-24T00:00:00+00:00",
                }
            },
        )
        linked = await PlatformLinkService.get_linked_platforms(USER_ID)
        assert "telegram" in linked  # seeded truth

        result = await disconnect_platform_account(USER_ID, "telegram")

        assert result.status == "disconnected"
        doc = await user_doc(mongo_db)
        assert "telegram" not in (doc["platform_links"] or {})
        assert "telegram" not in (doc["platform_links_connected_at"] or {})

    async def test_disconnect_of_an_unlinked_platform_raises_404(self, mongo_db):
        with pytest.raises(AppError):
            await disconnect_platform_account(USER_ID, "slack")
