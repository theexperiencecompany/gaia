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

These tests are the highest-confidence signal that all the layers — nodes, routing, state schema, tool wiring — work together correctly.

## `_harness/`

Shared streaming fixtures, not tests:

- **`transcript.py`** — parses SSE (either the chunks `execute_graph_streaming` yields, or a raw HTTP body) into typed frames, and joins each `tool_output` back to its `tool_data` by `tool_call_id`, exactly as the frontend does. Assert through `Transcript`, never on raw prose.
- **`graph_double.py`** — a compiled-graph stand-in that replays a chosen LangGraph event sequence, for the frame-level cases a real run cannot be made to produce on demand.
