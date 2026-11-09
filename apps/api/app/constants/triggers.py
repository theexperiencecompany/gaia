"""Trigger identifiers shared by the integration catalog and the handlers that route them."""

from typing import Final

# Composio's sent-mail poll trigger (its slug is also the webhook event type) and
# the GAIA trigger name it is offered under.
GMAIL_EMAIL_SENT_COMPOSIO_SLUG: Final = "GMAIL_EMAIL_SENT_TRIGGER"
GMAIL_EMAIL_SENT_TRIGGER_NAME: Final = "gmail_email_sent"

# The GAIA trigger name for inbound Gmail mail (Composio's GMAIL_NEW_GMAIL_MESSAGE).
GMAIL_NEW_MESSAGE_TRIGGER_NAME: Final = "gmail_new_message"
# The interval-polled trigger on the same Composio event and payload.
GMAIL_POLL_INBOX_TRIGGER_NAME: Final = "gmail_poll_inbox"

# Account-level Gmail triggers that fire once per message, inbound or sent.
PER_EMAIL_TRIGGER_NAMES: Final = frozenset(
    {GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME}
)

# One workflow run per real-world occurrence (e.g. a meeting seen on several calendars).
TRIGGER_OCCURRENCE_KEY: Final = "trigger_occurrence:{workflow_id}:{occurrence}"
TRIGGER_OCCURRENCE_TTL_SECONDS: Final = 24 * 60 * 60
