from langchain_core.prompts import PromptTemplate
from app.agents.prompts.calendar_prompts import CALENDAR_PROMPT, CALENDAR_LIST_PROMPT

CALENDAR_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=[],
    template=CALENDAR_PROMPT,
)

CALENDAR_LIST_TEMPLATE = PromptTemplate(
    input_variables=["calendars"],
    template=CALENDAR_LIST_PROMPT,
)
