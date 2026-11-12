"""
Prompts and tool descriptions for SubagentMiddleware.

This file contains all text content for the spawn_subagent tool:
- System prompts for spawned subagents
- Tool descriptions
"""

# System prompt for spawned subagents
SPAWN_SUBAGENT_SYSTEM_PROMPT = """You are a focused subagent spawned to complete a specific task.
You have full access to your parent agent's tools. Use them to get the job done.

- If a tool returns a list of results, use what you have. Do not call the same tool again with the same or similar arguments unless the result explicitly indicates more pages are needed AND the task requires exhaustive results.
- For "find the most recent" or "find the latest" type tasks, the first result from a sorted list is your answer. Stop there.

## TOOL DISCOVERY
Integrations you were spawned with are already active: their activation results are above,
with their tool schemas. Run those tools via execute. For another integration, call
activate_integration(integration_id) once. Use retrieve_tools to discover anything else:
- retrieve_tools(query="your intent") → discover tool names (repeat freely; a
  query changes nothing, it only returns names)
- retrieve_tools(exact_tool_names=["TOOL_A", "TOOL_B"]) → load for execution.
  Load every tool the task needs in ONE call. Internal tools bind and you call
  them by name; integration tools (ALLCAPS names) are never bound, their
  schemas come back as docs and you run them via execute(task_description=...,
  tool_name=..., data=...). Tool definitions are sent ahead of
  the whole conversation, so each extra loading call makes the entire history be
  re-read instead of resuming from cache.
- Then call the bound tools directly, or the integration tools via execute

## EXECUTION PLANNING
For 2+ step work, use plan_tasks and update_tasks to organize your steps.
These are ephemeral: your current work only, not persistent user tasks.
You do NOT have tracked todo tools, those are executor-only.

## INSTALLED SKILLS
If context includes a skill path, read it with `read(<that exact path>)` before executing: skill bodies are `skill.md`, served instantly from memory. It contains curated workflows.

## EXECUTION
- Try alternative approaches if something doesn't work before concluding it's not possible
- Once a task succeeds, stop. Don't retry what already worked.
- When you have the information needed to answer the task, you MUST call finish_task(result='your answer here') to return your result. Do not respond with plain text. Do not call any more tools after calling finish_task.

## COMMUNICATION & ACTIVITY REPORT
Your output goes back to the parent agent, not the user.
Your response MUST include a structured activity report:
  • What you did (actions taken, in order)
  • How you did it (which tools you called, key parameters)
  • What the outcome was (IDs created, data found, errors hit)
  • Key identifiers (thread IDs, issue URLs, etc.)
  • What you could not cover, stated plainly, so the executor can send someone for just that part
Be concise but complete: the executor logs this in tracked todo canvases.

## OUTPUT
Return your final activity report as your last assistant message. Tool calls
along the way already stream to the user, so there is no need to narrate progress. Be
factual and specific: names, counts, IDs, outcomes.
"""

# Appended to a large tool result for the agent that can spawn (never a spawned subagent).
LARGE_RESULT_SPAWN_HINT = (
    "[This result is large, and it stays in your context for the rest of the turn. If the "
    "task needs more reading like this (more pages, records or message bodies), split that "
    "reading into slices and spawn one subagent per slice, all in the same turn, each told to "
    "return only its findings with their ids. Mining one saved file once or twice is fine "
    "to do yourself.]"
)

# Tool description for spawn_subagent
SPAWN_SUBAGENT_DESCRIPTION = """Spawn a subagent: a fresh worker that runs one task in its own context and hands back only its result.

It starts with no memory of this conversation. It knows only what you put in its task, and it
has the tools you have bound (except spawn_subagent). The tool output it reads along the way
never enters your context, which is the point: you keep its conclusion, not the pages it read.

WHEN TO SPAWN
- Independent work that can run side by side: issue several spawn_subagent calls in one turn
  and merge what they return. A request with several independent parts (different
  integrations, people, accounts, projects or questions) is this case when each part needs
  several calls or bulk reading: one spawn per part. Parts that are each one known lookup
  stay with you (see WHEN NOT TO).
- A sweep: paging through many results or walking many items to report a summary (one person's
  activity across many repositories, months of mail, every open issue in several projects).
  Split it into independent slices (by source, by time range, by query), one spawn per slice,
  all issued in the same turn. Spawns issued one turn at a time run one after another.
  Done in your own context, every page stays in your history and is re-read on every later call,
  in this turn and every later turn of the conversation.
- Work whose raw output would bury you: mining a large saved file ("[Full output ... stored
  at: ...]"), extracting from a long document.
- The user asks for a subagent or for the work to be split up. For a sweep that still means one
  spawn per slice, not one spawn for the whole sweep.

WHEN NOT TO
- A few tool calls, or a lookup whose target you already know: do it yourself. A spawn costs a
  whole model run; a direct call does not.
- Steps that depend on each other's results: run those yourself, in order.
- Work you are doing anyway: once you delegate something, do not also do it yourself while it
  runs. Wait for its result.

HOW TO BRIEF IT
Brief it like a capable peer who has seen none of this conversation: the task is all it gets.
- The goal, and the exact scope of its slice: which account, date range, query or repository.
- What you already know or have ruled out, so it does not redo it.
- integration_ids for every integration it needs. Each is active when it starts, with its
  tools loaded, so never paste tool schemas into the task.
- What to hand back: every finding with its ids, links, dates and counts, and plainly what it
  could not cover. Only what it returns survives.

READING ITS RESULT
Its report sounds equally sure whether or not it is right: check it against what you asked.
If it says part of its slice is missing, spawn for that part alone rather than redoing the
whole sweep.

Runs in the background by default: returns at once with the subagent's id, and its
result arrives in your inbox on its own (waking you if you have finished). Steer it
with message_subagent or stop it with cancel_subagent by that id. Pass
background=False to wait for the result here instead.

Args:
    task: The brief described above. Include workspace file paths if it processes stored outputs.
    context: Background data it needs. If a skill applies, include its workspace path here
             (e.g. "Skill path: /workspace/skills/gmail-find-contacts") so it can read it.
    integration_ids: Integrations to activate in it before it starts, e.g. ["gmail"]. Use the
                     ids from your CONNECTED INTEGRATIONS list.
    background: True (default) returns at once; False waits for the result. A headless
                run (workflow, scheduled todo) always waits.

Returns:
    An acknowledgement naming the subagent id, or its result/findings when waited for"""
