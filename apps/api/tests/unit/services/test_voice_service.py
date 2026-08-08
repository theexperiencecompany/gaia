"""Unit tests for voice_service (catalog listing + per-user voice preference).

ElevenLabs is only ever touched for preview resolution and degrades silently;
selection validation and persistence are the behavior under test.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.constants.voices import DEFAULT_STARRED_VOICE_IDS, DEFAULT_VOICE_ID, VOICE_CATALOG
from app.models.voice_models import ElevenLabsAccountVoice, ElevenLabsSharedVoice
from app.services.voice_service import (
    get_elevenlabs_voices,
    get_shared_voices,
    get_starred_voice_ids,
    get_user_voice,
    list_voices,
    set_user_voice,
    set_voice_star,
)
from app.utils.errors import AppError

_MOD = "app.services.voice_service"
USER_ID = "507f1f77bcf86cd799439011"


@pytest.fixture
def mock_settings():
    with patch(f"{_MOD}.settings", SimpleNamespace(ELEVENLABS_API_KEY="el-key")):
        yield


@pytest.fixture
def mock_user_repo():
    with patch(f"{_MOD}.user_repository") as m:
        m.get = AsyncMock(return_value=None)
        m.set_selected_voice = AsyncMock()
        m.set_starred_voices = AsyncMock()
        yield m


def _account_voice(**overrides: object) -> ElevenLabsAccountVoice:
    data: dict[str, object] = {
        "voice_id": "acct-1",
        "name": "My Clone",
        "preview_url": None,
        "labels": {},
        "language_codes": ["en"],
    }
    data.update(overrides)
    return ElevenLabsAccountVoice(**data)


def _shared_voice(**overrides: object) -> ElevenLabsSharedVoice:
    data: dict[str, object] = {
        "voice_id": "lib-1",
        "name": "Library Voice",
        "preview_url": None,
        "public_owner_id": "owner-1",
        "gender": "female",
        "accent": "american",
        "language": "en",
        "descriptive": "warm",
        "use_case": "narration",
        "language_codes": ["en"],
    }
    data.update(overrides)
    return ElevenLabsSharedVoice(**data)


class TestGetElevenlabsVoices:
    async def test_empty_when_no_api_key(self):
        with patch(f"{_MOD}.settings", SimpleNamespace(ELEVENLABS_API_KEY="")):
            assert await get_elevenlabs_voices() == []

    async def test_returns_fetched_voices(self, mock_settings):
        voices = [_account_voice()]
        with patch(f"{_MOD}._fetch_elevenlabs_voices", AsyncMock(return_value=voices)):
            assert await get_elevenlabs_voices() == voices

    @pytest.mark.parametrize(
        "error", [httpx.HTTPError("boom"), ValueError("bad json"), KeyError("x")]
    )
    async def test_degrades_to_empty_on_upstream_failure(self, mock_settings, error):
        with patch(f"{_MOD}._fetch_elevenlabs_voices", AsyncMock(side_effect=error)):
            assert await get_elevenlabs_voices() == []


class TestGetSharedVoices:
    async def test_empty_when_no_api_key(self):
        with patch(f"{_MOD}.settings", SimpleNamespace(ELEVENLABS_API_KEY="")):
            assert await get_shared_voices() == []

    async def test_returns_fetched_voices(self, mock_settings):
        voices = [_shared_voice()]
        with patch(f"{_MOD}._fetch_shared_voices", AsyncMock(return_value=voices)):
            assert await get_shared_voices() == voices

    async def test_degrades_to_empty_on_upstream_failure(self, mock_settings):
        with patch(f"{_MOD}._fetch_shared_voices", AsyncMock(side_effect=httpx.HTTPError("boom"))):
            assert await get_shared_voices() == []


class TestGetUserVoice:
    async def test_returns_selected_voice(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(selected_voice_id="acct-1")

        assert await get_user_voice(USER_ID) == "acct-1"

    async def test_falls_back_to_default_when_none(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(selected_voice_id=None)

        assert await get_user_voice(USER_ID) == DEFAULT_VOICE_ID

    async def test_falls_back_to_default_for_missing_user(self, mock_user_repo):
        assert await get_user_voice(USER_ID) == DEFAULT_VOICE_ID

    async def test_falls_back_to_default_for_blank_selection(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(selected_voice_id="")

        assert await get_user_voice(USER_ID) == DEFAULT_VOICE_ID


class TestGetStarredVoiceIds:
    async def test_defaults_for_missing_user(self, mock_user_repo):
        assert await get_starred_voice_ids(USER_ID) == list(DEFAULT_STARRED_VOICE_IDS)

    async def test_defaults_when_never_starred(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(starred_voice_ids=None)

        assert await get_starred_voice_ids(USER_ID) == list(DEFAULT_STARRED_VOICE_IDS)

    async def test_returns_stored_list_filtered_to_strings(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(starred_voice_ids=["a", 42, "b"])

        assert await get_starred_voice_ids(USER_ID) == ["a", "b"]


class TestSetVoiceStar:
    async def test_star_prepends_and_persists(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(starred_voice_ids=["a", "b"])

        updated = await set_voice_star(USER_ID, "c", True)

        assert updated == ["c", "a", "b"]
        mock_user_repo.set_starred_voices.assert_awaited_once_with(USER_ID, ["c", "a", "b"])

    async def test_star_is_idempotent(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(starred_voice_ids=["a"])

        updated = await set_voice_star(USER_ID, "a", True)

        assert updated == ["a"]

    async def test_unstar_removes_and_persists(self, mock_user_repo):
        mock_user_repo.get.return_value = SimpleNamespace(starred_voice_ids=["a", "b"])

        updated = await set_voice_star(USER_ID, "a", False)

        assert updated == ["b"]
        mock_user_repo.set_starred_voices.assert_awaited_once_with(USER_ID, ["b"])


class TestSetUserVoice:
    async def test_accepts_account_voice(self, mock_user_repo, mock_settings):
        with patch(
            f"{_MOD}.get_elevenlabs_voices",
            AsyncMock(return_value=[_account_voice(voice_id="acct-1")]),
        ):
            result = await set_user_voice(USER_ID, "acct-1")

        assert result == "acct-1"
        mock_user_repo.set_selected_voice.assert_awaited_once_with(USER_ID, "acct-1")

    async def test_accepts_library_voice(self, mock_user_repo, mock_settings):
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(
                f"{_MOD}.get_shared_voices",
                AsyncMock(return_value=[_shared_voice(voice_id="lib-1")]),
            ),
        ):
            result = await set_user_voice(USER_ID, "lib-1")

        assert result == "lib-1"
        mock_user_repo.set_selected_voice.assert_awaited_once_with(USER_ID, "lib-1")

    async def test_rejects_unknown_voice(self, mock_user_repo, mock_settings):
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
        ):
            with pytest.raises(AppError) as exc_info:
                await set_user_voice(USER_ID, "ghost-voice")

        assert exc_info.value.status_code == 404
        mock_user_repo.set_selected_voice.assert_not_awaited()

    async def test_catalog_fallback_accepts_catalog_voice_when_account_unavailable(
        self, mock_user_repo, mock_settings
    ):
        with patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])):
            result = await set_user_voice(USER_ID, DEFAULT_VOICE_ID)

        assert result == DEFAULT_VOICE_ID


class TestListVoices:
    async def test_catalog_plus_selection(self, mock_user_repo):
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value=DEFAULT_VOICE_ID)),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        assert len(result.voices) == len(VOICE_CATALOG)
        assert result.selected_voice_id == DEFAULT_VOICE_ID
        assert all(not v.starred for v in result.voices)

    async def test_catalog_entry_missing_from_account_is_dropped(self, mock_user_repo):
        account = [_account_voice(voice_id=VOICE_CATALOG[1]["voice_id"])]
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=account)),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value=DEFAULT_VOICE_ID)),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        ids = [v.voice_id for v in result.voices]
        assert VOICE_CATALOG[0]["voice_id"] not in ids
        assert VOICE_CATALOG[1]["voice_id"] in ids

    async def test_account_voice_appended_with_preview(self, mock_user_repo):
        account = [_account_voice(voice_id="acct-1", preview_url="https://preview.example/mp3")]
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=account)),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value="acct-1")),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        account_option = next(v for v in result.voices if v.voice_id == "acct-1")
        assert account_option.source == "account"
        assert account_option.preview_url == "https://preview.example/mp3"
        assert result.selected_voice_id == "acct-1"

    async def test_shared_library_voices_appended(self, mock_user_repo):
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[_shared_voice()])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value=DEFAULT_VOICE_ID)),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        library = next(v for v in result.voices if v.voice_id == "lib-1")
        assert library.source == "library"

    async def test_starred_voices_float_to_top(self, mock_user_repo):
        last_catalog_id = VOICE_CATALOG[-1]["voice_id"]
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value=DEFAULT_VOICE_ID)),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[last_catalog_id])),
        ):
            result = await list_voices(USER_ID)

        assert result.voices[0].voice_id == last_catalog_id
        assert result.voices[0].starred is True

    async def test_selection_reconciled_when_voice_not_listed(self, mock_user_repo):
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value="deleted-voice")),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        assert result.selected_voice_id == DEFAULT_VOICE_ID

    async def test_catalog_entry_gets_preview_and_languages_from_account(self, mock_user_repo):
        entry = VOICE_CATALOG[0]
        account = [
            _account_voice(
                voice_id=entry["voice_id"],
                preview_url="https://preview.example/rachel",
                language_codes=["en", "de"],
            )
        ]
        with (
            patch(f"{_MOD}.get_elevenlabs_voices", AsyncMock(return_value=account)),
            patch(f"{_MOD}.get_shared_voices", AsyncMock(return_value=[])),
            patch(f"{_MOD}.get_user_voice", AsyncMock(return_value=DEFAULT_VOICE_ID)),
            patch(f"{_MOD}.get_starred_voice_ids", AsyncMock(return_value=[])),
        ):
            result = await list_voices(USER_ID)

        option = next(v for v in result.voices if v.voice_id == entry["voice_id"])
        assert option.preview_url == "https://preview.example/rachel"
        assert option.languages == ["English", "German"]
