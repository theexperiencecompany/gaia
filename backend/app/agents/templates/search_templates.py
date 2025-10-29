from langchain_core.prompts import PromptTemplate
from app.agents.prompts.search_prompts import SEARCH_PROMPT, DEEP_RESEARCH_PROMPT

SEARCH_TEMPLATE = PromptTemplate(
    input_variables=["formatted_results"],
    template=SEARCH_PROMPT,
)


DEEP_RESEARCH_TEMPLATE = PromptTemplate(
    input_variables=["formatted_results"],
    template=DEEP_RESEARCH_PROMPT,
)
