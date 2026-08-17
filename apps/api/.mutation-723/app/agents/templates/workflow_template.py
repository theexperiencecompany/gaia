"""Workflow generation template."""

from langchain_core.prompts import PromptTemplate

from app.agents.prompts.workflow_prompts import WORKFLOW_GENERATION_SYSTEM_PROMPT

# Create template without format_instructions — structured output is handled
# natively via llm.with_structured_output(GeneratedWorkflow) in generation_service.
WORKFLOW_GENERATION_TEMPLATE = PromptTemplate(
    input_variables=[
        "description",
        "title",
        "trigger_context",
        "tools",
        "categories",
    ],
    template=WORKFLOW_GENERATION_SYSTEM_PROMPT,
)
