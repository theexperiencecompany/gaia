from langchain_core.prompts import PromptTemplate

from app.agents.prompts.agent_prompts import AGENT_SYSTEM_PROMPT

AGENT_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["user_name"],
    template=AGENT_SYSTEM_PROMPT,
)
