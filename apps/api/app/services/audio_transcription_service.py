"""
Audio transcription service.

Wraps OpenAI Whisper for short-form audio → text conversion used by bot
adapters that receive voice notes (WhatsApp, Telegram, etc.). Provider-
agnostic on the surface so the underlying model can swap without changing
callers.
"""

from __future__ import annotations

import io
from typing import Final

from openai import AsyncOpenAI

from shared.py.wide_events import log

# OpenAI's documented hard ceiling for the audio transcription endpoint.
# Anything larger is rejected upstream — surface a clear 413 before sending.
MAX_AUDIO_BYTES: Final[int] = 25 * 1024 * 1024

# MIME types accepted by Whisper. WhatsApp voice notes ship as audio/ogg
# (Opus); audio files may also arrive as mp3/aac/m4a/wav.
_ALLOWED_AUDIO_MIME_TYPES: Final[frozenset[str]] = frozenset(
    {
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
    }
)


class AudioTooLargeError(ValueError):
    """Audio payload exceeds the transcription provider's size limit."""


class UnsupportedAudioFormatError(ValueError):
    """Audio mime type is not in the supported allowlist."""


def validate_audio_payload(*, content_type: str | None, size: int) -> str:
    """Validate inbound audio against size + format limits.

    Returns the normalised content type. Raises {@link AudioTooLargeError} or
    {@link UnsupportedAudioFormatError} so callers can map to HTTP responses.
    """
    if size > MAX_AUDIO_BYTES:
        raise AudioTooLargeError(f"Audio is {size} bytes; max supported is {MAX_AUDIO_BYTES}.")
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized not in _ALLOWED_AUDIO_MIME_TYPES:
        raise UnsupportedAudioFormatError(
            f"Unsupported audio content type: {normalized or '<missing>'}."
        )
    return normalized


async def transcribe_audio(
    *,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> str:
    """Transcribe a single audio clip via OpenAI Whisper.

    The OpenAI SDK expects a tuple of ``(filename, file_obj, content_type)``
    for streamed multipart upload. Returns the trimmed transcript string.
    """
    log.set(
        service="audio_transcription_service",
        operation="transcribe",
        filename=filename,
        content_type=content_type,
        size=len(audio_bytes),
    )

    client = AsyncOpenAI()
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename  # OpenAI SDK reads .name for the multipart filename

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, file_obj, content_type),
    )

    text = (response.text or "").strip()
    log.set(outcome="success", transcript_length=len(text))
    return text
