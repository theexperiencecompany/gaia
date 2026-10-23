"""The brief's text on each surface: the message the model wrote, framed per channel.

The message is the one canonical text. Chat posts the edition image captioned with the
headline, then the message ending on the full-brief link; the email and the in-app
notification carry the message as it is.
"""

from app.config.settings import settings
from app.constants.general import NEW_MESSAGE_BREAKER
from app.models.briefing_models import BriefingPayload


def brief_path(briefing_id: str) -> str:
    """Return the app path of one brief's standalone page."""
    return f"/brief/{briefing_id}"


def full_brief_url(briefing_id: str) -> str:
    """Where the brief's link sends the reader: its own page in the app."""
    return f"{settings.FRONTEND_URL}{brief_path(briefing_id)}"


def brief_message(payload: BriefingPayload) -> str:
    """Return the written message; a brief without one never passed generation, so it raises."""
    if not payload.message:
        raise ValueError(f"the {payload.date} brief has no message to deliver")
    return payload.message


def chat_text(payload: BriefingPayload, link: str) -> str:
    """Return the chat post: the headline bubble (the image's caption), then the message and link."""
    return f"{payload.headline}{NEW_MESSAGE_BREAKER}{brief_message(payload)}\n\nFull brief: {link}"


def preheader(payload: BriefingPayload) -> str:
    """Return the inbox preview line under the subject: the message on one line."""
    return " ".join(line.strip() for line in brief_message(payload).splitlines() if line.strip())
