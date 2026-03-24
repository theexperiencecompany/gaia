"""Utilities for normalizing noisy email content for LLM contexts."""

from __future__ import annotations

import re
import unicodedata
from html import unescape
from typing import Any, TypedDict

from bs4 import BeautifulSoup

DEFAULT_EMAIL_MAX_CHARS: int | None = None
DEFAULT_PREVIEW_MAX_CHARS: int | None = None

_HTML_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9:-]*(?:\s+[^<>]*)?>")
_BASE64_BLOB_RE = re.compile(r"^(?=.*[+/=])[A-Za-z0-9+/=]{160,}$")
_REPLY_SPLIT_PATTERNS = (
    re.compile(r"^on\s.+wrote:\s*$", re.IGNORECASE),
    re.compile(r"^from:\s.+$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*original message\s*-{2,}\s*$", re.IGNORECASE),
)

_SIGNATURE_SPLIT_PATTERNS = (
    re.compile(r"^--\s*$"),
    re.compile(r"^sent from my\s", re.IGNORECASE),
)

_FOOTER_HINTS = (
    "unsubscribe",
    "manage preferences",
    "view in browser",
    "privacy policy",
)


class NormalizedEmailText(TypedDict):
    """Normalized plain-text email payload for prompt/tool contexts."""

    text: str
    preview: str
    was_html: bool
    truncated: bool
    original_len: int
    kept_len: int


def normalize_email_text(
    raw_text: Any,
    *,
    max_chars: int | None = DEFAULT_EMAIL_MAX_CHARS,
    preview_chars: int | None = DEFAULT_PREVIEW_MAX_CHARS,
    strip_reply_chain: bool = False,
) -> NormalizedEmailText:
    """Normalize email content to compact plain text.

    Steps:
    - Coerce unknown payloads to text
    - Parse HTML when present
    - Remove invisible unicode and base64-like blobs
    - Optionally trim quoted reply chains and common footer boilerplate
    - Normalize whitespace
    - Optional deterministic truncation when max_chars is provided
    """

    text = _coerce_to_text(raw_text)
    if not text:
        return {
            "text": "",
            "preview": "",
            "was_html": False,
            "truncated": False,
            "original_len": 0,
            "kept_len": 0,
        }

    was_html = _looks_like_html(text)
    if was_html:
        text = _html_to_text(text)
    else:
        text = unescape(text)

    text = _remove_invisible_chars(text)
    text = _remove_base64_lines(text)

    if strip_reply_chain:
        text = _strip_reply_chain(text)
        text = _strip_signatures_and_footers(text)

    text = _normalize_whitespace(text)
    original_len = len(text)

    truncated = False
    if max_chars is not None and max_chars > 0:
        text, truncated = truncate_text_with_notice(text, max_chars=max_chars)

    preview = _build_preview(text, max_chars=preview_chars)

    return {
        "text": text,
        "preview": preview,
        "was_html": was_html,
        "truncated": truncated,
        "original_len": original_len,
        "kept_len": len(text),
    }


def truncate_text_with_notice(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Truncate long text deterministically with a compact suffix."""

    if max_chars <= 0:
        return "", bool(text)

    if len(text) <= max_chars:
        return text, False

    suffix_budget = 48
    hard_cutoff = max(1, max_chars - suffix_budget)
    cutoff = _find_readable_cutoff(text, hard_cutoff)
    trimmed = text[:cutoff].rstrip()

    omitted = max(0, len(text) - len(trimmed))
    suffix = f"\n\n[truncated {omitted} chars]"

    available = max_chars - len(suffix)
    if available < 1:
        return text[:max_chars], True

    if len(trimmed) > available:
        trimmed = text[:available].rstrip()
        omitted = max(0, len(text) - len(trimmed))
        suffix = f"\n\n[truncated {omitted} chars]"

    return f"{trimmed}{suffix}", True


def _coerce_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _looks_like_html(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(_HTML_TAG_RE.search(stripped))


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(unescape(html), "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return soup.get_text("\n")


def _remove_invisible_chars(text: str) -> str:
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cf", "Cc"} and char not in {"\n", "\t"}:
            continue
        cleaned.append(char)
    return "".join(cleaned)


def _remove_base64_lines(text: str) -> str:
    kept_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if _BASE64_BLOB_RE.fullmatch(stripped):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def _strip_reply_chain(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    for index, line in enumerate(lines):
        if index < 2:
            continue
        candidate = line.strip()
        if any(pattern.match(candidate) for pattern in _REPLY_SPLIT_PATTERNS):
            return "\n".join(lines[:index])

    return text


def _strip_signatures_and_footers(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text

    total = len(lines)

    for index, line in enumerate(lines):
        candidate = line.strip()
        if not candidate:
            continue

        if any(pattern.match(candidate) for pattern in _SIGNATURE_SPLIT_PATTERNS):
            return "\n".join(lines[:index])

        if index >= total // 2 and any(
            hint in candidate.lower() for hint in _FOOTER_HINTS
        ):
            return "\n".join(lines[:index])

    return text


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v]+", " ", text)
    text = re.sub(r"[ ]+", " ", text)
    text = re.sub(r"\n[ ]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_preview(text: str, *, max_chars: int | None) -> str:
    preview = re.sub(r"\s+", " ", text).strip()
    if max_chars is None:
        return preview
    if max_chars <= 0:
        return ""
    if len(preview) <= max_chars:
        return preview
    return preview[:max_chars].rstrip()


def _find_readable_cutoff(text: str, target: int) -> int:
    if target <= 1:
        return 1

    window_start = max(0, target - 240)

    paragraph_break = text.rfind("\n\n", window_start, target)
    if paragraph_break != -1:
        return paragraph_break

    line_break = text.rfind("\n", window_start, target)
    if line_break != -1:
        return line_break

    sentence_break = text.rfind(". ", window_start, target)
    if sentence_break != -1:
        return sentence_break + 1

    return target
