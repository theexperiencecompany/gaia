from langchain_core.prompts import PromptTemplate
from app.agents.prompts.fetch_prompts import FETCH_PROMPT

FETCH_TEMPLATE = PromptTemplate(
    input_variables=["urls", "page_content"],
    template=FETCH_PROMPT,
)
