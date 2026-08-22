"""Extract and save social profile URLs from email sender info and snippets."""

from typing import Any
import urllib.parse

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.llm.client import ainvoke_llm, get_helper_llm
from app.agents.llm.exceptions import LLMNotConfiguredError
from app.agents.prompts.onboarding_prompts import SOCIAL_PROFILE_FILTER_PROMPT
from app.constants.log_tags import LogTag
from app.db.repositories.users import user_repository
from app.models.onboarding_models import SocialProfile, SocialProfileFilterOutput
from shared.py.wide_events import log

# URLs containing these are marketing/newsletter links, not user profiles.
_TRACKING_INDICATORS = ("utm_source=", "utm_medium=", "utm_campaign=")

_MAX_CANDIDATES_PER_PLATFORM = 8
_MAX_CONTEXTS_PER_CANDIDATE = 5
_MAX_CONTEXT_FIELD_LEN = 100
_MAX_CONTEXT_SNIPPET_LEN = 120
_MAX_HANDLE_LEN = 60
_MIN_URL_CHARS_AFTER_SCHEME = 5


class _CandidateContext(BaseModel):
    """One email a candidate URL appeared in, as shown to the ownership LLM."""

    sender: str
    subject: str
    snippet: str


class _ProfileCandidate(BaseModel):
    """A harvested social URL plus the evidence used to judge ownership."""

    platform: str
    handle: str
    canonical_url: str
    frequency: int = 0
    is_sent: bool = False
    contexts: list[_CandidateContext] = []


def _is_tracking_url(url: str) -> bool:
    lower = url.lower()
    return any(ind in lower for ind in _TRACKING_INDICATORS)


# (url_prefix_up_to_the_handle, canonical_platform_name). The prefix includes any
# path segment that precedes the handle, so the handle is whatever follows it.
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

# Path segments that mark a URL as generic navigation rather than a profile link.
_GENERIC_PATH_SEGMENTS: frozenset[str] = frozenset(
    {
        "share",
        "login",
        "signup",
        "help",
        "about",
        "settings",
        "intent",
        "hashtag",
        "search",
        "explore",
        "home",
        "jobs",
    }
)


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
            if len(url) > len(prefix) + _MIN_URL_CHARS_AFTER_SCHEME:
                urls.append(url)
            start = end
    return urls


def _match_platform(url: str) -> tuple[str, str] | None:
    """Return (platform, the URL remainder that starts at the handle), or None."""
    lower = url.lower()
    for domain, platform in _PLATFORM_DOMAINS:
        idx = lower.find(domain)
        if idx != -1:
            return platform, lower[idx + len(domain) :]
    return None


def _is_generic_url(url: str) -> bool:
    try:
        path = urllib.parse.urlparse(url.lower()).path
    except ValueError:
        return True
    segments = [seg.removeprefix("@") for seg in path.split("/") if seg]
    if not segments:
        return True
    return any(seg in _GENERIC_PATH_SEGMENTS for seg in segments)


def _extract_handle(remainder: str) -> str | None:
    """Take the handle out of the URL remainder produced by `_match_platform`."""
    handle = remainder.split("/", maxsplit=1)[0].removeprefix("@")
    if not handle or len(handle) > _MAX_HANDLE_LEN:
        return None
    return handle


