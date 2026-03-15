"""Extract social profile URLs from email sender info and snippets."""

from shared.py.wide_events import log

from app.models.onboarding_models import SocialProfile

# Platform domains mapped to canonical platform names.
# Each tuple is (domain_substring, platform_name).
_PLATFORM_DOMAINS: list[tuple[str, str]] = [
    ("twitter.com/", "twitter"),
    ("x.com/", "twitter"),
    ("linkedin.com/in/", "linkedin"),
    ("linkedin.com/company/", "linkedin"),
    ("github.com/", "github"),
    ("instagram.com/", "instagram"),
    ("facebook.com/", "facebook"),
    ("youtube.com/@", "youtube"),
    ("youtube.com/c/", "youtube"),
    ("youtube.com/channel/", "youtube"),
    ("medium.com/@", "medium"),
    ("tiktok.com/@", "tiktok"),
    ("mastodon.social/@", "mastodon"),
    ("bsky.app/profile/", "bluesky"),
    ("threads.net/@", "threads"),
]

# Substrings that indicate a URL is generic (not a real profile link).
_GENERIC_PATH_SEGMENTS: list[str] = [
    "/share",
    "/login",
    "/signup",
    "/help",
    "/about",
    "/settings",
    "/intent/",
    "/hashtag/",
    "/search",
    "/explore",
    "/home",
    "/jobs",
]


def _extract_urls_from_text(text: str) -> list[str]:
    """Extract http/https URLs from a text string using simple scanning."""
    urls: list[str] = []
    for prefix in ("https://", "http://"):
        start = 0
        while True:
            idx = text.find(prefix, start)
            if idx == -1:
                break
            # Walk forward to find the end of the URL
            end = idx
            for ch in text[idx:]:
                if ch in (" ", "\n", "\r", "\t", '"', "'", "<", ">", ")", "]", "}"):
                    break
                end += 1
            url = text[idx:end].rstrip(".,;:!?")
            if len(url) > len(prefix) + 5:
                urls.append(url)
            start = end
    return urls


def _classify_url(url: str) -> str | None:
    """Return the platform name if the URL matches a known social profile domain."""
    lower = url.lower()
    for domain, platform in _PLATFORM_DOMAINS:
        if domain in lower:
            return platform
    return None


def _is_generic_url(url: str) -> bool:
    """Return True if the URL looks like a generic/non-profile page."""
    lower = url.lower()
    for segment in _GENERIC_PATH_SEGMENTS:
        if segment in lower:
            return True
    # Reject root-only URLs like "https://twitter.com/" with no username path
    # Find the domain end and check if there's a meaningful path
    for prefix in ("https://", "http://"):
        if lower.startswith(prefix):
            path_part = lower[len(prefix) :]
            # Remove www. prefix
            if path_part.startswith("www."):
                path_part = path_part[4:]
            slash_idx = path_part.find("/")
            if slash_idx == -1:
                return True  # No path at all
            after_slash = path_part[slash_idx + 1 :].strip("/")
            if not after_slash:
                return True  # Root path only
            break
    return False


def extract_social_profiles(emails: list[dict]) -> list[SocialProfile]:
    """
    Scan email sender info and snippets for social profile URLs.

    Looks through email snippets (which often contain signature content)
    and sender fields for known social platform URLs.

    Args:
        emails: List of email dicts with sender, subject, snippet fields.

    Returns:
        Deduplicated list of SocialProfile objects found.
    """
    seen_urls: set[str] = set()
    profiles: list[SocialProfile] = []

    for email in emails:
        # Scan both snippet and sender fields
        texts = [
            email.get("snippet", ""),
            email.get("sender", ""),
            email.get("subject", ""),
        ]
        combined = " ".join(texts)
        if not combined.strip():
            continue

        urls = _extract_urls_from_text(combined)
        for url in urls:
            platform = _classify_url(url)
            if platform is None:
                continue
            if _is_generic_url(url):
                continue
            # Normalize: strip trailing slashes for dedup
            normalized = url.rstrip("/")
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            profiles.append(SocialProfile(platform=platform, url=url))

    log.info(
        f"[social_profiles] Extracted {len(profiles)} profiles "
        f"from {len(emails)} emails"
    )
    return profiles
