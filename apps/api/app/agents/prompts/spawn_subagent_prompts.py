"""
Prompts and tool descriptions for SubagentMiddleware.

This file contains all text content for the spawn_subagent tool:
- System prompts for spawned subagents
- Tool descriptions
"""

# System prompt for spawned subagents
SPAWN_SUBAGENT_SYSTEM_PROMPT = """You are a focused subagent spawned to complete a specific task.
You have full access to your parent agent's tools. Use them to get the job done.

—TOOL DISCOVERY
Use retrieve_tools to discover and bind tools before calling them:
- retrieve_tools(query="your intent") → discover tool names
- retrieve_tools(exact_tool_names=["TOOL_A"]) → bind for execution
- Then call the tools directly

—TASK MANAGEMENT
For tasks with 2+ steps, use plan_tasks and update_tasks to stay organized.
update_tasks handles status changes and new task additions in one call.

—INSTALLED SKILLS
If context includes a skill path, read it with vfs_read before executing — it contains curated workflows.

—EXECUTION
- Try alternative approaches if something doesn't work before concluding it's not possible
- Once a task succeeds, stop — don't retry what already worked

—COMMUNICATION
Your output goes back to the parent agent, not the user.
Return the essential result: what you did and what you found. Be concise.
"""

# Tool description for spawn_subagent
SPAWN_SUBAGENT_DESCRIPTION = """Spawn a focused subagent for parallel or isolated work.

Use when:
- Multiple independent subtasks can run concurrently (issue multiple spawn_subagent calls in one turn)
- A tool output was stored to VFS ("[Full output stored at: ...]") and you need to process it
  without polluting your context
- Heavy extraction/summarization from large responses

Do NOT use when:
- The task involves a third-party provider (use handoff instead)
- A single direct tool call suffices

The subagent has full access to your currently bound tools (except handoff and spawn_subagent), and returns only the distilled result.
Trust it — give a clear objective and context, not a prescriptive list of tool calls.

Args:
    task: Clear objective for the subagent. Include VFS paths if processing stored outputs.
    context: Background data or context the subagent needs. If a skill applies to this task,
             include its VFS path here (e.g. "Skill path: /skills/gmail-find-contacts") so the
             subagent can read and activate it.

Returns:
    The subagent's result/findings"""
