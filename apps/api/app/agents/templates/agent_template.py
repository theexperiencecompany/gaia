from app.agents.prompts.comms_prompts import (
    EXECUTOR_AGENT_PROMPT,
    get_comms_agent_prompt,
)
from app.config.settings import get_settings
from langchain_core.prompts import PromptTemplate

_settings = get_settings()

COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=get_comms_agent_prompt(enable_openui=_settings.ENABLE_OPENUI),
)

EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
