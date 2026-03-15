"""Service to fetch and parse a company landing page into a CompanyProfile."""

import ipaddress
import json
import re
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx
from langchain_core.messages import HumanMessage
from shared.py.wide_events import log

from app.core.lazy_loader import providers
from app.models.onboarding_models import CompanyProfile


COMPANY_PARSE_PROMPT = """Parse this company landing page content and extract:
1. Company name
2. A 2-3 sentence description of what the company does and who it serves
3. The industry (one of: SaaS, E-commerce, Agency, Consulting, Education, Healthcare, Fintech, Developer Tools, Consumer, Other)

Page content:
{page_content}

Respond as JSON:
{{
  "name": "...",
  "description": "...",
  "industry": "..."
}}
"""

# Hosts that must never be fetched (SSRF protection)
_BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",  # nosec B104 — this is a blocklist entry for SSRF protection, not a bind address
    "[::1]",
    "metadata.google.internal",
}


def _normalize_url(url: str) -> str:
    """Ensure URL uses https:// scheme. Upgrades plain http:// to https://."""
    url = url.strip()
    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)
    elif not url.startswith("https://"):
        url = f"https://{url}"
    return url


def _is_safe_url(url: str) -> bool:
    """Validate that a URL does not point to internal/private networks (SSRF protection)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname in _BLOCKED_HOSTS:
            return False
        # Resolve hostname and check for private IP ranges
        resolved = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
        for _, _, _, _, addr in resolved:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError, OSError):
        return False
    return True


def _extract_text_from_html(html: str) -> str:
    """Very basic HTML -> plain text. Strip tags, collapse whitespace."""
    # Limit input length before regex processing to avoid excessive backtracking
    html = html[:200_000]
    # Remove script and style blocks
    html = re.sub(  # NOSONAR — bounded input, simple non-overlapping alternation, no ReDoS risk
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Remove all tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4000]  # Limit to 4000 chars for LLM


async def parse_company_url(url: str) -> Optional[CompanyProfile]:
    """
    Fetch a company URL and parse it into a CompanyProfile.

    Args:
        url: Company website URL (with or without scheme)

    Returns:
        CompanyProfile or None if fetch/parse fails
    """
    try:
        normalized = _normalize_url(url)

        if not _is_safe_url(normalized):
            log.warning("[company_parser] Blocked request to non-public URL")
            return None

        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = (
                await client.get(  # NOSONAR — URL is validated by _is_safe_url above
                    normalized,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; GAIA/1.0)"},
                )
            )
            response.raise_for_status()
            html = response.text

        page_text = _extract_text_from_html(html)

        if len(page_text) < 50:
            log.warning("[company_parser] Very little text extracted from URL")
            return None

        llm = await providers.aget("llm_gemini_flash")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        prompt = COMPANY_PARSE_PROMPT.format(page_content=page_text)
        response_msg = await llm.ainvoke([HumanMessage(content=prompt)])

        # Strip markdown fences if the LLM wrapped the JSON in a code block
        content = response_msg.content.strip()
        if content.startswith("```"):
            # Remove opening fence (e.g. ```json or ```)
            content = (
                content[content.index("\n") + 1 :] if "\n" in content else content[3:]
            )
        if content.endswith("```"):
            content = content[: content.rfind("```")].rstrip()

        result_data = json.loads(content)

        profile = CompanyProfile(
            name=result_data.get("name", ""),
            description=result_data.get("description", ""),
            industry=result_data.get("industry"),
        )

        log.info(
            f"[company_parser] Parsed company: {profile.name} ({profile.industry})"
        )
        return profile

    except Exception as e:
        log.error(f"[company_parser] Failed to parse company URL: {e}", exc_info=True)
        return None
