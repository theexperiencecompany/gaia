"""The email_verdicts collection: one email's JEV answers and the bucket code derived from them."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.constants.desk_buckets import DeskBucket, Judgment
from app.models.document_models import UserScopedDocument
from app.services.quiet_hours_urgency import Urgency


class EmailVerdictDocument(UserScopedDocument):
    """One user's verdict on one Gmail message, kept 48h so the sweep reuses the gate's call.

    answers holds P(true) per judgment JEV was asked; it is empty for a conversation, reply unasked.
    """

    message_id: str
    answers: dict[Judgment, float]
    bucket: DeskBucket | None = None
    # Asked only inside quiet hours.
    urgency: Urgency | None = None
    created_at: datetime | None = None


class EmailVerdictUpdate(BaseModel):
    """A verdict asked again for the same message, replacing the kept one."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[Judgment, float]
    bucket: DeskBucket | None
    urgency: Urgency | None
