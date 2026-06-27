"""
Email Constants.

Constants for email processing and display.
"""

from typing import Literal

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

# Email processing limits
EMAIL_QUERY = "in:inbox"
MAX_RESULTS = 500
BATCH_SIZE = 50
ONBOARDING_EMAIL_SCAN_LIMIT = 200

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
