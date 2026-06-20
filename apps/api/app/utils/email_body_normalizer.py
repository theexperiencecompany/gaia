"""Email body normalization for LLM consumption.

Strips boilerplate from email bodies — signatures, legal disclaimers,
unsubscribe footers, tracking URL parameters, repeated URL variants,
excess whitespace — while keeping the meaningful content (including
quoted replies, which the user finds useful for thread context).

Pure functions, no side effects. Safe to apply multiple times (idempotent).

Used by ``GMAIL_FETCH_INBOX_SUMMARY`` to keep typical inbox responses
under the inline-context threshold. When the aggregate is still too big,
``WorkspaceCompactionMiddleware`` writes the result to a file the agent
mines with ``bash``/``jq``/``grep``; the offloaded JSONL is meaningfully
smaller too because every message was already normalized.
"""

from __future__ import annotations

from html import unescape
import re

from bs4 import BeautifulSoup

# Signature block: everything after the standard "-- " delimiter on its own
# line (RFC 3676 §4.3). Includes the sender's title, phone, pronouns,
# "Sent from my iPhone", etc. Quoted replies don't start with "-- " so they're
# unaffected.
_SIGNATURE_DELIMITER_RE = re.compile(r"^-- ?$", re.MULTILINE)

# Legal disclaimer markers. Match at the start of a paragraph (preceded by
# blank line or string start). These never contain useful inbox content.
_DISCLAIMER_MARKERS = (
    r"DISCLAIMER:",
    r"CONFIDENTIALITY NOTICE",
    r"This email and any attachments are confidential",
    r"IMPORTANT NOTICE:?",
    r"Please do not reply to this email",
    r"This communication is confidential and privileged",
)
_DISCLAIMER_PATTERN = "(?:" + "|".join(_DISCLAIMER_MARKERS) + ")"
# Find a disclaimer marker anywhere in a paragraph; drop the paragraph.
_DISCLAIMER_RE = re.compile(_DISCLAIMER_PATTERN, re.IGNORECASE)

# Unsubscribe / footer markers. Same paragraph-start rule.
_UNSUBSCRIBE_MARKERS = (
    r"\bunsubscribe\b",
    r"\bmanage preferences\b",
    r"\bupdate preferences\b",
    r"\bview this (?:email|post) in your browser\b",
    r"\bemail preferences\b",
)
_UNSUBSCRIBE_PATTERN = "(?:" + "|".join(_UNSUBSCRIBE_MARKERS) + ")"
# A US postal address (number + words + 2-letter state + ZIP). Catches the
# "Mercury Technologies, Inc. / 2261 Market Street, Suite 86807, San
# Francisco, CA 94114" pattern that appears in marketing footers.
_US_POSTAL_RE = re.compile(
    r"\b\d{1,6}\s+[A-Z][\w\s]{2,40},?\s+Suite\s+\d+,\s+[A-Z][\w\s]+,\s+[A-Z]{2}\s+\d{5}\b"
)
# Find the marker anywhere in the body; the surrounding paragraph is
# considered footer. We split the body on \n\n (paragraph boundary) and
# drop any paragraph containing the marker.
_UNSUBSCRIBE_FOOTER_RE = re.compile(_UNSUBSCRIBE_PATTERN, re.IGNORECASE)

# Tracking URL params. Strip from query strings.
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_name",
    "utm_brand",
    "utm_social",
    "utm_creative_format",
    "utm_creative_id",
    "mc_eid",
    "mc_cid",
    "_hsenc",
    "_hsmi",
    "__cf_chl_jschl_tk__",
    "__cf_chl_fpa_tk",
    "vero_id",
    "vero_conv",
}

# Zero-width and invisible chars
_INVISIBLE_CHARS = "\u200b\u200c\u200d\ufeff"
_INVISIBLE_RE = re.compile("[" + re.escape(_INVISIBLE_CHARS) + "]")

# Multiple blank lines → one
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# An actual HTML tag: ``<tag ...>`` / ``</tag>`` / ``<tag/>``. The tag name must
# follow ``<`` (or ``</``) immediately, so prose like ``a < b > c`` or ``<3``
# is not misread as HTML.
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def strip_signature(body: str) -> str:
    """Remove the signature block (everything after ``-- \\n`` on its own line)."""
    match = _SIGNATURE_DELIMITER_RE.search(body)
    if match is None:
        return body
    return body[: match.start()].rstrip()


def strip_disclaimers(body: str) -> str:
    """Remove legal disclaimer paragraphs (handles multiple)."""
    # Drop any paragraph containing a disclaimer marker.
    paragraphs = body.split("\n\n")
    paragraphs = [p for p in paragraphs if not _DISCLAIMER_RE.search(p)]
    return "\n\n".join(paragraphs).strip()


