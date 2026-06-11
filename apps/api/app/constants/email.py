"""
Email Constants.

Constants for email processing and display.
"""

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
PEOPLE_SEARCH_READ_MASK = "names,emailAddresses,photos,biographies,organizations"
GRAVATAR_PROFILE_URL_TEMPLATE = "https://gravatar.com/{email_hash}.json"
GRAVATAR_TIMEOUT_SECONDS = 5.0
GRAVATAR_CONNECT_TIMEOUT_SECONDS = 3.0
GOOGLE_CONTACTS_SOURCE_NAME = "Google Contacts"
GRAVATAR_SOURCE_NAME = "Gravatar"
