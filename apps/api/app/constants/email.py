"""
Email Constants.

Constants for email processing and display.
"""

from typing import Literal

from app.constants.log_tags import LogTag

# Per-message fields the Gmail summary tool can project to.
MessageFieldLiteral = Literal[
    "id",
    "threadId",
    "from",
    "to",
    "cc",
    "bcc",
    "subject",
    "snippet",
    "body",
    "time",
    "isRead",
    "hasAttachment",
    "attachments",
    "labels",
]

# Curated per-message fields returned when the caller does not specify any:
# metadata + snippet, deliberately excluding the full `body` and `cc`/`bcc` to
# keep the LLM payload small. An explicit empty list means "all fields" instead.
DEFAULT_SUMMARY_FIELDS: list[MessageFieldLiteral] = [
    "id",
    "threadId",
    "from",
    "to",
    "subject",
    "snippet",
    "time",
    "isRead",
    "hasAttachment",
    "labels",
]

# Default display values
UNKNOWN_SENDER = "[Unknown]"
NO_SUBJECT = "[No Subject]"

# Email attachment resolution (app/services/composio/attachments.py): observability
# and user-facing error prose. Kept as single-line constants so mutation testing
# can suppress them (it cannot suppress interior lines of a multi-line
# log/error call); the tests assert behaviour, not this wording.
EMAIL_ATTACHMENT_FAIL_LOG = "File attachment could not be resolved"  # pragma: no mutate
EMAIL_ATTACHMENT_FAIL_WHY = "The file could not be read or uploaded."  # pragma: no mutate
EMAIL_ATTACHMENT_FAIL_FIX = (
    "Check the workspace path or URL is correct, then retry."  # pragma: no mutate
)

# Gmail compose hooks (app/utils/composio_hooks/gmail_hooks.py) — same single-line
# rule as above. Import LogTag so the f-string prefix stays identical.
GMAIL_TO_MAPPED_LOG = f"{LogTag.COMPOSIO} Mapped 'to' to 'recipient_email' for"  # pragma: no mutate
GMAIL_SKIP_STREAM_LOG = f"{LogTag.COMPOSIO} Skipping streaming: missing fields"  # pragma: no mutate
GMAIL_DRAFT_ID_MISSING_LOG = f"{LogTag.COMPOSIO} Draft response carried no id; compose card with attachments suppressed"  # pragma: no mutate
ATTACHMENTS_NOT_LIST_ERROR = "`attachments` must be a list of file references."  # pragma: no mutate
ATTACHMENTS_NO_USER_ERROR = (
    "Cannot resolve file attachments without a user context."  # pragma: no mutate
)

# Agent-facing description for the friendly ``attachments`` array param (the schema
# itself is derived from AttachmentReference in mail_models, so field changes land
# in one place; only this prose lives here).
EMAIL_ATTACHMENTS_PARAM_DESCRIPTION = (
    "Files to attach. Each item references ONE file by EITHER "
    "'workspace_path' (a file in the current session workspace, e.g. one the user "
    "uploaded or an agent saved there) OR 'url' (a fetchable link). To attach a "
    "Google Drive file, first call GOOGLEDRIVE_DOWNLOAD_FILE and pass the download "
    "URL it returns as 'url'. Total message size must stay under 25 MB."
)

# Email processing limits
EMAIL_QUERY = "in:inbox"
SENT_EMAIL_QUERY = "in:sent"
# Ownership signals (e.g. a social handle the user themselves linked) only exist
# in sent mail, so scans that derive them must span both mailboxes.
INBOX_OR_SENT_EMAIL_QUERY = f"({EMAIL_QUERY} OR {SENT_EMAIL_QUERY})"
MAX_RESULTS = 500
BATCH_SIZE = 50
ONBOARDING_EMAIL_SCAN_LIMIT = 200

# Outbound platform email (transactional sends via app/services/email)
CONTACT_EMAIL = "aryan@heygaia.io"
SUPPORT_EMAIL = "support@heygaia.io"
FOUNDER_SENDER = f"Aryan from GAIA <{CONTACT_EMAIL}>"
SUPPORT_SENDER = f"GAIA Support <{SUPPORT_EMAIL}>"
DISCORD_URL = "https://discord.heygaia.io"
WHATSAPP_URL = "https://whatsapp.heygaia.io"
TWITTER_URL = "https://twitter.com/trygaia"
FOUNDER_MEETING_URL = "https://cal.com/aryanranderiya"

# Email profile previews (email links in chat markdown)
MAILTO_PREFIX = "mailto:"
EMAIL_PROFILE_CACHE_TTL_SECONDS = 24 * 60 * 60
EMAIL_PROFILE_CACHE_KEY_TEMPLATE = "email_profile:{user_id}:{email}"
PEOPLE_SEARCH_ENDPOINT = "https://people.googleapis.com/v1/people:searchContacts"
OTHER_CONTACTS_SEARCH_ENDPOINT = "https://people.googleapis.com/v1/otherContacts:search"
PEOPLE_GET_ENDPOINT_TEMPLATE = "https://people.googleapis.com/v1/{resource_name}"
PEOPLE_SEARCH_READ_MASK = "names,emailAddresses,photos,biographies,organizations"
OTHER_CONTACTS_READ_MASK = "names,emailAddresses,photos"
# Google requires a warmup request before otherContacts/searchContacts return
# results after inactivity; retry once after this delay when a search is empty.
PEOPLE_SEARCH_WARMUP_DELAY_SECONDS = 1.5
DOMAIN_FAVICON_URL_TEMPLATE = "https://www.google.com/s2/favicons?domain={domain}&sz=64"
FREEMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "aol.com",
    }
)
GRAVATAR_PROFILE_URL_TEMPLATE = "https://gravatar.com/{email_hash}.json"
GRAVATAR_TIMEOUT_SECONDS = 5.0
GRAVATAR_CONNECT_TIMEOUT_SECONDS = 3.0
GOOGLE_CONTACTS_SOURCE_NAME = "Google Contacts"
GRAVATAR_SOURCE_NAME = "Gravatar"
