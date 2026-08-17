"""URL-download tool constants — fetch a URL to a workspace file the model can `read`."""

# Hard ceiling on a downloaded file, enforced while streaming (never trust the
# server's Content-Length). Matches the chat upload cap: a download is just
# another way a file enters the workspace, and should not be able to smuggle in
# something an upload could not.
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024

# Wall-clock budget for the whole fetch, redirects included.
DOWNLOAD_TIMEOUT_SECONDS = 30.0

# A plain, honest UA. Some hosts 403 an empty one; we do not impersonate a
# browser here because this path downloads files, not bot-walled article pages
# (that is `fetch_webpages`, which does send a browser UA).
DOWNLOAD_USER_AGENT = "GAIA/1.0 (+https://heygaia.io)"

# Content types that are web pages, not files. `download` refuses them and points
# at the tool that renders them to text.
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})

DOWNLOAD_HTML_REJECTED = (
    "That URL serves a web page ({content_type}), not a file. Use `fetch_webpages` "
    "to read its content as text instead of `download`."
)
DOWNLOAD_TOO_LARGE = (
    "The file at {url} exceeds the {limit_mb} MB download limit, so it was not saved."
)
