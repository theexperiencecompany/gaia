from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.repositories.base import UserScopedDocument


class MailDocument(UserScopedDocument):
    """An analyzed-email importance summary as stored in the mail collection.

    ``extra="allow"`` because the analyzer stores a variable set of summary fields
    that the read endpoints return verbatim; keeping them avoids dropping data.
    """

    model_config = ConfigDict(extra="allow")

    message_id: str
    is_important: bool = False
    analyzed_at: datetime | None = None


class MailUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_important: bool | None = None
