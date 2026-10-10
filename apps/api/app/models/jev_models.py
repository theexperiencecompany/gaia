"""JEV Decisions API wire shapes and the verdicts HIL reads out of them."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from app.constants.hil import ReplyChoice


class JevUsage(BaseModel):
    """Token counts a Decisions API response reports."""

    input_tokens: int | None = None
    output_tokens: int | None = None


class JevChoiceAnswer(BaseModel):
    """One question's answer; only type "choice" carries a verdict."""

    type: str | None = None
    choice: str
    confidence: float | None = None
    probabilities: dict[str, float] | None = None


class JevDecisionsResponse(BaseModel):
    """A Decisions API body, answers keyed by the question names the request sent."""

    answers: dict[str, JevChoiceAnswer]
    usage: JevUsage | None = None

    def choice(
        self, question: str, allowed: Collection[str], *, label: str = ""
    ) -> JevChoiceAnswer:
        """Return the named question's answer; raise unless it is a choice among allowed."""
        answer = self.answers.get(question)
        if answer is None:
            raise ValueError(f"JEV {label}answer missing for question {question!r}")
        if answer.type != "choice":
            raise ValueError(f"non-choice JEV {label}answer: {answer!r}"[:300])
        if answer.choice not in allowed:
            raise ValueError(f"unknown JEV {label}choice: {answer.choice!r}")
        return answer

    def tokens(self) -> tuple[int, int]:
        """Return (input, output) tokens, zero when the body reports none."""
        usage = self.usage or JevUsage()
        return int(usage.input_tokens or 0), int(usage.output_tokens or 0)


@dataclass(frozen=True)
class JevReplyVerdict:
    """What JEV said one chat reply means for one pending action."""

    choice: ReplyChoice
    confidence: float
    probabilities: Mapping[str, float]
