"""
Integration Inference Service.

LLM-backed inference for published custom integrations: their marketplace
``category`` and the rich detail-page ``content`` (use cases, how-it-works,
FAQs). Native integrations ship both curated by hand in
``app/config/oauth_content.py``; custom integrations get them generated here at
publish time so they show tailored copy instead of the frontend's generic
fallbacks.

Both run on the default model (``gemini-3.1-flash-lite``) via ``get_default_llm``
+ ``ainvoke_llm`` — the same path used for memory extraction, follow-ups, and
research helpers.
"""

import asyncio
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage

from app.agents.llm.client import ainvoke_llm, get_default_llm
from app.constants.integrations import (
    CATEGORY_INFERENCE_PROMPT,
    CONTENT_INFERENCE_PROMPT,
    FAQ_COUNT,
    HOW_IT_WORKS_COUNT,
    INTEGRATION_CATEGORIES,
    MAX_TOOLS_FOR_CATEGORY,
    MAX_TOOLS_FOR_CONTENT,
    USE_CASES_COUNT,
)
from app.constants.log_tags import LogTag
from app.models.oauth_models import IntegrationContent
from shared.py.wide_events import log

_FALLBACK_CATEGORY = "other"
# Best-effort caps so a slow upstream LLM never stalls the inline publish flow.
_CONTENT_GENERATION_TIMEOUT_SECONDS = 12
_CATEGORY_INFERENCE_TIMEOUT_SECONDS = 10


def _tools_summary(tools: list[dict[str, Any]], limit: int) -> str:
    """Comma-joined names of the first ``limit`` tools, or "None" when empty."""
    names = [str(t.get("name")) for t in tools[:limit] if t.get("name")]
    return ", ".join(names) or "None"


def _server_domain(server_url: str) -> str:
    # .hostname (not .netloc) so any embedded credentials/port never leak into the prompt.
    try:
        return urlparse(server_url).hostname or "unknown"
    except ValueError:
        return "unknown"


async def infer_integration_category(
    name: str,
    description: str,
    tools: list[dict[str, Any]],
    server_url: str,
) -> str:
    """Classify an integration into one ``INTEGRATION_CATEGORIES`` value.

    Falls back to ``"other"`` on any error or an unrecognized response.
    """
    log.set(integration={"provider": name, "action": "infer_category"})
    prompt = CATEGORY_INFERENCE_PROMPT.format(
        categories=", ".join(INTEGRATION_CATEGORIES),
        name=name,
        description=description or "No description provided",
        tools=_tools_summary(tools, MAX_TOOLS_FOR_CATEGORY),
        domain=_server_domain(server_url),
    )
    try:
        async with asyncio.timeout(_CATEGORY_INFERENCE_TIMEOUT_SECONDS):
            response = await ainvoke_llm(
                get_default_llm(), [HumanMessage(content=prompt)], label="integration_category"
            )
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to infer category for integration '{name}': {e}",
            exc_info=True,
        )
        return _FALLBACK_CATEGORY

    # ``.text`` flattens the message's content blocks to a string; ``.content``
    # may be a list (Gemini), whose repr would never match a category.
    category = response.text.strip().lower()
    if category not in INTEGRATION_CATEGORIES:
        log.warning(
            f"{LogTag.INTEGRATION} LLM returned invalid category '{category}' for integration "
            f"'{name}', falling back to '{_FALLBACK_CATEGORY}'"
        )
        return _FALLBACK_CATEGORY

    log.info(f"{LogTag.INTEGRATION} Inferred category '{category}' for integration '{name}'")
    return category


async def infer_integration_content(
    name: str,
    description: str,
    tools: list[dict[str, Any]],
    server_url: str,
    category: str,
) -> IntegrationContent | None:
    """Generate rich marketplace content for an integration, or ``None``.

    Best-effort: returns ``None`` on any failure, timeout, or when the result
    does not satisfy the ``USE_CASES_COUNT`` / ``HOW_IT_WORKS_COUNT`` /
    ``FAQ_COUNT`` contract, so the caller stays unblocked and the frontend falls
    back to its generic copy. Content is a nice-to-have, never a publish gate.
    """
    log.set(integration={"provider": name, "action": "infer_content"})
    prompt = CONTENT_INFERENCE_PROMPT.format(
        name=name,
        category=category,
        description=description or "No description provided",
        tools=_tools_summary(tools, MAX_TOOLS_FOR_CONTENT),
        domain=_server_domain(server_url),
        use_cases_count=USE_CASES_COUNT,
        how_it_works_count=HOW_IT_WORKS_COUNT,
        faq_count=FAQ_COUNT,
    )
    # One overall timeout budget around the default model's structured-output call
    # (transient-error retry is built into ainvoke_llm). Content is a nice-to-have:
    # any failure or an incomplete result returns None so publishing is never blocked.
    try:
        async with asyncio.timeout(_CONTENT_GENERATION_TIMEOUT_SECONDS):
            structured_llm = get_default_llm().with_structured_output(IntegrationContent)
            result = await ainvoke_llm(
                structured_llm, [HumanMessage(content=prompt)], label="integration_content"
            )
            content = IntegrationContent.model_validate(result)
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Content generation errored for integration '{name}': {e}",
            exc_info=True,
        )
        return None

    if _is_complete(content):
        log.info(f"{LogTag.INTEGRATION} Generated marketplace content for integration '{name}'")
        return content
    log.warning(f"{LogTag.INTEGRATION} Incomplete content for integration '{name}'")
    return None


def _is_complete(content: IntegrationContent) -> bool:
    """Whether content satisfies the required 5/3/4 cardinality contract."""
    return (
        len(content.use_cases) == USE_CASES_COUNT
        and len(content.how_it_works) == HOW_IT_WORKS_COUNT
        and len(content.faqs) == FAQ_COUNT
    )
