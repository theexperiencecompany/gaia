"""
Workflow context extractor - extracts execution history from thread for workflow creation.

This module provides functionality to:
1. Fetch conversation messages from a thread's checkpointer state
2. Parse tool calls and their outputs
3. Build a summarized context suitable for workflow creation
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.config.loggers import general_logger as logger
from app.config.oauth_config import get_toolkit_to_integration_map


@dataclass
class ExtractedContext:
    """Summarized execution context for workflow creation."""

    suggested_title: str
    summary: str
    workflow_steps: List[Dict[str, Any]]
    integrations_used: List[str] = field(default_factory=list)


class WorkflowContextExtractor:
    """Extracts workflow context from conversation threads."""

    # Maximum characters for truncated outputs
    MAX_OUTPUT_CHARS = 100
    MAX_TOTAL_CHARS = 4000

    # Tools to skip (meta/internal tools that shouldn't become workflow steps)
    SKIP_TOOLS = {
        "handoff",
        "retrieve_tools",
        "search_memory",
        "call_executor",
        "create_workflow",
        "extract_thread_context",
        "search_triggers",
        "get_trigger_schema",
        "list_workflows",
        "get_workflow",
        "execute_workflow",
        "finalize_workflow",
    }

    @classmethod
    async def extract_from_thread(
        cls,
        thread_id: str,
        max_output_chars: Optional[int] = None,
    ) -> Optional[ExtractedContext]:
        """
        Extract workflow context from a conversation thread.

        Fetches messages from the thread's checkpointer state,
        parses tool calls, and builds the workflow context.

        Args:
            thread_id: The thread ID to extract from
            max_output_chars: Override for max output truncation

        Returns:
            ExtractedContext with workflow-ready data, or None if extraction fails
        """
        if max_output_chars is None:
            max_output_chars = cls.MAX_OUTPUT_CHARS

        try:
            messages = await cls._fetch_messages(thread_id)
            if not messages:
                logger.warning(f"No messages found for thread {thread_id}")
                return None

            return cls._build_context(messages, max_output_chars)

        except Exception as e:
            logger.error(f"Error extracting from thread {thread_id}: {e}")
            return None

    @classmethod
    async def _fetch_messages(cls, thread_id: str) -> List:
        """Fetch messages from thread checkpointer."""
        from app.agents.core.graph_builder.checkpointer_manager import (
            get_checkpointer_manager,
        )

        manager = await get_checkpointer_manager()
        checkpointer = manager.get_checkpointer()

        config = {"configurable": {"thread_id": thread_id}}
        state = await checkpointer.aget(config)

        if not state or "channel_values" not in state:
            return []

        return state["channel_values"].get("messages", [])

    @classmethod
    def _build_context(
        cls,
        messages: List,
        max_output_chars: int,
    ) -> ExtractedContext:
        """Build context from message list."""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        steps: List[Dict[str, Any]] = []
        integrations: Set[str] = set()
        tool_outputs: Dict[str, str] = {}  # tool_call_id -> output
        current_agent = "executor"
        first_human_message = ""

        # First pass: collect tool outputs and first human message
        for msg in messages:
            if isinstance(msg, ToolMessage):
                output = str(msg.content)[:max_output_chars]
                tool_call_id = getattr(msg, "tool_call_id", None)
                if tool_call_id:
                    tool_outputs[tool_call_id] = output
            elif isinstance(msg, HumanMessage) and not first_human_message:
                content = msg.content
                if isinstance(content, str):
                    first_human_message = content[:100]
                elif isinstance(content, list) and content:
                    # Handle list content (multimodal)
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            first_human_message = str(item.get("text", ""))[:100]
                            break

        # Second pass: extract tool calls
        for msg in messages:
            if not isinstance(msg, AIMessage):
                continue

            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue

            for tc in tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")

                # Track agent transitions via handoff
                if tool_name == "handoff":
                    subagent_id = tool_args.get("subagent_id", "")
                    current_agent = f"{subagent_id}_agent"
                    integrations.add(subagent_id)
                    continue

                # Skip internal tools
                if tool_name in cls.SKIP_TOOLS:
                    continue

                # Infer category from agent or tool name
                category = cls._infer_category(current_agent, tool_name)
                if category != "general":
                    integrations.add(category)

                # Build workflow step
                steps.append(
                    {
                        "id": f"step_{len(steps)}",
                        "title": cls._humanize_tool_name(tool_name),
                        "category": category,
                        "description": cls._build_description(
                            tool_name,
                            tool_args,
                            tool_outputs.get(tool_id, ""),
                        ),
                    }
                )

        # Generate suggested title
        if first_human_message:
            suggested_title = first_human_message
            if len(suggested_title) > 50:
                # Try to find a natural break point
                break_point = suggested_title[:50].rfind(" ")
                if break_point > 20:
                    suggested_title = suggested_title[:break_point] + "..."
                else:
                    suggested_title = suggested_title[:50] + "..."
        elif integrations:
            suggested_title = f"{', '.join(sorted(integrations)[:3])} Workflow"
        else:
            suggested_title = "New Workflow"

        # Build summary
        if steps:
            integration_list = (
                ", ".join(sorted(integrations)) if integrations else "general tools"
            )
            summary = f"Workflow with {len(steps)} steps using {integration_list}"
        else:
            summary = "No executable steps found in conversation"

        return ExtractedContext(
            suggested_title=suggested_title,
            summary=summary,
            workflow_steps=steps,
            integrations_used=sorted(integrations),
        )

    @classmethod
    def _infer_category(cls, agent: str, tool_name: str) -> str:
        """Infer category from agent name or tool prefix.

        Uses oauth_config.get_toolkit_to_integration_map() as the single source of truth.
        """
        # From agent name: gmail_agent -> gmail
        if agent and agent.endswith("_agent") and agent != "executor":
            return agent.replace("_agent", "")

        # From tool name prefix using oauth_config as source of truth
        tool_upper = tool_name.upper()
        toolkit_map = get_toolkit_to_integration_map()
        for prefix, integration_id in toolkit_map.items():
            if tool_upper.startswith(prefix + "_") or tool_upper.startswith(prefix):
                return integration_id

        return "general"

    @classmethod
    def _humanize_tool_name(cls, tool_name: str) -> str:
        """Convert TOOL_NAME_HERE to 'Tool Name Here'.

        Uses oauth_config.get_toolkit_to_integration_map() as the single source of truth.
        """
        # Remove common prefixes using oauth_config as source of truth
        name = tool_name
        toolkit_map = get_toolkit_to_integration_map()
        for prefix in toolkit_map.keys():
            prefix_with_underscore = prefix + "_"
            if name.upper().startswith(prefix_with_underscore):
                name = name[len(prefix_with_underscore) :]
                break

        # Also handle CUSTOM_ prefix
        if name.upper().startswith("CUSTOM_"):
            name = name[7:]

        return name.replace("_", " ").title()

    @classmethod
    def _build_description(
        cls,
        tool_name: str,
        args: Dict[str, Any],
        output: str,
    ) -> str:
        """Build step description from tool details.

        Args:
            tool_name: Name of the tool that was executed
            args: Arguments passed to the tool
            output: Result returned by the tool (truncated if too long)

        Returns:
            Human-readable description of what the tool did
        """
        parts = [f"Execute {tool_name}"]

        # Add key args (truncated)
        if args:
            arg_strs = []
            for k, v in list(args.items())[:3]:
                v_str = str(v)
                if len(v_str) > 30:
                    v_str = v_str[:30] + "..."
                arg_strs.append(f"{k}={v_str}")
            if arg_strs:
                parts.append(f"with {', '.join(arg_strs)}")

        # Add output if available (truncated to ~100 chars)
        if output and output.strip():
            output_truncated = output.strip()
            if len(output_truncated) > 100:
                output_truncated = output_truncated[:100] + "..."
            parts.append(f"and returned '{output_truncated}'")

        return " ".join(parts)
