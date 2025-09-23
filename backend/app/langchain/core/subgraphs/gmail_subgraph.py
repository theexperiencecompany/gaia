"""
Clean Gmail Subgraph with Simple Plan-and-Execute Flow.

Flow:
1. Main agent hands off to Gmail subagent 
2. Gmail subagent creates structured plan with node_name (enum) + free_llm node
3. Execute steps sequentially, passing last AI message between steps
4. Return final output to main agent

No complex routing logic - just simple sequential execution.
"""

from enum import Enum
from typing import Dict, List
from typing_extensions import TypedDict

from app.config.loggers import langchain_logger as logger
from app.langchain.prompts.gmail_node_prompts import (
    GMAIL_PLANNER_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    ATTACHMENT_HANDLING_PROMPT,
)
from langchain_core.language_models import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field


class GmailNodeEnum(str, Enum):
    """Available Gmail operation nodes."""
    
    EMAIL_COMPOSITION = "email_composition"
    EMAIL_RETRIEVAL = "email_retrieval" 
    EMAIL_MANAGEMENT = "email_management"
    COMMUNICATION = "communication"
    CONTACT_MANAGEMENT = "contact_management"
    ATTACHMENT_HANDLING = "attachment_handling"
    FREE_LLM = "free_llm"  # For brainstorming, structuring, general tasks


class GmailPlanStep(BaseModel):
    """A single step in Gmail execution plan."""
    
    node_name: GmailNodeEnum = Field(description="Which node to execute")
    instruction: str = Field(description="Detailed instruction for this step")
    context: Dict = Field(default_factory=dict, description="Additional context")


class GmailPlan(BaseModel):
    """Gmail execution plan."""
    
    steps: List[GmailPlanStep] = Field(description="Sequential execution steps")


class GmailState(TypedDict):
    """Gmail subgraph state."""
    
    input: str  # Original user request
    plan: List[GmailPlanStep]  # Execution plan
    current_step: int  # Current step index
    last_ai_message: str  # Last AI message (passed between steps)
    final_response: str  # Final response to return to main agent
    messages: List  # Message history


# Node prompts mapping
NODE_PROMPTS = {
    GmailNodeEnum.EMAIL_COMPOSITION: EMAIL_COMPOSITION_PROMPT,
    GmailNodeEnum.EMAIL_RETRIEVAL: EMAIL_RETRIEVAL_PROMPT,
    GmailNodeEnum.EMAIL_MANAGEMENT: EMAIL_MANAGEMENT_PROMPT,
    GmailNodeEnum.COMMUNICATION: COMMUNICATION_PROMPT,
    GmailNodeEnum.CONTACT_MANAGEMENT: CONTACT_MANAGEMENT_PROMPT,
    GmailNodeEnum.ATTACHMENT_HANDLING: ATTACHMENT_HANDLING_PROMPT,
    GmailNodeEnum.FREE_LLM: """You are a helpful Gmail assistant. Execute the given instruction using your knowledge and reasoning abilities. Be thorough and provide clear, actionable responses."""
}

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


