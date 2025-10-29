from langchain_core.prompts import PromptTemplate
from app.agents.prompts.workflow_prompts import WORKFLOW_GENERATION_SYSTEM_PROMPT

WORKFLOW_GENERATION_TEMPLATE = PromptTemplate(
    input_variables=[
        "description",
        "title",
        "trigger_context",
        "tools",
        "categories",
        "format_instructions",
    ],
    template=WORKFLOW_GENERATION_SYSTEM_PROMPT,
)
