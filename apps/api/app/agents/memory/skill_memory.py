"""
Skill Learning System - Simple approach using mem0 via memory_service.

Design:
1. Send full conversation to mem0 (truncate large tool outputs)
2. Use SKILL_EXTRACTION_PROMPT to extract reusable procedures
3. Search and inject as context - no parsing needed

Skills are ISOLATED per subagent (twitter, github, linear, etc.)
using the agent_id namespace in mem0.

Note: User-specific memories (IDs, contacts, preferences) are handled
separately by memory_learning_node using the user_id namespace.
"""

from typing import Dict, List, Optional

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agents.memory.client import memory_client_manager
from app.config.loggers import llm_logger as logger
from app.services.memory_service import memory_service


# Maximum size for tool outputs (truncate if larger)
MAX_TOOL_OUTPUT_SIZE = 300


# Default extraction prompt for skills - tells mem0 WHAT to extract
SKILL_EXTRACTION_PROMPT = """You extract REUSABLE PROCEDURAL SKILLS from agent conversations.

A skill is a learned procedure for accomplishing a task type. Extract skills when:
1. The task was completed successfully
2. It required 2+ steps/tool calls
3. The procedure could help with similar future tasks

For each skill, capture:
- What type of request triggers this (e.g., "send DM on twitter", "create github issue")
- The step-by-step procedure that worked
- Which tools were essential
- How to verify success

DO NOT extract:
- Personal user data (names, specific content, URLs, IDs, emails)
- One-off tasks with no reusable pattern
- Failed attempts
- Simple single-step actions

Format each skill as a clear, reusable procedure that could guide future similar tasks."""


def _truncate_tool_outputs(messages: List[AnyMessage]) -> List[Dict[str, str]]:
    """Convert messages to mem0 format, truncating large tool outputs.

    Tool outputs can be huge (API responses, file contents, etc.)
    We truncate them to keep the conversation manageable while
    preserving the structure and flow.
    """
    formatted = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            # Skip system messages - they're not part of the skill
            continue
        elif isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, list):
                # Handle multimodal - extract text parts
                text_parts = []
                for item in content:
                    if isinstance(item, str):
                        text_parts.append(item)
                    elif isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                content = " ".join(text_parts)
            formatted.append({"role": "user", "content": str(content)})

        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                # Format tool calls concisely
                for call in msg.tool_calls:
                    args_str = str(call.get("args", {}))
                    if len(args_str) > 200:
                        args_str = args_str[:200] + "..."
                    formatted.append(
                        {
                            "role": "assistant",
                            "content": f"[TOOL CALL: {call['name']}({args_str})]",
                        }
                    )
            elif msg.content:
                formatted.append({"role": "assistant", "content": str(msg.content)})

        elif isinstance(msg, ToolMessage):
            # TRUNCATE tool outputs - this is the key optimization
            content = str(msg.content)
            if len(content) > MAX_TOOL_OUTPUT_SIZE:
                # Keep start and indicate truncation
                content = content[:MAX_TOOL_OUTPUT_SIZE] + "... [truncated]"
            formatted.append(
                {"role": "assistant", "content": f"[TOOL RESULT: {content}]"}
            )

    return formatted


def _check_worth_learning(messages: List[AnyMessage]) -> tuple[bool, str]:
    """Quick check if this conversation is worth sending for skill extraction.

    Returns (should_learn, reason).
    """
    if len(messages) < 4:
        return False, "Too few messages"

    # Count tool calls
    tool_calls = 0

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            tool_calls += len(msg.tool_calls)

    if tool_calls < 2:
        return False, f"Only {tool_calls} tool calls - too simple"

    # Check last message for success indicators
    last_ai_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            last_ai_msg = msg
            break

    if last_ai_msg:
        content_lower = str(last_ai_msg.content).lower()
        failure_words = ["sorry", "couldn't", "unable", "failed", "error", "cannot"]
        if any(word in content_lower for word in failure_words):
            if not any(word in content_lower for word in ["fixed", "resolved", "done"]):
                return False, "Task appears to have failed"

    return True, "OK"


async def store_skill(
    messages: List[AnyMessage],
    subagent_id: str,
    session_id: Optional[str] = None,
) -> bool:
    """Store a skill from conversation in mem0 using memory_service.

    Args:
        messages: Full conversation messages
        subagent_id: Which subagent this is (twitter, github, etc.) - REQUIRED for isolation
        session_id: Optional session ID for correlation

    Returns:
        True if stored successfully, False otherwise
    """
    if not subagent_id:
        logger.warning("subagent_id required for skill storage")
        return False

    # Quick check if worth learning
    should_learn, reason = _check_worth_learning(messages)
    if not should_learn:
        logger.debug(f"[{subagent_id}] Skill learning skipped: {reason}")
        return False

    # Convert messages, truncating large tool outputs
    formatted_messages = _truncate_tool_outputs(messages)

    if not formatted_messages:
        return False

    # Store via memory_service with agent_id for isolation
    success = await memory_service.store_memory_batch(
        messages=formatted_messages,
        agent_id=subagent_id,
        conversation_id=session_id,
        metadata={
            "memory_type": "skill",
            "subagent": subagent_id,
        },
        custom_instructions=SKILL_EXTRACTION_PROMPT,
        async_mode=True,
    )

    if success:
        logger.info(f"[{subagent_id}] Skill stored successfully")

    return success


async def search_skills(
    query: str,
    subagent_id: str,
    limit: int = 3,
    threshold: float = 0.5,
) -> List[str]:
    """Search for relevant skills for this subagent.

    Args:
        query: What the user is trying to do
        subagent_id: Which subagent (REQUIRED - only searches this subagent's skills)
        limit: Max results
        threshold: Min relevance score

    Returns:
        List of skill memory contents (raw strings from mem0)
    """
    if not subagent_id:
        return []

    try:
        client = await memory_client_manager.get_client()

        # Search only in this subagent's namespace
        response = await client.search(
            query=query,
            filters={
                "AND": [
                    {"agent_id": subagent_id},
                    {"metadata.memory_type": "skill"},
                ]
            },
            limit=limit,
            rerank=True,
            threshold=threshold,
        )

        # Extract just the memory content - no parsing needed
        skills = []
        results = []

        if isinstance(response, dict):
            results = response.get("results", [])
        elif isinstance(response, list):
            results = response

        for r in results:
            memory = r.get("memory", "")
            if memory:
                skills.append(memory)

        if skills:
            logger.info(f"[{subagent_id}] Found {len(skills)} relevant skills")

        return skills

    except Exception as e:
        logger.error(f"[{subagent_id}] Error searching skills: {e}")
        return []


def format_skills_for_prompt(skills: List[str], subagent_id: str) -> str:
    """Format retrieved skills for injection into system prompt."""
    if not skills:
        return ""

    lines = [
        f"\n## Learned Procedures ({subagent_id}):",
        "Use these approaches if relevant:\n",
    ]

    for i, skill in enumerate(skills, 1):
        lines.append(f"{i}. {skill}")
        lines.append("")

    return "\n".join(lines)
