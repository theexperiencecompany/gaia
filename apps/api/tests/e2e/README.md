# End-to-End Tests

Full-stack scenario tests that drive a real compiled LangGraph graph from a user message through to a final state, without mocking any GAIA production code. Only live external services (real LLMs, real databases, real APIs) are replaced with in-memory or fake equivalents.

Each test file represents a distinct user scenario:

- **`test_create_todo_flow`** — The agent receives a task, calls `plan_tasks`, and the `todos` channel in state is populated correctly.
- **`test_send_email_flow`** — A dangling tool call (email send interrupted mid-flight) is cleaned up by `filter_messages_node` before the model is re-invoked.
- **`test_multi_tool_scenario`** — Multiple sequential tool calls within a single turn all execute and produce ToolMessages.
- **`test_workflow_execution`** — A workflow definition is compiled and executed through the agent graph.
- **`test_chat_stream`** — One user turn through the real comms graph, asserted on the SSE transcript the client receives: text, tool cards, results, and what must *not* replay across turns.
- **`test_tool_visibility`** — The chat stream's frame contract, scenario by scenario: the nested `tool_calls_data` envelope, the `tool_call_id` join, the node gate, dedup, suppression rules, cancellation.
- **`test_subagent_stream`** — The real subagent driver: every frame tagged with its `subagent_id` (the frontend's only routing key), the narration-only guard that makes a parent re-issue a handoff, HIL pauses, and malformed/empty stream events.
- **`test_prompt_contract`** — The prompt layer pinned at the model boundary: `construct_langchain_messages` output must reach the model byte-identical past the pre-model hooks; tool declarations are asserted on `model_bound_tools` (the `bind_tools` channel), not on prose.

These tests are the highest-confidence signal that all the layers — nodes, routing, state schema, tool wiring — work together correctly.

## `_harness/`

Shared infrastructure, not tests:

- **`transcript.py`** — parses SSE (either the chunks `execute_graph_streaming` yields, or a raw HTTP body) into typed frames, and joins each `tool_output` back to its `tool_data` by `tool_call_id`, exactly as the frontend does. Assert through `Transcript`, never on raw prose.
- **`graph_double.py`** — a compiled-graph stand-in that replays a chosen LangGraph event sequence, for the frame-level cases a real run cannot be made to produce on demand.
- **`graph_run.py`** — the offline graph driver. `comms_graph()` / `executor_graph()` build the **real** compiled graph with only the model and narrow I/O seams replaced (ChromaDB store → `InMemoryStore`, Postgres checkpointer → in-memory); `run_graph()` drives one turn and returns a `GraphRun` typed with what the graph did (`tool_names`, `ran()`, `nodes()`, `results_from()`, `last_prompt()`, `bound_tools()`).
- **Recording fake models** (`graph_run.py`):
  - `RecordingFakeModel` — a scripted fake that *records* what the model was shown. Pre-model hooks rewrite the message list on the way in and that rewrite never reaches the checkpoint, so `last_chat_messages` / `chat_messages_log` are the only place a hook's effect is observable — this is what `test_prompt_contract` asserts on. `bind_tools` also records what was bound, making tool-surface assertions falsifiable.
  - `CallAllToolsModel` — calls *every* bound tool on its first turn, then replies "Tool calls complete." so the run still terminates: a cheap way to exercise every tool a graph binds.
  - `scripted_model()` — replays a script (`str` reply, `dict` tool call, `list[dict]` parallel calls, raw `BaseMessage`); `scripted_model_of(graph)` returns the model a graph was built with (valid inside the graph's `async with` block).
