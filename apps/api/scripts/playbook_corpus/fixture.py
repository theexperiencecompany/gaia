"""The corpus fixture: one run, its record, and each write_playbook attempt it made."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.models.playbook_models import PlaybookRefusal, PlaybookStep
from app.models.workflow_execution_models import RecordedCall
from app.services.workflow.playbook.record import PlaybookPick

from .translate import Unmappable

#: Where the fixtures live, one JSON file per prod run.
CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "playbook_writes"

#: Refusals of what the author explicitly asked for, which no server can reinterpret:
#: a call that returned nothing (the run should decline no_work_today), a field
#: or step that does not exist, a time the placeholder vocabulary cannot say, a
#: time in a layout the tool was not sent (the refusal names the slot to write).
AUTHOR_CHOICE_REFUSALS = frozenset(
    {
        PlaybookRefusal.EMPTY_RESULT,
        PlaybookRefusal.STEP_REFERENCE,
        PlaybookRefusal.TIME_EXPRESSION,
        PlaybookRefusal.TIME_LAYOUT,
    }
)


class Verdict(StrEnum):
    """What the pick flow does with an attempt."""

    ACCEPTED = "accepted"
    REFUSED = "refused"
    UNMAPPABLE = "unmappable"


class Origin(StrEnum):
    """Where a run came from, and so what its attempts are."""

    #: A prod run: its attempts were hand-written steps, re-expressed here as picks.
    PROD = "prod"
    #: A real-LLM drive on a local stack: its attempts are the picks the model sent.
    DRIVE = "drive"


class OldOutcome(StrEnum):
    """What the flow the attempt ran under did with it."""

    ACCEPTED = "accepted"
    REFUSED = "refused"


class CorpusAttempt(BaseModel):
    """One write_playbook call from prod, re-expressed as picks, and the verdict it must get."""

    model_config = ConfigDict(extra="forbid")

    position: int = Field(description="The call's index in the run's trace")
    record_len: int = Field(description="How many record calls ran before it")
    written: dict[str, object] = Field(description="The hand-written args, anonymised")
    old_outcome: OldOutcome
    picks: list[PlaybookPick] | None = None
    dropped: list[str] = Field(default_factory=list)
    unmappable: Unmappable | None = None
    unmappable_detail: str = ""
    expected: Verdict
    refusals: list[PlaybookRefusal] = Field(default_factory=list)


class CorpusRun(BaseModel):
    """One run that called write_playbook, anonymised."""

    model_config = ConfigDict(extra="forbid")

    run: str = Field(description="Salted hash of the execution id")
    origin: Origin = Origin.PROD
    captured_from: date
    trigger_type: str
    record: list[RecordedCall] = Field(description="The run's pickable calls, in order")
    replaces: list[PlaybookStep] = Field(
        default_factory=list,
        description="The current stored playbook's steps, which every attempt must keep acting",
    )
    attempts: list[CorpusAttempt]
