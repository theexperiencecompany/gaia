"""
Content Inference Service for MCP Integrations.

Generates the rich marketplace content (use cases, how-it-works steps, FAQs)
shown on an integration's public detail page. Native integrations ship this
content curated by hand in ``app/config/oauth_content.py``; custom integrations
get it generated here at publish time — the same way ``category`` is inferred in
``category_inference_service`` — so they show tailored copy instead of the
frontend's generic fallbacks.
"""

import json
from urllib.parse import urlparse

from openai import AsyncOpenAI

from app.constants.log_tags import LogTag
from app.models.oauth_models import IntegrationContent
from shared.py.wide_events import log

# How many of each content element to request from the model. The frontend
# needs at least 3 FAQs for its rich-snippet schema, so never go below that.
USE_CASES_COUNT = 5
HOW_IT_WORKS_COUNT = 3
FAQ_COUNT = 4

CONTENT_INFERENCE_PROMPT = """
You are writing marketplace copy for GAIA, a proactive personal AI assistant. \
GAIA connects to third-party tools via MCP and exposes every action as a \
plain-English command — the user tells GAIA what they want and GAIA does it, \
including proactively in the background.

Write rich detail-page content for the following integration.

Integration Name: {name}
Category: {category}
Description: {description}
Available Tools: {tools}
Server URL Domain: {domain}

Voice and quality bar:
- Concrete and specific to THIS integration and its actual tools — never generic
  filler that would fit any product.
- Benefit-led, in GAIA's voice ("GAIA does X for you"), plain-English examples.
- No marketing fluff, no emojis, no first person, no trailing punctuation noise.

Respond with ONLY a JSON object in exactly this shape:
{{
  "use_cases": [{use_cases_count} short strings, each a distinct capability],
  "how_it_works": [{how_it_works_count} objects {{"title": short, "body": 1-2 sentences}} \
covering connect -> instruct in plain English -> GAIA automates it],
  "faqs": [{faq_count} objects {{"question": natural user question, "answer": 1-3 sentences}}]
}}
"""


async def infer_integration_content(
    name: str,
    description: str,
    tools: list[dict],
    server_url: str,
    category: str,
) -> IntegrationContent | None:
    """Generate rich marketplace content for an integration via LLM.

    Mirrors :func:`infer_integration_category`: cost-efficient ``gpt-4o-mini``,
    JSON output validated against :class:`IntegrationContent`. Returns ``None`` on
    any failure or empty result so the caller stays unblocked and the frontend
    falls back to its generic content — content is a nice-to-have, never a gate.
    """
    log.set(integration={"provider": name, "action": "infer_content"})
    try:
        client = AsyncOpenAI()

        tool_names: list[str] = [str(t.get("name")) for t in tools[:15] if t.get("name")]
        tools_str = ", ".join(tool_names) or "None"

        try:
            domain = urlparse(server_url).netloc or "unknown"
        except Exception:
            domain = "unknown"

        prompt_content = CONTENT_INFERENCE_PROMPT.format(
            name=name,
            category=category,
            description=description or "No description provided",
            tools=tools_str,
            domain=domain,
            use_cases_count=USE_CASES_COUNT,
            how_it_works_count=HOW_IT_WORKS_COUNT,
            faq_count=FAQ_COUNT,
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_content}],
            response_format={"type": "json_object"},
            temperature=0.4,
        )

        raw = response.choices[0].message.content
        if not raw:
            log.warning(f"{LogTag.INTEGRATION} LLM returned empty content for integration '{name}'")
            return None

        content = IntegrationContent.model_validate(json.loads(raw))
        if not content.use_cases and not content.how_it_works and not content.faqs:
            log.warning(
                f"{LogTag.INTEGRATION} LLM returned no usable content for integration '{name}'"
            )
            return None

        log.info(f"{LogTag.INTEGRATION} Generated marketplace content for integration '{name}'")
        return content

    except Exception as e:
        log.error(
            f"{LogTag.INTEGRATION} Failed to generate content for integration '{name}': {e}",
            exc_info=True,
        )
        return None
