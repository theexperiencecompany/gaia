"""Unit tests for the audio transcription service.

Covers payload validation + the OpenAI Whisper integration. The OpenAI client
is patched at module scope so we never make a real network call.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audio_transcription_service import (
    MAX_AUDIO_BYTES,
    AudioTooLargeError,
    UnsupportedAudioFormatError,
    transcribe_audio,
    validate_audio_payload,
)


class TestValidateAudioPayload:
    """Tests for validate_audio_payload MIME normalisation, size and format checks."""

    def test_normalises_mime_type(self):
        result = validate_audio_payload(content_type="audio/ogg", size=1024)
        assert result == "audio/ogg"

    def test_strips_parameters_from_mime_type(self):
        result = validate_audio_payload(
            content_type="audio/ogg; codecs=opus",
            size=1024,
        )
        assert result == "audio/ogg"

    def test_rejects_oversize_payload(self):
        with pytest.raises(AudioTooLargeError):
            validate_audio_payload(content_type="audio/ogg", size=MAX_AUDIO_BYTES + 1)

    def test_rejects_missing_content_type(self):
        with pytest.raises(UnsupportedAudioFormatError):
            validate_audio_payload(content_type=None, size=1024)

    def test_rejects_unknown_content_type(self):
        with pytest.raises(UnsupportedAudioFormatError):
            validate_audio_payload(content_type="text/plain", size=1024)

    @pytest.mark.parametrize(
        "mime",
        [
            "audio/ogg",
            "audio/opus",
            "audio/mpeg",
            "audio/mp3",
            "audio/mp4",
            "audio/m4a",
            "audio/x-m4a",
            "audio/wav",
            "audio/x-wav",
            "audio/webm",
            "audio/aac",
            "audio/flac",
        ],
    )
    def test_accepts_common_audio_formats(self, mime: str):
        assert validate_audio_payload(content_type=mime, size=1024) == mime


class TestTranscribeAudio:
    """Tests for transcribe_audio's Whisper call and transcript handling."""

    @patch("app.services.audio_transcription_service.AsyncOpenAI")
    @patch("app.services.audio_transcription_service.resolve_openai_config")
    async def test_uses_the_stored_credential_key(
        self,
        mock_resolve: MagicMock,
        mock_client_cls: MagicMock,
    ):
        """A key configured in Settings (credential store) is passed explicitly
        to the client — the SDK must not depend on the OPENAI_API_KEY env var."""
        mock_resolve.return_value = {
            "api_key": "sk-stored",
            "base_url": None,
            "model": None,
            "preset": None,
        }
        mock_instance = MagicMock()
        mock_instance.audio.transcriptions.create = AsyncMock(return_value=MagicMock(text="hi"))
        mock_client_cls.return_value = mock_instance

        result = await transcribe_audio(
            audio_bytes=b"bytes", filename="voice.ogg", content_type="audio/ogg"
        )

        assert result == "hi"
        assert mock_client_cls.call_args.kwargs["api_key"] == "sk-stored"

    @patch("app.services.audio_transcription_service.AsyncOpenAI")
    @patch("app.services.audio_transcription_service.resolve_openai_config")
    async def test_falls_back_to_env_when_nothing_is_stored(
        self,
        mock_resolve: MagicMock,
        mock_client_cls: MagicMock,
    ):
        # resolve() already applies the service's env fallback internally, so
        # its None result means neither store nor env has a key.
        mock_resolve.return_value = None

        with pytest.raises(RuntimeError, match="OpenAI is not configured"):
            await transcribe_audio(
                audio_bytes=b"bytes", filename="voice.ogg", content_type="audio/ogg"
            )
        mock_client_cls.assert_not_called()

    @patch("app.services.audio_transcription_service.AsyncOpenAI")
    @patch("app.services.audio_transcription_service.resolve_openai_config")
    async def test_returns_trimmed_transcript(
        self,
        _mock_resolve: MagicMock,
        mock_client_cls: MagicMock,
    ):
        # AsyncOpenAI() returns a client whose .audio.transcriptions.create is async
        transcript = MagicMock(text="  buy milk on the way home  ")
        mock_create = AsyncMock(return_value=transcript)
        mock_instance = MagicMock()
        mock_instance.audio.transcriptions.create = mock_create
        mock_client_cls.return_value = mock_instance

        result = await transcribe_audio(
            audio_bytes=b"fake-opus-bytes",
            filename="voice.ogg",
            content_type="audio/ogg",
        )

        assert result == "buy milk on the way home"
        mock_create.assert_awaited_once()
        await_args = mock_create.await_args
        assert await_args is not None
        kwargs = await_args.kwargs
        assert kwargs["model"] == "whisper-1"
        # OpenAI SDK accepts (filename, file_obj, content_type) tuples
        assert kwargs["file"][0] == "voice.ogg"
        assert kwargs["file"][2] == "audio/ogg"

    @patch("app.services.audio_transcription_service.AsyncOpenAI")
    @patch(
        "app.services.audio_transcription_service.resolve_openai_config",
        new=AsyncMock(
            return_value={"api_key": "sk-stored", "base_url": None, "model": None, "preset": None}
        ),
    )
    async def test_returns_empty_string_for_empty_response(self, mock_client_cls: MagicMock):
        mock_instance = MagicMock()
        mock_instance.audio.transcriptions.create = AsyncMock(return_value=MagicMock(text=None))
        mock_client_cls.return_value = mock_instance

        result = await transcribe_audio(
            audio_bytes=b"bytes", filename="voice.ogg", content_type="audio/ogg"
        )
        assert result == ""
