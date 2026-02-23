from app.agents.prompts.comms_prompts import COMMS_AGENT_PROMPT, EXECUTOR_AGENT_PROMPT
from langchain_core.prompts import PromptTemplate

COMMS_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=COMMS_AGENT_PROMPT,
)

EXECUTOR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=EXECUTOR_AGENT_PROMPT,
)
