"""Generate marketplace category and detail-page copy for custom integrations.

Native integrations ship both curated by hand in app/config/oauth_content.py;
custom integrations get them generated here at publish time instead of the
frontend's generic fallbacks. Both run on the default model via
resolve_model + ainvoke_llm — the same path used for memory extraction,
follow-ups, and research helpers.
"""

import asyncio
from typing import cast
from urllib.parse import urlparse

from langchain_core.messages import BaseMessage, HumanMessage

from app.agents.llm.client import ainvoke_llm, ainvoke_structured, metered_config, resolve_model
from app.constants.integrations import (
    CATEGORY_INFERENCE_PROMPT,
    CONTENT_INFERENCE_PROMPT,
    DEFAULT_INTEGRATION_CATEGORY,
    FAQ_COUNT,
    HOW_IT_WORKS_COUNT,
    INTEGRATION_CATEGORIES,
    MAX_TOOLS_IN_PROMPT,
    TOOL_DESCRIPTION_MAX_CHARS,
    USE_CASES_COUNT,
)
from app.constants.log_tags import LogTag
from app.models.db_oauth import MCPAuthType
from app.models.integration_models import AuthType, Integration, StoredIntegrationTool
from app.models.oauth_models import IntegrationContent
from app.services.integrations.integration_content_fallback import first_sentence, named_tools
from shared.py.wide_events import log

# Best-effort caps so a slow upstream LLM never stalls the inline publish flow.
_CONTENT_GENERATION_TIMEOUT_SECONDS = 20
_CATEGORY_INFERENCE_TIMEOUT_SECONDS = 10


_AUTH_DESCRIPTIONS: dict[MCPAuthType, str] = {
    MCPAuthType.OAUTH: "they sign in and approve access on an OAuth consent screen",
    MCPAuthType.BEARER: "they paste an API token from their account",
    MCPAuthType.NONE: "no credentials, it works as soon as it is added",
}


def _tools_catalog(tools: list[StoredIntegrationTool]) -> str:
    """One "- name: first sentence of its description" line per named tool, or "None"."""
    lines = []
    for tool in named_tools(tools)[:MAX_TOOLS_IN_PROMPT]:
        summary = first_sentence(tool.description, max_len=TOOL_DESCRIPTION_MAX_CHARS)
        lines.append(f"- {tool.name}: {summary}" if summary else f"- {tool.name}")
    return "\n".join(lines) or "None"


def _auth_description(auth_type: AuthType | None) -> str:
    return _AUTH_DESCRIPTIONS[MCPAuthType(auth_type)] if auth_type else "not specified"


def _server_domain(server_url: str) -> str:
    # .hostname (not .netloc) so any embedded credentials/port never leak into the prompt.
    try:
        return urlparse(server_url).hostname or "unknown"
    except ValueError:
        return "unknown"


async def infer_integration_category(
    name: str,
    description: str,
    tools: list[StoredIntegrationTool],
    server_url: str,
    user_id: str,
) -> str:
    """Classify an integration into one INTEGRATION_CATEGORIES value.

    Falls back to "other" on any error or an unrecognized response.
    """
    log.set(integration={"provider": name, "action": "infer_category"})
    prompt = CATEGORY_INFERENCE_PROMPT.format(
        categories=", ".join(INTEGRATION_CATEGORIES),
        name=name,
        description=description or "No description provided",
        tools=_tools_catalog(tools),
        domain=_server_domain(server_url),
    )
    try:
        async with asyncio.timeout(_CATEGORY_INFERENCE_TIMEOUT_SECONDS):
            response = await ainvoke_llm(
                resolve_model(),
                [HumanMessage(content=prompt)],
                label="integration_category",
                config=metered_config(user_id),
            )
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to infer category for integration",
            name=name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return DEFAULT_INTEGRATION_CATEGORY

    # ``.text`` flattens the message's content blocks to a string; ``.content``
    # may be a list (Gemini), whose repr would never match a category.
    category = cast(BaseMessage, response).text.strip().lower()
    if category not in INTEGRATION_CATEGORIES:
        log.warning(
            f"{LogTag.INTEGRATION} LLM returned an invalid category for integration, falling back",
            category=category,
            name=name,
            _fallback_category=DEFAULT_INTEGRATION_CATEGORY,
        )
        return DEFAULT_INTEGRATION_CATEGORY

    log.info(
        f"{LogTag.INTEGRATION} Inferred category for integration", category=category, name=name
    )
    return category


async def infer_integration_content(
    integration: Integration,
    category: str,
    auth_type: AuthType | None,
    user_id: str,
) -> IntegrationContent | None:
    """Generate rich marketplace content for an integration, or None.

    Best-effort: returns None on any failure, timeout, or when the result
    does not satisfy the USE_CASES_COUNT / HOW_IT_WORKS_COUNT /
    FAQ_COUNT contract, so the caller stays unblocked and the frontend falls
    back to its generic copy. Content is a nice-to-have, never a publish gate.
    """
    name = integration.name
    tools = integration.tools
    server_url = integration.mcp_config.server_url if integration.mcp_config else ""
    log.set(integration={"provider": name, "action": "infer_content"})
    tool_count = len(named_tools(tools))
    prompt = CONTENT_INFERENCE_PROMPT.format(
        name=name,
        category=category,
        description=integration.description or "No description provided",
        auth=_auth_description(auth_type),
        tool_count=tool_count,
        tools_note=f", first {MAX_TOOLS_IN_PROMPT} listed"
        if tool_count > MAX_TOOLS_IN_PROMPT
        else "",
        tools=_tools_catalog(tools),
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
            content = await ainvoke_structured(
                IntegrationContent,
                prompt,
                label="integration_content",
                config=metered_config(user_id),
            )
    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Content generation errored for integration",
            name=name,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        return None

    if _is_complete(content):
        log.info(f"{LogTag.INTEGRATION} Generated marketplace content for integration", name=name)
        return content
    log.warning(f"{LogTag.INTEGRATION} Incomplete content for integration", name=name)
    return None


def _is_complete(content: IntegrationContent) -> bool:
    """Whether content satisfies the required 5/3/4 cardinality contract."""
    return (
        len(content.use_cases) == USE_CASES_COUNT
        and len(content.how_it_works) == HOW_IT_WORKS_COUNT
        and len(content.faqs) == FAQ_COUNT
    )
