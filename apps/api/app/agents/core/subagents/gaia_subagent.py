"""
GAIA Self-Knowledge Subagent

A predefined subagent with deep knowledge about GAIA's own capabilities,
integrations, and features. Invoked when users ask questions like:

  - "What can you do?"
  - "What integrations do you support?"
  - "How does GAIA work?"
  - "Tell me about GAIA"

The subagent fetches live documentation from:
  - https://docs.heygaia.io/llms.txt
  - https://heygaia.io/llms.txt

and answers using up-to-date, accurate information about the product.
"""

from app.agents.llm.client import init_llm
from app.agents.tools.webpage_tool import fetch_webpages
from app.core.lazy_loader import providers
from shared.py.wide_events import log

from .base_subagent import SubAgentFactory


GAIA_AGENT_NAME = "gaia_agent"
GAIA_TOOL_SPACE = "gaia"

# Tools the GAIA agent binds at startup — it only needs fetch_webpages
# to load live documentation from docs.heygaia.io and heygaia.io
GAIA_AUTO_BIND_TOOLS = [fetch_webpages.name]


async def create_gaia_subagent():
    """
    Create the GAIA self-knowledge subagent graph.

    The subagent uses fetch_webpages to load live documentation from
    docs.heygaia.io/llms.txt and heygaia.io/llms.txt, then answers
    user questions about GAIA's capabilities and integrations.

    Returns:
        Compiled LangGraph subagent graph
    """
    llm = init_llm()

    log.set(subagent={"name": GAIA_AGENT_NAME, "provider": "gaia"})
    log.info("Creating GAIA self-knowledge subagent")

    graph = await SubAgentFactory.create_provider_subagent(
        provider="gaia",
        llm=llm,
        tool_space=GAIA_TOOL_SPACE,
        name=GAIA_AGENT_NAME,
        use_direct_tools=True,
        disable_retrieve_tools=True,
        auto_bind_tools=GAIA_AUTO_BIND_TOOLS,
    )

    log.info("GAIA self-knowledge subagent created successfully")
    return graph


def register_gaia_subagent() -> None:
    """
    Register the GAIA self-knowledge subagent as a lazy provider.

    Called during application startup via register_subagent_providers().
    The subagent graph is created on first access.
    """
    providers.register(
        name=GAIA_AGENT_NAME,
        loader_func=create_gaia_subagent,
        required_keys=[],
    )
    log.info(f"Registered GAIA self-knowledge subagent provider: {GAIA_AGENT_NAME}")
