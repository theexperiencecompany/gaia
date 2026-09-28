"""Trigger identifiers shared by the integration catalog and the handlers that route them."""

from typing import Final

# Composio's sent-mail poll trigger (its slug is also the webhook event type) and
# the GAIA trigger name it is offered under.
GMAIL_EMAIL_SENT_COMPOSIO_SLUG: Final = "GMAIL_EMAIL_SENT_TRIGGER"
GMAIL_EMAIL_SENT_TRIGGER_NAME: Final = "gmail_email_sent"
