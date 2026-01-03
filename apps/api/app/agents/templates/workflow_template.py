"""Workflow generation template and parser."""

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from app.agents.prompts.workflow_prompts import WORKFLOW_GENERATION_SYSTEM_PROMPT
from app.models.workflow_models import GeneratedWorkflow


# Create parser using models from workflow_models
workflow_parser = PydanticOutputParser(pydantic_object=GeneratedWorkflow)

# Create template with partial_variables (like filter_service.py does)
WORKFLOW_GENERATION_TEMPLATE = PromptTemplate(
    input_variables=[
        "description",
        "title",
        "trigger_context",
        "tools",
        "categories",
    ],
    template=WORKFLOW_GENERATION_SYSTEM_PROMPT,
    partial_variables={
        "format_instructions": workflow_parser.get_format_instructions()
    },
)
