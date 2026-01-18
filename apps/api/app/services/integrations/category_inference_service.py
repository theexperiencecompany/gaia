"""
Category Inference Service for MCP Integrations.

This service uses an LLM to automatically categorize integrations
based on their name, description, tools, and server URL domain.
"""

from urllib.parse import urlparse

from openai import AsyncOpenAI

from app.config.loggers import app_logger as logger

# Fixed list of valid integration categories
INTEGRATION_CATEGORIES = [
    "productivity",  # Notion, Todoist, project management
    "communication",  # Slack, Discord, email
    "developer",  # GitHub, GitLab, CI/CD
    "analytics",  # Data tools, dashboards
    "finance",  # Payments, accounting
    "marketing",  # Social media, SEO, ads
    "storage",  # Cloud storage, databases
    "ai-ml",  # AI services, ML tools
    "automation",  # Zapier-like, webhooks
    "other",  # Fallback
]

CATEGORY_INFERENCE_PROMPT = """
Given the following MCP integration details, classify it into ONE of these categories:
{categories}

Integration Name: {name}
Description: {description}
Available Tools: {tools}
Server URL Domain: {domain}

Respond with ONLY the category name, nothing else.
"""


async def infer_integration_category(
    name: str,
    description: str,
    tools: list[dict],
    server_url: str,
) -> str:
    """
    Infer the category of an MCP integration using LLM classification.

    Uses GPT-4o-mini for cost-efficient category inference based on
    the integration's name, description, available tools, and server domain.

    Args:
        name: The integration name
        description: The integration description
        tools: List of tool dictionaries with at least a "name" key
        server_url: The MCP server URL

    Returns:
        One of the INTEGRATION_CATEGORIES strings. Falls back to "other"
        on any error or if the LLM returns an invalid category.
    """
    try:
        client = AsyncOpenAI()

        # Extract first 10 tool names for context
        tools_str = ", ".join([t.get("name", "") for t in tools[:10]]) or "None"

        # Extract domain from server URL
        try:
            domain = urlparse(server_url).netloc or "unknown"
        except Exception:
            domain = "unknown"

        prompt_content = CATEGORY_INFERENCE_PROMPT.format(
            categories=", ".join(INTEGRATION_CATEGORIES),
            name=name,
            description=description or "No description provided",
            tools=tools_str,
            domain=domain,
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_content}],
            max_tokens=20,
            temperature=0,
        )

        content = response.choices[0].message.content
        if content is None:
            logger.warning(
                f"LLM returned empty content for integration '{name}', falling back to 'other'"
            )
            return "other"
        category = content.strip().lower()

        # Validate response is a known category
        if category not in INTEGRATION_CATEGORIES:
            logger.warning(
                f"LLM returned invalid category '{category}' for integration '{name}', "
                f"falling back to 'other'"
            )
            return "other"

        logger.info(f"Inferred category '{category}' for integration '{name}'")
        return category

    except Exception as e:
        logger.error(
            f"Failed to infer category for integration '{name}': {e}",
            exc_info=True,
        )
        return "other"
