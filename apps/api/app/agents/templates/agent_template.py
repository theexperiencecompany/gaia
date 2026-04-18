from app.agents.prompts.comms_prompts import (
    EXECUTOR_AGENT_PROMPT,
    get_comms_agent_prompt,
)
from langchain_core.prompts import PromptTemplate

COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=get_comms_agent_prompt(),
)


def build_comms_prompt_template(source: str | None = None) -> PromptTemplate:
    """Return a comms prompt template with OpenUI instructions gated on source.

    Non-rich-UI sources (whatsapp, telegram, discord, slack, email) get the
    prompt WITHOUT OpenUI Lang so the agent doesn't emit ``:::openui`` fences
    that those platforms can't render.
    """
    return PromptTemplate(
        input_variables=["user_name"],
        template=get_comms_agent_prompt(source),
    )


EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
