"""
Gmail Subgraph implemented using the standardized Plan-and-Execute framework.

Flow:
1. Main agent hands off to Gmail subagent
2. Gmail subagent creates structured execution plan with specialized operation nodes
3. Execute steps based on dependencies, passing context between steps
4. Return final output to main agent

Uses the FlexiblePlanExecuteGraph for standardized planning and execution.
"""

from enum import Enum
from typing import Any, Dict

from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import FlexiblePlanExecuteGraph
from app.langchain.prompts.gmail_node_prompts import (
    ATTACHMENT_HANDLING_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    GMAIL_PLANNER_PROMPT,
)
from langchain_core.messages import HumanMessage, SystemMessage


class GmailNodeEnum(str, Enum):
    """Available Gmail operation nodes."""
    
    EMAIL_COMPOSITION = "email_composition"
    EMAIL_RETRIEVAL = "email_retrieval" 
    EMAIL_MANAGEMENT = "email_management"
    COMMUNICATION = "communication"
    CONTACT_MANAGEMENT = "contact_management"
    ATTACHMENT_HANDLING = "attachment_handling"
    FREE_LLM = "free_llm"  # For brainstorming, structuring, general tasks


# Available nodes description for planner
AVAILABLE_NODES_DESCRIPTION = """
Available Gmail Operation Nodes:

• email_composition - Create, draft, send emails and manage drafts
• email_retrieval - Search, fetch, list emails and conversation threads  
• email_management - Organize, label, delete, archive emails
• communication - Reply to threads, forward messages, manage conversations
• contact_management - Search people, contacts, profiles in Gmail
• attachment_handling - Download and process email attachments
• free_llm - General reasoning, brainstorming, structuring tasks
"""


class GmailPlanExecuteGraph(FlexiblePlanExecuteGraph):
    """Gmail plan-and-execute framework implementation."""

    def __init__(self):
        """Initialize the Gmail plan-and-execute framework."""
        super().__init__(provider_name="Gmail")

    def _initialize_operation_nodes(self):
        """Initialize Gmail operation nodes."""
        logger.info("Initializing Gmail operation nodes")

        # Register all specialized Gmail operation nodes
        self.register_operation_node(
            name=GmailNodeEnum.EMAIL_COMPOSITION.value,
            func=self._email_composition_node,
            description="Create, draft, send emails and manage drafts",
        )

        self.register_operation_node(
            name=GmailNodeEnum.EMAIL_RETRIEVAL.value,
            func=self._email_retrieval_node,
            description="Search, fetch, list emails and conversation threads",
        )

        self.register_operation_node(
            name=GmailNodeEnum.EMAIL_MANAGEMENT.value,
            func=self._email_management_node,
            description="Organize, label, delete, archive emails",
        )

        self.register_operation_node(
            name=GmailNodeEnum.COMMUNICATION.value,
            func=self._communication_node,
            description="Reply to threads, forward messages, manage conversations",
        )

        self.register_operation_node(
            name=GmailNodeEnum.CONTACT_MANAGEMENT.value,
            func=self._contact_management_node,
            description="Search people, contacts, profiles in Gmail",
        )

        self.register_operation_node(
            name=GmailNodeEnum.ATTACHMENT_HANDLING.value,
            func=self._attachment_handling_node,
            description="Download and process email attachments",
        )

        self.register_operation_node(
            name=GmailNodeEnum.FREE_LLM.value,
            func=self._free_llm_node,
            description="General reasoning, brainstorming, structuring tasks",
        )

    def get_planner_prompt(self) -> str:
        """Get the Gmail planner system prompt."""
        return GMAIL_PLANNER_PROMPT + "\n\n" + AVAILABLE_NODES_DESCRIPTION

    async def _email_composition_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for email composition operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for email composition
            messages = [
                SystemMessage(content=EMAIL_COMPOSITION_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this email composition task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Email composition node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in email composition node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _email_retrieval_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for email retrieval operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for email retrieval
            messages = [
                SystemMessage(content=EMAIL_RETRIEVAL_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this email retrieval task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Email retrieval node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in email retrieval node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _email_management_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for email management operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for email management
            messages = [
                SystemMessage(content=EMAIL_MANAGEMENT_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this email management task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Email management node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in email management node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _communication_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for communication operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for communication
            messages = [
                SystemMessage(content=COMMUNICATION_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this communication task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Communication node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in communication node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _contact_management_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for contact management operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for contact management
            messages = [
                SystemMessage(content=CONTACT_MANAGEMENT_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this contact management task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Contact management node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in contact management node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _attachment_handling_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for attachment handling operations."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use specialized prompt for attachment handling
            messages = [
                SystemMessage(content=ATTACHMENT_HANDLING_PROMPT),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this attachment handling task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Attachment handling node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in attachment handling node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}

    async def _free_llm_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Node for general reasoning tasks."""
        try:
            # Extract current execution context
            context = state.get("_execution_context", {})
            instruction = context.get("instructions", "")

            # Use general prompt for free LLM tasks
            free_llm_prompt = """You are a helpful Gmail assistant. Execute the given instruction using your knowledge and reasoning abilities. Be thorough and provide clear, actionable responses."""

            messages = [
                SystemMessage(content=free_llm_prompt),
                HumanMessage(
                    content=f"Instruction: {instruction}\n\nExecute this task thoroughly."
                ),
            ]

            # Execute using LLM
            response = await self.llm.ainvoke(messages)

            # Extract result
            if isinstance(response, str):
                result = response
            elif hasattr(response, "content"):
                result = response.content
            else:
                result = str(response)

            logger.info("Free LLM node executed successfully")
            return {"output": result, "success": True}

        except Exception as e:
            logger.error(f"Error in free LLM node: {e}")
            return {"output": str(e), "success": False, "error": str(e)}


def create_gmail_subgraph():
    """Factory function to create and compile the Gmail subgraph."""
    logger.info("Creating Gmail subgraph using plan-and-execute framework")

    # Create the Gmail plan-and-execute graph
    gmail_graph = GmailPlanExecuteGraph()

    logger.info("Gmail subgraph created successfully")
    return gmail_graph