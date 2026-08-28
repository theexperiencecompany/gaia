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
        patch.object(
            account_settings.user_repository, "set_channel_preferences", new=AsyncMock()
        ) as set_channels,
        patch.object(
            account_settings.user_repository, "update_onboarding_preferences", new=AsyncMock()
        ) as update_prefs,
        patch.object(account_settings.user_repository, "update", new=AsyncMock()) as update,
    ):
        yield SimpleNamespace(set_channels=set_channels, update_prefs=update_prefs, update=update)


async def test_notification_channels_write_only_the_given_flags(repo) -> None:
    result = await account_settings.set_notification_channels(USER_ID, email=False, telegram=True)

    assert result == "Notification settings updated (telegram=on, email=off)."
    repo.set_channels.assert_awaited_once_with(USER_ID, email=False, telegram=True)


async def test_notification_channels_with_no_flags_is_an_error(repo) -> None:
    with pytest.raises(AppError) as excinfo:
        await account_settings.set_notification_channels(USER_ID)

    assert excinfo.value.message == "No channels were specified"
    assert excinfo.value.why == "the tool call did not include any channel flag"
    assert excinfo.value.fix == "Pass at least one channel, e.g. email=False"
    assert excinfo.value.status_code == 400
    repo.set_channels.assert_not_awaited()


async def test_response_style_patches_only_that_field(repo) -> None:
    result = await account_settings.set_preferences(USER_ID, response_style=" brief ")

    assert result == "Preferences updated: response style set to 'brief'."
    assert repo.update_prefs.await_args.args[0] == USER_ID
    preferences = repo.update_prefs.await_args.args[1]
    # PATCH semantics: only response_style is in fields_set, so profession and
    # custom_instructions are never clobbered.
    assert preferences.model_fields_set == {"response_style"}
    assert preferences.response_style == "brief"


async def test_invalid_timezone_is_rejected_before_any_write(repo) -> None:
    with pytest.raises(AppError) as excinfo:
        await account_settings.set_preferences(USER_ID, timezone="Mars/Olympus")

    assert excinfo.value.message == "Invalid timezone 'Mars/Olympus'"
    assert excinfo.value.fix == (
        "Use an IANA identifier like 'America/New_York', 'Asia/Kolkata' or 'UTC'"
    )
    assert excinfo.value.status_code == 400
    repo.update.assert_not_awaited()


async def test_empty_and_whitespace_timezones_are_invalid_not_silently_accepted(repo) -> None:
    for bad in ["", "   "]:
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_preferences(USER_ID, timezone=bad)
        assert excinfo.value.message == f"Invalid timezone '{bad.strip()}'"
        repo.update.assert_not_awaited()


async def test_timezone_writes_the_root_level_field(repo) -> None:
    await account_settings.set_preferences(USER_ID, timezone="Asia/Kolkata")

    update = repo.update.await_args
    assert update.args[0] == USER_ID
    assert update.args[1].timezone == "Asia/Kolkata"


async def test_custom_instructions_patch_exactly_one_field_and_cap_length(repo) -> None:
    result = await account_settings.set_custom_instructions(
        USER_ID, instructions="  always reply in haiku "
    )
    assert result == "Custom instructions updated."
    preferences = repo.update_prefs.await_args.args[1]
    assert preferences.model_fields_set == {"custom_instructions"}
    assert preferences.custom_instructions == "always reply in haiku"
    assert repo.update_prefs.await_args.args[0] == USER_ID

    with pytest.raises(AppError):
        await account_settings.set_custom_instructions(USER_ID, instructions="x" * 501)


async def test_empty_custom_instructions_clear_them(repo) -> None:
    result = await account_settings.set_custom_instructions(USER_ID, instructions="   ")

    assert result == "Custom instructions cleared."
    preferences = repo.update_prefs.await_args.args[1]
    assert preferences.model_fields_set == {"custom_instructions"}
    assert preferences.custom_instructions is None


async def test_voice_resolves_by_name_case_insensitively(repo) -> None:
    voice = SimpleNamespace(voice_id="v-123", name="Rachel", starred=False)
    catalog = SimpleNamespace(voices=[voice], selected_voice_id=None)
    with (
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)) as list_voices,
        patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
    ):
        result = await account_settings.select_voice(USER_ID, voice="rachel")

    assert "Rachel" in result
    list_voices.assert_awaited_once_with(USER_ID)
    set_voice.assert_awaited_once_with(USER_ID, "v-123")


