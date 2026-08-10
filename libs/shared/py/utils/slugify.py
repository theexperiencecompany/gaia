import re
import unicodedata


def slugify(text: str, max_length: int = 80) -> str:
    """Convert a title to a URL-safe kebab-case slug.

    Examples:
        "Daily Email Summary" -> "daily-email-summary"
        "Gmail -> Slack Alerts" -> "gmail-slack-alerts"
        "  Spaces & Special! Chars " -> "spaces-special-chars"
    """
    # Normalize unicode (e -> e, u -> u, etc.)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    text = text.lower()
    # Replace common separators with hyphens
    text = re.sub(r"[→&/\\|+@#%^*=<>]", "-", text)
    # Word separators become hyphens. Without this the strip below deletes them
    # outright and every multi-word title collapses into one run-together word
    # ("Daily Email Summary" -> "dailyemailsummary"), which is the opposite of
    # what a slug is for.
    text = re.sub(r"\s+", "-", text)

    # Strip everything that isn't alphanumeric or hyphen
    text = re.sub(r"[^a-z0-9\-]", "", text)
    # Collapse multiple hyphens, strip leading/trailing
    text = re.sub(r"-+", "-", text).strip("-")
    # Enforce max length at a word boundary
    if len(text) > max_length:
        cut = text[:max_length]
        # Only trim back to the previous boundary when the cut landed *inside* a
        # word. A cut that lands exactly on a hyphen is already at a boundary, and
        # rsplitting it anyway throws away a whole word that fit
        # ("one two three", max_length=7 -> "one-two", not "one").
        if not cut.endswith("-") and text[max_length] != "-":
            cut = cut.rsplit("-", 1)[0]
        text = cut.rstrip("-")

    return text
