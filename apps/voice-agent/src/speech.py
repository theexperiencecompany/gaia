"""One reply spoken aloud: its text flushed to TTS in sentence-sized chunks, and how far into it the user heard."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

from src.constants import (
    OPEN_TAG_DEFER_CAP,
    SENTENCE_ENDINGS,
    TTS_FINAL_MIN_CHARS,
    TTS_HARD_FLUSH_CHARS,
    TTS_MIN_EMIT_CHARS,
    TTS_MIN_SENTENCE_CHARS,
)
from src.utils import has_open_openui_fence_at_tail, has_open_tag_at_tail, sanitize_for_tts


@dataclass(frozen=True)
class Flush:
    """A slice of the reply's text handed on: raw for the screen, spoken (sanitised, maybe empty) for TTS."""

    raw: str
    spoken: str


@dataclass(frozen=True)
class _Spoken:
    """A chunk TTS was given and the offset in the reply's text it ends at."""

    spoken: str
    raw_end: int


class ReplySpeech:
    """The spoken form of one reply, fed its text deltas in order."""

    def __init__(self, reply_id: str) -> None:
        self.reply_id = reply_id
        # The reply's text so far: the fold of its response deltas, as the API saves it.
        self.text = ""
        self.settled = False
        self._flushed_to = 0
        self._deferrals = 0
        self._spoken: list[_Spoken] = []
        self._chunks: asyncio.Queue[str | None] = asyncio.Queue()

    def add(self, piece: str) -> Flush | None:
        """Append a text delta; return what was flushed when the buffer became speakable."""
        self.text += piece
        if not self._should_flush():
            return None
        return self._flush(TTS_MIN_EMIT_CHARS)

    def finish(self) -> Flush | None:
        """Flush whatever is left and end the chunk stream; the reply has no more text."""
        self.settled = True
        flushed = self._flush(TTS_FINAL_MIN_CHARS) if self._flushed_to < len(self.text) else None
        self._chunks.put_nowait(None)
        return flushed

    async def chunks(self) -> AsyncIterator[str]:
        """Yield each chunk handed to TTS until the reply settles."""
        while (chunk := await self._chunks.get()) is not None:
            yield chunk

    def heard_through(self, heard: str) -> int:
        """Return the offset in the reply's text the user heard to, at the end of the last whole chunk heard.

        heard is the transcript TTS reports as played; whitespace is ignored because the
        aligned transcript does not keep the chunks' spacing.
        """
        heard_letters = _letters(heard)
        through = 0
        spoken_letters = 0
        for chunk in self._spoken:
            spoken_letters += _letters(chunk.spoken)
            if spoken_letters > heard_letters:
                break
            through = chunk.raw_end
        return through

    def _should_flush(self) -> bool:
        """Sentence-or-size flush, deferred while a tag or an OpenUI fence straddles the boundary."""
        pending = self.text[self._flushed_to :]
        if pending.endswith(SENTENCE_ENDINGS):
            ready = len(pending) >= TTS_MIN_SENTENCE_CHARS
        else:
            ready = len(pending) >= TTS_HARD_FLUSH_CHARS
        if not ready or has_open_openui_fence_at_tail(pending):
            # A split fence leaks its markup into TTS, so it waits until it closes or the reply ends.
            return False
        if has_open_tag_at_tail(pending) and self._deferrals < OPEN_TAG_DEFER_CAP:
            self._deferrals += 1
            return False
        return True

    def _flush(self, min_chars: int) -> Flush:
        raw = self.text[self._flushed_to :]
        self._flushed_to = len(self.text)
        self._deferrals = 0
        spoken = sanitize_for_tts(raw)
        if len(spoken) < min_chars:
            spoken = ""
        if spoken:
            self._spoken.append(_Spoken(spoken=spoken, raw_end=self._flushed_to))
            self._chunks.put_nowait(spoken)
        return Flush(raw=raw, spoken=spoken)


def _letters(text: str) -> int:
    return sum(1 for char in text if not char.isspace())
