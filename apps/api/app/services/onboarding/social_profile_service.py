"""Extract and save social profile URLs from email sender info and snippets."""

import urllib.parse

from bson import ObjectId
from langchain_core.messages import HumanMessage

from app.agents.prompts.onboarding_prompts import SOCIAL_PROFILE_FILTER_PROMPT
from app.core.lazy_loader import providers
from app.db.mongodb.collections import users_collection
from app.models.onboarding_models import SocialProfile, SocialProfileFilterOutput
from shared.py.wide_events import log

# URLs containing these are marketing/newsletter links, not user profiles.
_TRACKING_INDICATORS = ("utm_source=", "utm_medium=", "utm_campaign=")


def _is_tracking_url(url: str) -> bool:
    lower = url.lower()
    return any(ind in lower for ind in _TRACKING_INDICATORS)


# (domain_substring, canonical_platform_name)
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


def _canonicalize_social_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        clean = parsed._replace(query="", fragment="", netloc=parsed.netloc.lower())
        return urllib.parse.urlunparse(clean).rstrip("/")
    except Exception:
        return url.rstrip("/")


def _extract_urls_from_text(text: str) -> list[str]:
    urls: list[str] = []
    for prefix in ("https://", "http://"):
        start = 0
        while True:
            idx = text.find(prefix, start)
            if idx == -1:
                break
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
    lower = url.lower()
    for domain, platform in _PLATFORM_DOMAINS:
        if domain in lower:
            return platform
    return None


def _is_generic_url(url: str) -> bool:
    lower = url.lower()
    for segment in _GENERIC_PATH_SEGMENTS:
        if segment in lower:
            return True
    for prefix in ("https://", "http://"):
        if lower.startswith(prefix):
            path_part = lower[len(prefix) :]
            path_part = path_part.removeprefix("www.")
            slash_idx = path_part.find("/")
            if slash_idx == -1:
                return True
            after_slash = path_part[slash_idx + 1 :].strip("/")
            if not after_slash:
                return True
            break
    return False


