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
    # Strip everything that isn't alphanumeric or hyphen
    text = re.sub(r"[^a-z0-9\-]", "", text)
    # Collapse multiple hyphens, strip leading/trailing
    text = re.sub(r"-+", "-", text).strip("-")
    # Enforce max length at a word boundary
    if len(text) > max_length:
        text = text[:max_length].rsplit("-", 1)[0]
    return text
