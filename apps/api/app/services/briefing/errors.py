"""The errors a briefing run fails with."""


class BriefingGenerationError(Exception):
    """The agent did not produce a valid brief — the run failed."""


class VoiceUnreadableError(BriefingGenerationError):
    """The voice call's reply was no whole voice; problems name why, reply is what came back."""

    def __init__(self, problems: list[str], reply: str | None = None) -> None:
        super().__init__(f"The voice reply was no whole voice: {'; '.join(problems)}")
        self.problems = problems
        self.reply = reply or "(no readable reply)"
