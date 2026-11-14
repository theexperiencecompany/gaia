"""The waits collection: one waiter to pick back up once the user does what GAIA asked."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.constants.waits import WaitCondition, WaiterKind
from app.models.document_models import UserScopedDocument


class WaitKey(BaseModel):
    """Who waits on what: one wait per user, condition, subject and waiter."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    condition: WaitCondition
    subject_id: str
    waiter: WaiterKind
    waiter_id: str


class WaitDocument(UserScopedDocument):
    """A waiter kept until its condition is met or 7 days pass after the latest ask.

    stream_id is the asking run's, so a run still live can be released from what blocked it.
    """

    condition: WaitCondition
    subject_id: str
    subject_name: str
    waiter: WaiterKind
    waiter_id: str
    stream_id: str | None = None
    created_at: datetime


class WaitUpdate(BaseModel):
    """A repeat ask: the newest name and run replace the kept ones."""

    model_config = ConfigDict(extra="forbid")

    subject_name: str
    stream_id: str | None


class WaitMetPayload(BaseModel):
    """The trigger payload a todo waiter is woken with: GAIA's note on what the user did."""

    message: str
