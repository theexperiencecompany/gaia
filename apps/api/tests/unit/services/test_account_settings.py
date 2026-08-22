"""Account settings mutations: validation, the owning repo/service seam, and
the confirmation contract.

The appliers are the real write path behind the account tools — a wrong value
that reached Mongo from here would ship straight into the user's account, so
every invalid-input branch and every repo call is pinned.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import account_settings
from app.utils.errors import AppError

MODULE = "app.services.account_settings"
USER_ID = "user-1"


@pytest.fixture
def repo():
    with (
        patch.object(account_settings.user_repository, "set_channel_preferences", new=AsyncMock()) as set_channels,
        patch.object(
            account_settings.user_repository, "update_onboarding_preferences", new=AsyncMock()
        ) as update_prefs,
        patch.object(account_settings.user_repository, "update", new=AsyncMock()) as update,
    ):
        yield SimpleNamespace(
            set_channels=set_channels, update_prefs=update_prefs, update=update
        )


async def test_notification_channels_write_only_the_given_flags(repo) -> None:
    result = await account_settings.set_notification_channels(
        USER_ID, email=False, telegram=True
    )

    assert "email=off" in result and "telegram=on" in result
    repo.set_channels.assert_awaited_once_with(USER_ID, email=False, telegram=True)


async def test_notification_channels_with_no_flags_is_an_error(repo) -> None:
    with pytest.raises(AppError):
        await account_settings.set_notification_channels(USER_ID)
    repo.set_channels.assert_not_awaited()


async def test_response_style_patches_only_that_field(repo) -> None:
    result = await account_settings.set_preferences(USER_ID, response_style=" brief ")

    assert "brief" in result
    preferences = repo.update_prefs.await_args.args[1]
    # PATCH semantics: only response_style is in fields_set, so profession and
    # custom_instructions are never clobbered.
    assert preferences.model_fields_set == {"response_style"}
    assert preferences.response_style == "brief"


async def test_invalid_timezone_is_rejected_before_any_write(repo) -> None:
    with pytest.raises(AppError):
        await account_settings.set_preferences(USER_ID, timezone="Mars/Olympus")
    repo.update.assert_not_awaited()


async def test_timezone_writes_the_root_level_field(repo) -> None:
    await account_settings.set_preferences(USER_ID, timezone="Asia/Kolkata")

    update = repo.update.await_args
    assert update.args[0] == USER_ID
    assert update.args[1].timezone == "Asia/Kolkata"


async def test_custom_instructions_patch_exactly_one_field_and_cap_length(repo) -> None:
    await account_settings.set_custom_instructions(USER_ID, instructions="  always reply in haiku ")
    preferences = repo.update_prefs.await_args.args[1]
    assert preferences.model_fields_set == {"custom_instructions"}
    assert preferences.custom_instructions == "always reply in haiku"

    with pytest.raises(AppError):
        await account_settings.set_custom_instructions(USER_ID, instructions="x" * 501)


async def test_empty_custom_instructions_clear_them(repo) -> None:
    await account_settings.set_custom_instructions(USER_ID, instructions="   ")

    preferences = repo.update_prefs.await_args.args[1]
    assert preferences.model_fields_set == {"custom_instructions"}
    assert preferences.custom_instructions is None


async def test_voice_resolves_by_name_case_insensitively(repo) -> None:
    voice = SimpleNamespace(voice_id="v-123", name="Rachel", starred=False)
    catalog = SimpleNamespace(voices=[voice], selected_voice_id=None)
    with (
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)),
        patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
    ):
        result = await account_settings.select_voice(USER_ID, voice="rachel")

    assert "Rachel" in result
    set_voice.assert_awaited_once_with(USER_ID, "v-123")


async def test_unknown_voice_names_the_catalog_instead_of_failing_blindly(repo) -> None:
    catalog = SimpleNamespace(voices=[SimpleNamespace(voice_id="v1", name="Rachel")])
    with (
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)),
        patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
    ):
        with pytest.raises(AppError) as excinfo:
            await account_settings.select_voice(USER_ID, voice="nope")

    assert "Rachel" in excinfo.value.fix
    set_voice.assert_not_awaited()
