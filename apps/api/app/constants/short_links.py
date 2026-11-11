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