def _extract_handle_from_url(url: str, platform: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(url.lower())
        path = parsed.path.strip("/")
        path = path.removeprefix("@")
        segments = path.split("/")
        handle = segments[0] if segments else ""
        if not handle or len(handle) > 60:
            return None
        for segment in _GENERIC_PATH_SEGMENTS:
            if handle in segment.strip("/"):
                return None
        return handle
    except Exception:
        return None


async def extract_social_profiles_from_emails(
    emails: list[dict],
    user_name: str | None,
    user_email: str | None,
) -> list[SocialProfile]:
    """Extract social profiles from emails: broad URL harvest + LLM ownership
    filter to keep only profiles owned by the user."""
    candidates: dict[tuple[str, str], dict] = {}

    for email in emails:
        body = email.get("body", "") or email.get("snippet", "") or email.get("messageText", "")
        sender = email.get("sender", "") or email.get("from", "")
        subject = email.get("subject", "")
        combined = f"{body} {sender} {subject}"
        if not combined.strip():
            continue

        is_sent = "SENT" in email.get("labelIds", []) or bool(email.get("from_sent", False))

        urls = _extract_urls_from_text(combined)
        for url in urls:
            if _is_tracking_url(url):
                continue
            platform = _classify_url(url)
            if platform is None:
                continue
            if _is_generic_url(url):
                continue

            canonical = _canonicalize_social_url(url)
            handle = _extract_handle_from_url(canonical, platform)
            if not handle:
                continue

            key = (platform, handle)
            if key not in candidates:
                candidates[key] = {
                    "platform": platform,
                    "handle": handle,
                    "canonical_url": canonical,
                    "frequency": 0,
                    "is_sent": False,
                    "contexts": [],
                }
            entry = candidates[key]
            entry["frequency"] += 1
            if is_sent:
                entry["is_sent"] = True
            if len(entry["contexts"]) < 5:
                entry["contexts"].append(
                    {
                        "sender": sender[:100],
                        "subject": subject[:100],
                        "snippet": (email.get("snippet", "") or "")[:120],
                    }
                )

    if not candidates:
        log.info("[social_profiles_smart] No social URL candidates found in emails")
        return []

    by_platform: dict[str, list[dict]] = {}
    for entry in candidates.values():
        p = entry["platform"]
        if p not in by_platform:
            by_platform[p] = []
        by_platform[p].append(entry)

    capped: list[dict] = []
    for platform_entries in by_platform.values():
        sorted_entries = sorted(
            platform_entries,
            key=lambda e: (e["is_sent"], e["frequency"]),
            reverse=True,
        )
        capped.extend(sorted_entries[:8])

    log.info(
        f"[social_profiles_smart] Harvested {len(capped)} candidates "
        f"across {len(by_platform)} platforms from {len(emails)} emails"
    )

    for entry in capped:
        sent_label = "SENT" if entry["is_sent"] else "recv"
        log.info(
            f"[social_profiles_smart] candidate: {entry['platform']}/{entry['handle']} "
            f"freq={entry['frequency']} {sent_label}"
        )

    candidates_lines: list[str] = []
    for entry in capped:
        sent_label = "yes" if entry["is_sent"] else "no"
        header = (
            f"Platform: {entry['platform']} | Handle: {entry['handle']} | "
            f"Appeared in {entry['frequency']} email(s) | Sent email: {sent_label}"
        )
        context_lines = []
        for i, ctx in enumerate(entry["contexts"], 1):
            context_lines.append(
                f"  Context {i} — From: {ctx['sender']} | "
                f'Subject: {ctx["subject"]} | "{ctx["snippet"]}"'
            )
        candidates_lines.append(header)
        candidates_lines.extend(context_lines)
        candidates_lines.append("")

    candidates_text = "\n".join(candidates_lines).strip()

    sent_fallback = [
        SocialProfile(platform=e["platform"], url=e["canonical_url"])
        for e in capped
        if e["is_sent"]
    ]

    try:
        llm = await providers.aget("gemini_llm")
        if llm is None:
            log.warning("[social_profiles_smart] LLM not available, using sent-email fallback")
            return dedup_profiles_by_platform(sent_fallback)

        structured_llm = llm.with_structured_output(SocialProfileFilterOutput)
        prompt = SOCIAL_PROFILE_FILTER_PROMPT.format(
            user_name=user_name or "Unknown",
            user_email=user_email or "Unknown",
            candidates=candidates_text,
        )
        result: SocialProfileFilterOutput = await structured_llm.ainvoke(
            [HumanMessage(content=prompt)]
        )

        url_lookup: dict[tuple[str, str], str] = {
            (e["platform"], e["handle"]): e["canonical_url"] for e in capped
        }

        owned: list[SocialProfile] = []
        for item in result.owned_profiles:
            item_platform = str(item.get("platform") or "")
            item_handle = str(item.get("handle") or "")
            canonical_url = url_lookup.get((item_platform, item_handle))
            if canonical_url:
                owned.append(SocialProfile(platform=item_platform, url=canonical_url))

        log.info(
            f"[social_profiles_smart] LLM filtered to {len(owned)} owned profiles "
            f"from {len(capped)} candidates"
        )
        if owned:
            for p in owned:
                log.info(f"[social_profiles_smart] accepted: {p.platform} → {p.url}")
        else:
            log.info(
                f"[social_profiles_smart] LLM returned 0 owned. "
                f"Raw output: {result.owned_profiles!r}"
            )
        return dedup_profiles_by_platform(owned)

    except Exception as e:
        log.error(
            f"[social_profiles_smart] LLM filter failed, using sent-email fallback: {e}",
            exc_info=True,
        )
        return dedup_profiles_by_platform(sent_fallback)


def dedup_profiles_by_platform(profiles: list[SocialProfile]) -> list[SocialProfile]:
    seen: set[str] = set()
    result: list[SocialProfile] = []
    for p in profiles:
        if p.platform not in seen:
            seen.add(p.platform)
            result.append(p)
    return result


async def save_confirmed_profiles(user_id: str, profiles: list[dict]) -> None:
    """Persist user-confirmed social profiles, overwriting extracted ones."""
    await users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"onboarding.social_profiles": profiles}},
    )
    log.info(f"[social_profiles] Saved {len(profiles)} confirmed profiles for {user_id}")
