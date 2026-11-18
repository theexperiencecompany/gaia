"""The errors a briefing run fails with."""


class BriefingGenerationError(Exception):
    """The agent did not produce a valid brief — the run failed."""
