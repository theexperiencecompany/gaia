"""The errors a briefing run fails with."""

from app.services.briefing.errors import VoiceUnreadableError


class TestVoiceUnreadableError:
    def test_the_message_names_every_problem_and_never_the_text(self) -> None:
        error = VoiceUnreadableError(["no JSON object", "message missing"])

        assert str(error) == "The voice reply was no whole voice: no JSON object; message missing"
        assert error.problems == ["no JSON object", "message missing"]

    def test_a_reply_that_came_back_is_kept_whole(self) -> None:
        assert (
            VoiceUnreadableError(["no JSON object"], "half a sentence").reply == "half a sentence"
        )

    def test_a_missing_or_empty_reply_reads_as_no_readable_reply(self) -> None:
        assert VoiceUnreadableError(["x"]).reply == "(no readable reply)"
        assert VoiceUnreadableError(["x"], "").reply == "(no readable reply)"
