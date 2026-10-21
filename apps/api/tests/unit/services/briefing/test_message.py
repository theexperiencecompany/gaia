"""The written message is the brief's one text; each surface frames it, none rewrites it."""

from typing import Any

import pytest

from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.briefing_models import BriefingPayload
from app.services.briefing.message import brief_message, chat_text, preheader
from app.utils.message_breaks import split_message_bubbles

_LINK = "https://heygaia.io/brief/brief_1"
_MESSAGE = "Priya's deck is waiting on you.\n\nSequoia at 11:00.\nThen lunch with Dhruv."


def _payload(**overrides: Any) -> BriefingPayload:
    data: dict[str, Any] = {
        "kicker": "K",
        "date": "2026-10-14",
        "headline": "The deck, then Sequoia",
        "lede": "lede",
        "mood": "packed",
        "caption": "c",
        "message": _MESSAGE,
    }
    data.update(overrides)
    return BriefingPayload.model_validate(data)


@pytest.mark.unit
class TestChatText:
    def test_the_headline_is_its_own_bubble_and_the_message_follows_with_the_link(self) -> None:
        text = chat_text(_payload(), _LINK)

        assert split_message_bubbles(text) == [
            "The deck, then Sequoia",
            f"{_MESSAGE}\n\nFull brief: {_LINK}",
        ]

    def test_the_message_keeps_its_line_breaks(self) -> None:
        text = chat_text(_payload(), _LINK)

        assert text.split(NEW_MESSAGE_BREAKER)[1].startswith(_MESSAGE)


@pytest.mark.unit
class TestPreheader:
    def test_the_message_reads_as_one_preview_line(self) -> None:
        assert preheader(_payload()) == (
            "Priya's deck is waiting on you. Sequoia at 11:00. Then lunch with Dhruv."
        )


@pytest.mark.unit
class TestLinkedPhrases:
    _LINKED = "The [venue shortlist](https://heygaia.link/v1) is ready.\nPick one."

    def test_chat_keeps_the_markdown_link_each_bot_renders_natively(self) -> None:
        text = chat_text(_payload(message=self._LINKED), _LINK)

        assert "The [venue shortlist](https://heygaia.link/v1) is ready." in text

    def test_the_preview_line_shows_the_phrase_without_its_url(self) -> None:
        assert preheader(_payload(message=self._LINKED)) == (
            "The venue shortlist is ready. Pick one."
        )


@pytest.mark.unit
class TestBriefMessage:
    @pytest.mark.parametrize("message", [None, ""])
    def test_a_brief_without_a_message_raises_instead_of_sending_nothing(
        self, message: str | None
    ) -> None:
        with pytest.raises(ValueError, match="2026-10-14"):
            brief_message(_payload(message=message))

    def test_a_written_message_is_returned_as_written(self) -> None:
        assert brief_message(_payload()) == _MESSAGE
