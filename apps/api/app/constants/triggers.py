"""Trigger identifiers shared by the integration catalog and the handlers that route them."""

from typing import Final

# Composio's sent-mail poll trigger (its slug is also the webhook event type) and
# the GAIA trigger name it is offered under.
GMAIL_EMAIL_SENT_COMPOSIO_SLUG: Final = "GMAIL_EMAIL_SENT_TRIGGER"
GMAIL_EMAIL_SENT_TRIGGER_NAME: Final = "gmail_email_sent"

# The GAIA trigger name for inbound Gmail mail (Composio's GMAIL_NEW_GMAIL_MESSAGE).
GMAIL_NEW_MESSAGE_TRIGGER_NAME: Final = "gmail_new_message"

# Account-level Gmail triggers that fire once per message, inbound or sent.
PER_EMAIL_TRIGGER_NAMES: Final = frozenset(
    {GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME}
)

# How many times a subscription write re-reads the todo and retries after losing a
# compare-and-set to a concurrent write. Two provisions of the same Inbox desk race
# on exactly this append, and three attempts is enough for the loser to see the
# watch the winner stored.
SUBSCRIPTION_WRITE_ATTEMPTS: Final = 3
