from langchain_core.prompts import PromptTemplate
from app.agents.prompts.weather_prompts import WEATHER_PROMPT

WEATHER_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["weather_data"],
    template=WEATHER_PROMPT,
)