class GmailPlanAndExecute:
    """Simple Gmail plan-and-execute subgraph."""
    
    def __init__(self, llm: LanguageModelLike):
        self.llm = llm
    
    async def planner_node(self, state: GmailState) -> Dict:
        """Create structured execution plan."""
        try:
            logger.info(f"Gmail Planner: Creating plan for: {state['input']}")
            
            planner_prompt = GMAIL_PLANNER_PROMPT + "\\n\\n" + AVAILABLE_NODES_DESCRIPTION
            
            messages = [
                SystemMessage(content=planner_prompt),
                HumanMessage(content=f"""Create a structured plan for: {state['input']}

Return a JSON plan with this exact structure:
{{
    "steps": [
        {{
            "node_name": "email_retrieval",
            "instruction": "Search for emails from John about project meeting",
            "context": {{"search_query": "from:john project meeting"}}
        }},
        {{
            "node_name": "communication", 
            "instruction": "Reply to the found email with project update",
            "context": {{"reply_type": "project_update"}}
        }}
    ]
}}

Available node_names: {[e.value for e in GmailNodeEnum]}
""")
            ]
            
            response = await self.llm.ainvoke(messages)
            
            # Extract content safely
            if isinstance(response, str):
                content = response
            elif hasattr(response, 'content'):
                content = response.content
            else:
                content = str(response)
            
            # Parse plan from response
            content_str = str(content) if not isinstance(content, str) else content
            plan_steps = self._parse_plan(content_str, state['input'])
            
            logger.info(f"Gmail Planner: Created {len(plan_steps)} steps")
            return {
                "plan": plan_steps,
                "current_step": 0
            }
            
        except Exception as e:
            logger.error(f"Gmail Planner error: {e}")
            # Fallback plan
            fallback_step = GmailPlanStep(
                node_name=GmailNodeEnum.FREE_LLM,
                instruction=f"Handle Gmail request: {state['input']}",
                context={"fallback": True}
            )
            return {
                "plan": [fallback_step],
                "current_step": 0
            }
    
    async def executor_node(self, state: GmailState) -> Dict:
        """Execute current step in plan."""
        try:
            plan = state.get('plan', [])
            current_step_idx = state.get('current_step', 0)
            
            if current_step_idx >= len(plan):
                # All steps completed
                final_response = state.get('last_ai_message', 'Gmail operations completed successfully.')
                return {"final_response": final_response}
            
            current_step = plan[current_step_idx]
            node_name = current_step.node_name
            
            logger.info(f"Gmail Executor: Executing step {current_step_idx + 1}/{len(plan)} - {node_name}")
            
            # Get node prompt
            node_prompt = NODE_PROMPTS.get(node_name, NODE_PROMPTS[GmailNodeEnum.FREE_LLM])
            
            # Build execution message
            execution_message = f"""**Instruction:** {current_step.instruction}

**Context:** {current_step.context if current_step.context else 'None'}

**Previous Step Output:** {state.get('last_ai_message', 'This is the first step')}

Execute this instruction thoroughly and provide a clear result."""
            
            messages = [
                SystemMessage(content=node_prompt),
                HumanMessage(content=execution_message)
            ]
            
            # Execute step
            response = await self.llm.ainvoke(messages)
            
            # Extract AI message safely
            if isinstance(response, str):
                ai_message = response
            elif hasattr(response, 'content'):
                ai_message = response.content
            else:
                ai_message = str(response)
            
            logger.info(f"Gmail Executor: Step {current_step_idx + 1} completed")
            
            return {
                "current_step": current_step_idx + 1,
                "last_ai_message": ai_message,
                "messages": [response] if hasattr(response, 'content') else [AIMessage(content=ai_message)]
            }
            
        except Exception as e:
            logger.error(f"Gmail Executor error: {e}")
            return {
                "final_response": f"Error executing Gmail operation: {str(e)}"
            }
    
    def should_continue(self, state: GmailState) -> str:
        """Determine next action - continue execution or end."""
        if "final_response" in state and state["final_response"]:
            return END
        
        plan = state.get('plan', [])
        current_step = state.get('current_step', 0)
        
        if current_step < len(plan):
            return "executor"
        else:
            # All steps completed, generate final response
            return "executor"  # Will handle completion in executor
    
    def _parse_plan(self, content: str, user_input: str) -> List[GmailPlanStep]:
        """Parse plan steps from LLM response."""
        import json
        import re
        
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\\{.*\\}', content, re.DOTALL)
            if json_match:
                plan_data = json.loads(json_match.group())
                steps = []
                for step_data in plan_data.get('steps', []):
                    if step_data.get('node_name') in [e.value for e in GmailNodeEnum]:
                        steps.append(GmailPlanStep(
                            node_name=GmailNodeEnum(step_data['node_name']),
                            instruction=step_data.get('instruction', ''),
                            context=step_data.get('context', {})
                        ))
                if steps:
                    return steps
        except Exception as e:
            logger.warning(f"Failed to parse structured plan: {e}")
        
        # Fallback: create simple plan based on user input
        return self._create_simple_plan(user_input)
    
    def _create_simple_plan(self, user_input: str) -> List[GmailPlanStep]:
        """Create simple fallback plan based on input analysis."""
        input_lower = user_input.lower()
        
        if any(word in input_lower for word in ['draft', 'compose', 'create', 'write']):
            return [GmailPlanStep(
                node_name=GmailNodeEnum.EMAIL_COMPOSITION,
                instruction=f"Create email based on request: {user_input}",
                context={}
            )]
        elif any(word in input_lower for word in ['reply', 'respond', 'answer']):
            return [
                GmailPlanStep(
                    node_name=GmailNodeEnum.EMAIL_RETRIEVAL,
                    instruction=f"Find relevant email thread for: {user_input}",
                    context={}
                ),
                GmailPlanStep(
                    node_name=GmailNodeEnum.COMMUNICATION,
                    instruction=f"Reply to the email thread: {user_input}",
                    context={}
                )
            ]
        elif any(word in input_lower for word in ['search', 'find', 'fetch', 'show']):
            return [GmailPlanStep(
                node_name=GmailNodeEnum.EMAIL_RETRIEVAL,
                instruction=f"Search and retrieve emails: {user_input}",
                context={}
            )]
        else:
            return [GmailPlanStep(
                node_name=GmailNodeEnum.FREE_LLM,
                instruction=f"Handle Gmail request: {user_input}",
                context={}
            )]
    
    def create_graph(self) -> StateGraph:
        """Create the Gmail subgraph."""
        logger.info("Creating Gmail subgraph")
        
        workflow = StateGraph(GmailState)
        
        # Add nodes
        workflow.add_node("planner", self.planner_node)
        workflow.add_node("executor", self.executor_node)
        
        # Define flow
        workflow.add_edge(START, "planner")
        workflow.add_edge("planner", "executor")
        workflow.add_conditional_edges(
            "executor",
            self.should_continue,
            {"executor": "executor", END: END}
        )
        
        return workflow
    
    def compile(self):
        """Compile the Gmail subgraph."""
        from app.langchain.tools.core.store import get_tools_store
        
        workflow = self.create_graph()
        store = get_tools_store()
        
        compiled = workflow.compile(
            store=store,
            name="gmail_subgraph",
            checkpointer=False
        )
        
        logger.info("Gmail subgraph compiled successfully")
        return compiled