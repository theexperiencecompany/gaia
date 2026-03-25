from app.agents.prompts.comms_prompts import (
    EXECUTOR_AGENT_PROMPT,
    get_comms_agent_prompt,
)
from langchain_core.prompts import PromptTemplate

COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=get_comms_agent_prompt(),
)

EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
