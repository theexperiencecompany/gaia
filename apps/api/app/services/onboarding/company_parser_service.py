"""Service to fetch and parse a company landing page into a CompanyProfile."""

import json
import re
from typing import Optional

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


def _normalize_url(url: str) -> str:
    """Ensure URL has https:// scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url


def _extract_text_from_html(html: str) -> str:
    """Very basic HTML -> plain text. Strip tags, collapse whitespace."""
    # Remove script and style blocks
    html = re.sub(
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

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(
                normalized,
                headers={"User-Agent": "Mozilla/5.0 (compatible; GAIA/1.0)"},
            )
            response.raise_for_status()
            html = response.text

        page_text = _extract_text_from_html(html)

        if len(page_text) < 50:
            log.warning(f"[company_parser] Very little text extracted from {url}")
            return None

        llm = await providers.aget("llm_gemini_flash")
        if llm is None:
            raise RuntimeError("LLM provider not available")
        prompt = COMPANY_PARSE_PROMPT.format(page_content=page_text)
        response_msg = await llm.ainvoke([HumanMessage(content=prompt)])

        # Parse JSON from response - strip markdown fences if present
        content = response_msg.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

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
        log.error(f"[company_parser] Failed to parse {url}: {e}", exc_info=True)
        return None