def strip_unsubscribe_footers(body: str) -> str:
    """Remove unsubscribe / mailing-address footer paragraphs."""
    # Drop any paragraph containing an unsubscribe marker.
    paragraphs = body.split("\n\n")
    paragraphs = [p for p in paragraphs if not _UNSUBSCRIBE_FOOTER_RE.search(p)]
    body = "\n\n".join(paragraphs).strip()
    # Drop multi-line address blocks (≥ 2 lines, contains a US postal
    # address). Inline mentions of addresses in prose are 1-line and
    # have surrounding sentence content, so they're preserved.
    paragraphs = body.split("\n\n")
    kept = []
    for p in paragraphs:
        if not _US_POSTAL_RE.search(p):
            kept.append(p)
            continue
        lines = [line for line in p.splitlines() if line.strip()]
        if len(lines) >= 2:
            continue  # multi-line address block — drop
        kept.append(p)
    return "\n\n".join(kept).strip()


def strip_tracking_params(text: str) -> str:
    """Remove utm_* and similar tracking parameters from URLs.

    Walks each URL in the text. For each URL, drops tracking params and
    rewrites the query-string separator: "?a=1&utm_source=x&b=2" → "?a=1&b=2"
    when the leading '?' was the start of the query, or "?utm_source=x" → ""
    when there are no non-tracking params left.
    """
    url_re = re.compile(r"https?://\S+")
    return url_re.sub(_clean_url, text)


def _clean_url(match: re.Match[str]) -> str:
    """Strip tracking params from a single URL."""
    url = match.group(0)
    # Drop trailing punctuation that often follows URLs in prose.
    trailing = ""
    while url and url[-1] in ".,;:!?":
        trailing = url[-1] + trailing
        url = url[:-1]
    # Split path and query.
    if "?" not in url:
        return url + trailing
    path, query = url.split("?", 1)
    # Parse query into (key, value) pairs, drop tracking keys.
    pairs = [pair for pair in query.split("&") if pair]
    kept = []
    for pair in pairs:
        if "=" in pair:
            key = pair.split("=", 1)[0]
        else:
            key = pair
        if key.lower() in _TRACKING_PARAMS:
            continue
        kept.append(pair)
    if not kept:
        return path + trailing
    return f"{path}?{'&'.join(kept)}{trailing}"


def collapse_whitespace(body: str) -> str:
    """Collapse multiple blank lines, strip trailing whitespace, drop invisible chars."""
    body = _INVISIBLE_RE.sub("", body)
    # Strip trailing spaces/tabs per line with plain string ops. A `[ \t]+$`
    # regex is polynomial (O(n^2)) on long all-whitespace lines (Sonar S5852);
    # rstrip per line is linear and equivalent.
    body = "\n".join(line.rstrip(" \t") for line in body.split("\n"))
    body = _MULTI_BLANK_RE.sub("\n\n", body)
    return body.strip()


def html_to_text(html: str) -> str:
    """Extract plain text from HTML, unescape entities, collapse whitespace.

    Block-level elements (``<p>``, ``<div>``, ``<br>``, ``<li>``, ``<h1-6>``,
    ``<tr>``, ``<br>``, end-of-block) introduce paragraph breaks so the
    paragraph-based rules downstream can identify boilerplate sections.
    """
    if not html or "<" not in html:
        return unescape(html)
    # Parse the raw HTML BEFORE unescaping. Unescaping first would turn an
    # escaped literal like ``&lt;script&gt;keep&lt;/script&gt;`` into a real
    # tag that decompose() then deletes, losing user-visible content. We
    # unescape the extracted text at the end instead.
    soup = BeautifulSoup(html, "html.parser")
    # Drop script/style entirely (they may have text we don't want).
    for tag in soup(["script", "style"]):
        tag.decompose()
    # Insert paragraph break markers around block-level elements so
    # get_text() preserves them, then post-process.
    block_tags = ["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"]
    for tag in soup.find_all(block_tags):
        tag.insert_before("\n\n")
        tag.insert_after("\n\n")
    for br in soup.find_all("br"):
        br.insert_after("\n")
    text = unescape(soup.get_text())
    text = collapse_whitespace(text)
    return text


def normalize_email_body(body: str, *, level: str = "default") -> str:
    """Normalize an email body for LLM consumption.

    Args:
        body: Raw email body text. May be plain text or HTML; the function
            handles both. Pass an empty string returns an empty string.
        level: ``"default"`` applies the full rule set. Currently only one
            level is implemented; the parameter exists for future expansion
            (e.g. an ``"aggressive"`` mode that also strips mailing-list
            footers and template artifacts).

    Returns:
        The normalized body. All rules are idempotent; calling this function
        twice produces the same result as calling it once.

    Note:
        **Quoted replies are intentionally NOT stripped.** Lines starting with
        ``>`` and the ``On <date>, <sender> wrote:`` attribution line are
        preserved — they give context into the older conversation, which
        the user finds useful. See ``test_quoted_replies_are_kept`` for the
        explicit guardrail.
    """
    if not body:
        return body

    # HTML → text first so the text rules operate on clean content. Require an
    # actual tag (not just stray angle brackets) so plain prose isn't mangled.
    if _HTML_TAG_RE.search(body):
        body = html_to_text(body)

    if level == "default":
        body = strip_signature(body)
        body = strip_disclaimers(body)
        body = strip_unsubscribe_footers(body)
        body = strip_tracking_params(body)
        body = collapse_whitespace(body)
    # Future: handle "aggressive" level with extra rules.

    return body
