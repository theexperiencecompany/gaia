"""The errors a briefing run fails with."""

from app.services.briefing.errors import VoiceUnreadableError


class TestVoiceUnreadableError:
    def test_the_message_names_every_problem_and_never_the_text(self) -> None:
        error = VoiceUnreadableError(["no JSON object", "message missing"])

        assert str(error) == "The voice reply was no whole voice: no JSON object; message missing"
        assert error.problems == ["no JSON object", "message missing"]
