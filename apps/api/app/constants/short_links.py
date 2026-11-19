"""heygaia.link constants."""

#: User-agent markers of the bots that fetch a link to build a chat preview (and
#: the crawlers that run a page's script). Matched case-insensitively; their
#: fetches are never someone opening the link.
UNFURL_BOT_USER_AGENT_MARKERS = (
    "slackbot",
    "facebookexternalhit",
    "facebot",
    "whatsapp/",
    "telegrambot",
    "twitterbot",
    "discordbot",
    "linkedinbot",
    "googlebot",
    "bingbot",
    "applebot",
)

# Snapshot caps: past one, the bytes are not published and the link shows the name and size only.
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024
MAX_HTML_SNAPSHOT_BYTES = 5 * 1024 * 1024
MAX_SVG_SNAPSHOT_BYTES = 2 * 1024 * 1024
#: Text the page renders itself (code, markdown, HTML source) ships in the view up to this size.
MAX_VIEW_TEXT_BYTES = 2 * 1024 * 1024
#: Per owner, where the deployment enforces usage limits.
MAX_PUBLISHED_BYTES_PER_DAY = 500 * 1024 * 1024
MAX_STORED_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
PUBLISHED_BYTES_KEY = "link_content:published_bytes:{user_id}:{day}"
PUBLISHED_BYTES_TTL_SECONDS = 2 * 24 * 3600

#: Installers and executables only ever open for their owner.
EXECUTABLE_EXTENSIONS = frozenset(
    {"exe", "msi", "dmg", "pkg", "apk", "app", "deb", "rpm", "bat", "cmd", "ps1", "scr", "jar"}
)
#: An owner with this many takedowns can share HTML only with specific people.
REPEAT_ABUSE_TAKEDOWNS = 2

# Content ids: 26 lowercase base32 characters (130 bits), one per snapshot and one origin each.
CONTENT_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"
CONTENT_ID_LENGTH = 26
CONTENT_TOKEN_TTL_SECONDS = 600
CONTENT_HMAC_DOMAIN = "link-content"
THUMBNAIL_SIZE = (1200, 630)
THUMBNAIL_MAX_BYTES = 300 * 1024
THUMBNAIL_PATH = "thumb.jpg"

# Rate limits (slowapi strings) on the link routes.
MINT_RATE_LIMIT = "60/hour;500/day"
RESOLVE_RATE_LIMIT = "60/minute"
CONTENT_URL_RATE_LIMIT = "600/minute"
REPORT_RATE_LIMIT = "10/day"
#: Misses (unknown slugs) a viewer may make per window before every resolve is refused for the lockout.
MAX_RESOLVE_MISSES = 20
RESOLVE_MISS_WINDOW_SECONDS = 600
RESOLVE_MISS_LOCKOUT_SECONDS = 3600
RESOLVE_MISS_KEY = "short_link:misses:{viewer}"
RESOLVE_LOCKOUT_KEY = "short_link:lockout:{viewer}"

# Reports: distinct reporters that suspend a link with active or downloadable content, and any other.
ACTIVE_CONTENT_REPORT_THRESHOLD = 3
REPORT_THRESHOLD = 5
