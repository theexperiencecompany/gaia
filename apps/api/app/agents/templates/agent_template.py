from app.agents.prompts.comms_prompts import (
    EXECUTOR_AGENT_PROMPT,
    RICH_UI_SOURCES,
    get_comms_agent_prompt,
)
from langchain_core.prompts import PromptTemplate

# Two pre-built comms prompt variants, cached at module load.
#
# Rebuilding a PromptTemplate per request fragments the LLM provider's prompt
# cache (caching keys on exact prefix). By collapsing every possible ``source``
# down to one of two stable prompt strings — rich-UI (web/mobile/desktop) and
# plain (whatsapp/telegram/discord/slack/email) — we keep the cache hit rate
# high and avoid the cost of string-concatenating the large OpenUI spec on
# every message.
_RICH_COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=get_comms_agent_prompt(None),
)

_PLAIN_COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=get_comms_agent_prompt("whatsapp"),
)

# Backwards-compatible default (rich-UI variant) for callers that don't know
# about source gating yet.
COMMS_PROMPT_TEMPLATE = _RICH_COMMS_PROMPT_TEMPLATE


def build_comms_prompt_template(source: str | None = None) -> PromptTemplate:
    """Return the comms prompt template appropriate for ``source``.

    Web / mobile / desktop get the variant with OpenUI Lang instructions so
    the agent can emit rich interactive cards. Messaging platforms (whatsapp,
    telegram, discord, slack) and email get the variant without OpenUI —
    those channels can only render plain Markdown and would show ``:::openui``
    fences as literal text.
    """
    if source is None or source in RICH_UI_SOURCES:
        return _RICH_COMMS_PROMPT_TEMPLATE
    return _PLAIN_COMMS_PROMPT_TEMPLATE


EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
