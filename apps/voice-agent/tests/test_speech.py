"""A reply's text is spoken in sentence-sized chunks, and the heard offset rounds down to the last whole chunk."""

import asyncio

from src.speech import ReplySpeech

FIRST = "Your flight to **Berlin** leaves at nine tomorrow morning."
SECOND = " The hotel near the station is booked for two nights."


def spoken_reply() -> ReplySpeech:
    speech = ReplySpeech("r1")
    speech.add(FIRST)
    speech.add(SECOND)
    speech.finish()
    return speech


def test_each_sentence_is_flushed_once_with_its_markup_left_for_the_screen() -> None:
    speech = ReplySpeech("r1")
    first = speech.add(FIRST)
    assert first is not None
    assert (first.raw, first.spoken) == (
        FIRST,
        "Your flight to Berlin leaves at nine tomorrow morning.",
    )
    assert speech.add(" Short") is None


def test_the_heard_offset_is_the_end_of_the_last_chunk_played_whole() -> None:
    speech = spoken_reply()
    spoken_first = "Your flight to Berlin leaves at nine tomorrow morning."
    assert speech.heard_through("") == 0
    assert speech.heard_through(spoken_first[:20]) == 0
    # The aligned transcript drops the chunks' spacing; only the letters count.
    assert speech.heard_through(spoken_first.replace(" ", "")) == len(FIRST)
    assert speech.heard_through(spoken_first + " The hotel") == len(FIRST)
    assert speech.heard_through(spoken_first + SECOND) == len(FIRST + SECOND)


def test_the_chunks_end_when_the_reply_settles() -> None:
    async def chunks() -> list[str]:
        return [chunk async for chunk in spoken_reply().chunks()]

    assert asyncio.run(chunks()) == [
        "Your flight to Berlin leaves at nine tomorrow morning.",
        "The hotel near the station is booked for two nights.",
    ]
