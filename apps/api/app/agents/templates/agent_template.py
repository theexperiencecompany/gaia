from app.agents.prompts.agent_prompts import AGENT_SYSTEM_PROMPT
from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT, EXECUTOR_AGENT_PROMPT
from langchain_core.prompts import PromptTemplate

AGENT_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=AGENT_SYSTEM_PROMPT,
)

COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=COMMS_AGENT_PROMPT,
)

EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