async def test_unknown_voice_names_the_catalog_instead_of_failing_blindly(repo) -> None:
    catalog = SimpleNamespace(voices=[SimpleNamespace(voice_id="v1", name="Rachel")])
    with (
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)),
        patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
    ):
        with pytest.raises(AppError) as excinfo:
            await account_settings.select_voice(USER_ID, voice="nope")

    assert excinfo.value.fix == "Pick one from the catalog, e.g.: Rachel"
    assert excinfo.value.status_code == 404
    set_voice.assert_not_awaited()


async def test_unknown_voice_error_pins_the_message_and_reason(repo) -> None:
    catalog = SimpleNamespace(
        voices=[
            SimpleNamespace(voice_id="v1", name="Rachel"),
            SimpleNamespace(voice_id="v2", name="Adam"),
        ]
    )
    with (
        patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=catalog)),
        patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
    ):
        with pytest.raises(AppError) as excinfo:
            await account_settings.select_voice(USER_ID, voice="  nope  ")

    assert excinfo.value.message == "Unknown voice '  nope  '"
    assert excinfo.value.why == "it is not in this user's voice catalog"
    assert excinfo.value.fix == "Pick one from the catalog, e.g.: Rachel, Adam"
    assert excinfo.value.status_code == 404
    set_voice.assert_not_awaited()


# ---------------------------------------------------------------------------
# Brutal edge cases — attack what a hasty implementation forgets
# ---------------------------------------------------------------------------


class TestSetPreferencesEdges:
    async def test_no_arguments_at_all_is_an_error_not_a_silent_noop(self, repo) -> None:
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_preferences(USER_ID)

        assert excinfo.value.message == "Nothing to update"
        assert excinfo.value.why == "neither response_style nor timezone was provided"
        assert excinfo.value.fix == (
            "Pass response_style (brief/detailed/casual/professional or a custom label) "
            "and/or an IANA timezone"
        )
        assert excinfo.value.status_code == 400
        repo.update_prefs.assert_not_awaited()
        repo.update.assert_not_awaited()

    async def test_whitespace_only_response_style_is_rejected_after_stripping(self, repo):
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_preferences(USER_ID, response_style="   \t\n")

        assert excinfo.value.message == "Response style cannot be empty"
        assert excinfo.value.fix == (
            "Use one of brief, detailed, casual, professional — or pass a custom label"
        )
        assert excinfo.value.status_code == 400
        repo.update_prefs.assert_not_awaited()

    async def test_missing_user_on_style_write_raises_404(self, repo) -> None:
        repo.update_prefs.return_value = None
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_preferences(USER_ID, response_style="brief")

        assert excinfo.value.message == "User not found"
        assert excinfo.value.status_code == 404

    async def test_missing_user_on_timezone_write_raises_404(self, repo) -> None:
        repo.update.return_value = None
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_preferences(USER_ID, timezone="UTC")

        assert excinfo.value.message == "User not found"
        assert excinfo.value.status_code == 404

    @pytest.mark.parametrize("tz", ["+05:30", "-08:00", "Asia/Kolkata", "UTC"])
    async def test_every_timezone_shape_the_canonical_validator_accepts_lands_verbatim(
        self, repo, tz
    ):
        await account_settings.set_preferences(USER_ID, timezone=tz)
        assert repo.update.await_args.args[1].timezone == tz

    async def test_style_and_timezone_together_write_both_seams(self, repo) -> None:
        result = await account_settings.set_preferences(
            USER_ID, response_style="brief", timezone="UTC"
        )

        assert result == "Preferences updated: response style set to 'brief'; timezone set to UTC."
        assert repo.update_prefs.await_count == 1
        assert repo.update.await_count == 1

    async def test_repo_failure_propagates_instead_of_faking_success(self, repo) -> None:
        repo.update.side_effect = RuntimeError("mongo down")
        with pytest.raises(RuntimeError, match="mongo down"):
            await account_settings.set_preferences(USER_ID, timezone="UTC")


