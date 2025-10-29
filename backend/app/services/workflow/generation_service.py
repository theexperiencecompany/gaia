"""Workflow generation service for LLM-based step creation."""

from typing import List

from app.agents.llm.client import init_llm
from app.agents.prompts.trigger_prompts import generate_trigger_context
from app.agents.templates.workflow_template import WORKFLOW_GENERATION_TEMPLATE
from app.config.loggers import general_logger as logger
from app.models.workflow_models import WorkflowStep
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field


class WorkflowPlan(BaseModel):
    """Schema for complete workflow plan."""

    steps: List[WorkflowStep] = Field(description="List of workflow steps")


class WorkflowGenerationService:
    """Service for generating workflow steps using LLM."""

    @staticmethod
    async def generate_steps_with_llm(
        description: str, title: str, trigger_config=None
    ) -> list:
        """Generate workflow steps using LLM with structured output."""
        try:
            # Create the parser
            parser = PydanticOutputParser(pydantic_object=WorkflowPlan)

            # Import here to avoid circular dependency at module level
            from app.agents.tools.core.registry import get_tool_registry

            tool_registry = await get_tool_registry()

            # Create structured tool information with categories
            tools_with_categories = []
            category_names = []
            categories = tool_registry.get_all_category_objects()
            for category in categories.keys():
                category_names.append(category)
                category_tools = categories[category].get_tool_objects()
                tool_names = [
                    tool.name if hasattr(tool, "name") else str(tool)
                    for tool in category_tools
                ]
                tools_with_categories.append(f"{category}: {', '.join(tool_names)}")

            for tool in tool_registry.get_core_tools():
                tool_name = tool.name if hasattr(tool, "name") else str(tool)
                tools_with_categories.append(f"Always Available: {tool_name}")

            trigger_context = generate_trigger_context(trigger_config)

            # Initialize LLM
            llm = init_llm()

            # Format the prompt using the template
            formatted_prompt = WORKFLOW_GENERATION_TEMPLATE.format(
                description=description,
                title=title,
                trigger_context=trigger_context,
                tools="\n".join(tools_with_categories),
                categories=", ".join(category_names),
                format_instructions=parser.get_format_instructions(),
            )

            # Generate workflow plan using LLM directly
            llm_response = await llm.ainvoke(formatted_prompt)

            # Parse the response content - handle different response types
            response_content = getattr(llm_response, "content", str(llm_response))
            result = parser.parse(response_content)

            # Convert to list of dictionaries for storage
            steps_data = []
            for i, step in enumerate(result.steps, 1):
                steps_data.append(step.model_dump(mode="json"))

            logger.info(f"Generated {len(steps_data)} workflow steps for: {title}")
            return steps_data

        except Exception as e:
            logger.error(f"Error in LLM workflow generation: {str(e)}")
            return []
