# Unit Tests — Agent Nodes

Tests for the individual LangGraph node functions that run inside the agent graph. Each node is a self-contained async function; these tests call them directly without compiling a graph.

Nodes covered:

- **`filter_messages_node`** — Removes unanswered tool calls from the message history before the model sees them. Pure function, no mocking needed.
- **`follow_up_actions_node`** — Generates suggested follow-up actions after a response and streams them to the client via a stream writer. Tests verify writer call order, LLM input construction, parse-failure fallbacks, and that actions are never stored in graph state.
- **`memory_node`** — Decides whether a conversation is worth learning from, then spawns a fire-and-forget background task to persist user memory. Tests verify the guard conditions, that the correct arguments reach the background coroutine, and that storage errors are swallowed without affecting the node's return value.
- **`manage_system_prompts_node`** — Injects or updates the system prompt in the message history.

All nodes return the input `state` object unchanged when they only produce side effects, so `assert result is state` is the correct assertion for pass-through behaviour.
