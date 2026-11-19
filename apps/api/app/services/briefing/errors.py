"""The errors a briefing run fails with."""


class BriefingGenerationError(Exception):
    """The agent did not produce a valid brief — the run failed."""


class VoiceUnreadableError(BriefingGenerationError):
    """The daily run's reply held no voice JSON; problems name why, never its text."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(f"No valid voice JSON in agent output: {'; '.join(problems)}")
        self.problems = problems