async def extract_social_profiles_from_emails(
    emails: list[dict[str, Any]],
    user_name: str | None,
    user_email: str | None,
) -> list[SocialProfile]:
    """Extract social profiles from emails: broad URL harvest + LLM ownership
    filter to keep only profiles owned by the user."""
    candidates: dict[tuple[str, str], _ProfileCandidate] = {}

    for email in emails:
        body = email.get("body", "") or email.get("snippet", "") or email.get("messageText", "")
        sender = email.get("sender", "") or email.get("from", "")
        subject = email.get("subject", "")
        combined = f"{body} {sender} {subject}"
        if not combined.strip():
            continue

        is_sent = "SENT" in (email.get("labelIds") or email.get("label_ids") or [])

        seen_in_email: set[tuple[str, str]] = set()
        urls = _extract_urls_from_text(combined)
        for url in urls:
            if _is_tracking_url(url):
                continue

            canonical = _canonicalize_social_url(url)
            matched = _match_platform(canonical)
            if matched is None:
                continue
            platform, remainder = matched
            if _is_generic_url(canonical):
                continue

            handle = _extract_handle(remainder)
            if not handle:
                continue

            key = (platform, handle)
            # One email counts once per profile, however often it repeats the link.
            if key in seen_in_email:
                continue
            seen_in_email.add(key)

            if key not in candidates:
                candidates[key] = _ProfileCandidate(
                    platform=platform,
                    handle=handle,
                    canonical_url=canonical,
                )
            entry = candidates[key]
            entry.frequency += 1
            if is_sent:
                entry.is_sent = True
            if len(entry.contexts) < _MAX_CONTEXTS_PER_CANDIDATE:
                entry.contexts.append(
                    _CandidateContext(
                        sender=sender[:_MAX_CONTEXT_FIELD_LEN],
                        subject=subject[:_MAX_CONTEXT_FIELD_LEN],
                        snippet=(email.get("snippet", "") or "")[:_MAX_CONTEXT_SNIPPET_LEN],
                    )
                )

    if not candidates:
        log.info(f"{LogTag.ONBOARDING} No social URL candidates found in emails")
        return []

    by_platform: dict[str, list[_ProfileCandidate]] = {}
    for entry in candidates.values():
        platform_name = entry.platform
        if platform_name not in by_platform:
            by_platform[platform_name] = []
        by_platform[platform_name].append(entry)

    capped: list[_ProfileCandidate] = []
    for platform_entries in by_platform.values():
        sorted_entries = sorted(
            platform_entries,
            key=lambda e: (e.is_sent, e.frequency),
            reverse=True,
        )
        capped.extend(sorted_entries[:_MAX_CANDIDATES_PER_PLATFORM])

    log.info(
        f"{LogTag.ONBOARDING} Harvested social URL candidates across platforms from emails",
        capped_count=len(capped),
        by_platform_count=len(by_platform),
        emails_count=len(emails),
    )

    for entry in capped:
        sent_label = "SENT" if entry.is_sent else "recv"
        log.info(
            f"{LogTag.ONBOARDING} social profile candidate: / freq",
            entry_platform=entry.platform,
            entry_handle=entry.handle,
            entry_frequency=entry.frequency,
            sent_label=sent_label,
        )

    candidates_lines: list[str] = []
    for entry in capped:
        sent_label = "yes" if entry.is_sent else "no"
        header = (
            f"Platform: {entry.platform} | Handle: {entry.handle} | "
            f"Appeared in {entry.frequency} email(s) | Sent email: {sent_label}"
        )
        context_lines = []
        for i, ctx in enumerate(entry.contexts, 1):
            context_lines.append(
                f'  Context {i} — From: {ctx.sender} | Subject: {ctx.subject} | "{ctx.snippet}"'
            )
        candidates_lines.append(header)
        candidates_lines.extend(context_lines)
        candidates_lines.append("")

    candidates_text = "\n".join(candidates_lines).strip()

    sent_fallback = [
        SocialProfile(platform=e.platform, url=e.canonical_url) for e in capped if e.is_sent
    ]

    try:
        try:
            llm = get_helper_llm()
        except LLMNotConfiguredError:
            log.warning(
                f"{LogTag.ONBOARDING} social_profiles LLM not available, using sent-email fallback"
            )
            return dedup_profiles_by_platform(sent_fallback)

        structured_llm = llm.with_structured_output(SocialProfileFilterOutput)
        prompt = SOCIAL_PROFILE_FILTER_PROMPT.format(
            user_name=user_name or "Unknown",
            user_email=user_email or "Unknown",
            candidates=candidates_text,
        )
        result: SocialProfileFilterOutput = await ainvoke_llm(
            structured_llm, [HumanMessage(content=prompt)], label="onboarding_social_profile"
        )

        url_lookup: dict[tuple[str, str], str] = {
            (e.platform, e.handle): e.canonical_url for e in capped
        }

        owned: list[SocialProfile] = []
        for item in result.owned_profiles:
            # The LLM echoes back handles from the prompt; don't lose a profile to casing.
            item_platform = item.platform.strip().lower()
            item_handle = item.handle.strip().lower()
            canonical_url = url_lookup.get((item_platform, item_handle))
            if canonical_url:
                owned.append(SocialProfile(platform=item_platform, url=canonical_url))

        log.info(
            f"{LogTag.ONBOARDING} social_profiles LLM filtered to owned profiles from candidates",
            owned_count=len(owned),
            capped_count=len(capped),
        )
        if owned:
            for p in owned:
                log.info(
                    f"{LogTag.ONBOARDING} social_profiles accepted", platform=p.platform, url=p.url
                )
        else:
            log.info(
                f"{LogTag.ONBOARDING} social_profiles LLM returned 0 owned. Raw output",
                owned_profiles=result.owned_profiles,
            )
        return dedup_profiles_by_platform(owned)

    except Exception as e:
        log.error(
            f"{LogTag.ONBOARDING} social_profiles LLM filter failed, using sent-email fallback",
            error=str(e),
            error_type=type(e).__name__,
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


async def save_confirmed_profiles(user_id: str, profiles: list[SocialProfile]) -> None:
    """Persist user-confirmed social profiles, overwriting extracted ones."""
    await user_repository.set_social_profiles(user_id, profiles)
    log.info(
        f"{LogTag.ONBOARDING} Saved confirmed social profiles for",
        profiles_count=len(profiles),
        user_id=user_id,
    )