class TestCustomInstructionBoundaries:
    @pytest.mark.parametrize("length", [499, 500])
    async def test_instructions_at_the_cap_are_accepted(self, repo, length: int) -> None:
        await account_settings.set_custom_instructions(USER_ID, instructions="é" * length)
        preferences = repo.update_prefs.await_args.args[1]
        assert preferences.custom_instructions == "é" * length

    @pytest.mark.parametrize("length", [501, 10_000])
    async def test_instructions_over_the_cap_are_rejected_before_any_write(
        self, repo, length: int
    ) -> None:
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_custom_instructions(USER_ID, instructions="é" * length)

        assert excinfo.value.message == "Custom instructions must be 500 characters or less"
        assert excinfo.value.fix == "Shorten the instructions and try again"
        assert excinfo.value.status_code == 400
        repo.update_prefs.assert_not_awaited()

    async def test_missing_user_raises_404(self, repo) -> None:
        repo.update_prefs.return_value = None
        with pytest.raises(AppError) as excinfo:
            await account_settings.set_custom_instructions(USER_ID, instructions="hi")

        assert excinfo.value.message == "User not found"
        assert excinfo.value.status_code == 404
        assert repo.update_prefs.await_args.args[0] == USER_ID


class TestChannelFlagSemantics:
    async def test_all_five_flags_write_in_one_call(self, repo) -> None:
        flags = dict.fromkeys(account_settings.CHANNEL_FLAGS, True)
        await account_settings.set_notification_channels(USER_ID, **flags)
        repo.set_channels.assert_awaited_once_with(USER_ID, **flags)

    async def test_unset_channels_are_absent_from_the_write_so_they_survive(self, repo) -> None:
        # email=False must be written; telegram=None must NOT be — the whole
        # PATCH contract is "unspecified means untouched".
        await account_settings.set_notification_channels(USER_ID, email=False)
        kwargs = repo.set_channels.await_args.kwargs
        assert kwargs == {"email": False}
        assert set(kwargs) != set(account_settings.CHANNEL_FLAGS)


class TestVoiceSelectionAttacks:
    def catalog_of(self, *voices):
        return SimpleNamespace(voices=list(voices), selected_voice_id=None)

    async def test_empty_catalog_reports_an_unknown_voice_without_listing_anything(self):
        with (
            patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=self.catalog_of())),
            patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
        ):
            with pytest.raises(AppError, match="Unknown voice 'Ghost'"):
                await account_settings.select_voice(USER_ID, voice="Ghost")
        set_voice.assert_not_awaited()

    async def test_big_catalog_error_lists_only_a_sample_not_all_voices(self) -> None:
        voices = [SimpleNamespace(voice_id=f"v{i}", name=f"Voice{i}") for i in range(40)]
        with patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=self.catalog_of(*voices))):
            with pytest.raises(AppError) as excinfo:
                await account_settings.select_voice(USER_ID, voice="Missing")
        assert excinfo.value.fix == (
            "Pick one from the catalog, e.g.: " + ", ".join(f"Voice{i}" for i in range(15))
        )
        assert "Voice39" not in excinfo.value.fix

    async def test_exact_voice_id_wins_even_when_it_lowercases_to_another_name(self) -> None:
        # 'rachel' is another voice's NAME but also this voice's ID — id match
        # is exact and checked first in list order.
        voices = [
            SimpleNamespace(voice_id="rachel", name="First"),
            SimpleNamespace(voice_id="v2", name="Rachel"),
        ]
        with (
            patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=self.catalog_of(*voices))),
            patch(f"{MODULE}.set_user_voice", new=AsyncMock()) as set_voice,
        ):
            result = await account_settings.select_voice(USER_ID, voice="rachel")
        assert "First" in result
        set_voice.assert_awaited_once_with(USER_ID, "rachel")

    async def test_selection_failure_between_list_and_set_propagates_loud(self) -> None:
        voice = SimpleNamespace(voice_id="v-123", name="Rachel", starred=False)
        with (
            patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=self.catalog_of(voice))),
            patch(
                f"{MODULE}.set_user_voice",
                new=AsyncMock(side_effect=RuntimeError("elevenlabs down")),
            ),
        ):
            with pytest.raises(RuntimeError, match="elevenlabs down"):
                await account_settings.select_voice(USER_ID, voice="Rachel")

    async def test_whitespace_padded_query_still_resolves(self) -> None:
        voice = SimpleNamespace(voice_id="v-123", name="Rachel", starred=False)
        with (
            patch(f"{MODULE}.list_voices", new=AsyncMock(return_value=self.catalog_of(voice))),
            patch(f"{MODULE}.set_user_voice", new=AsyncMock()),
        ):
            result = await account_settings.select_voice(USER_ID, voice="  RACHEL  ")
        assert "Rachel" in result
