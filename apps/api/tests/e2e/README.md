# End-to-End Tests

Full-stack scenario tests that drive a real compiled LangGraph graph from a user message through to a final state, without mocking any GAIA production code. Only live external services (real LLMs, real databases, real APIs) are replaced with in-memory or fake equivalents.

Each test file represents a distinct user scenario:

- **`test_create_todo_flow`** — The agent receives a task, calls `plan_tasks`, and the `todos` channel in state is populated correctly.
- **`test_send_email_flow`** — A dangling tool call (email send interrupted mid-flight) is cleaned up by `filter_messages_node` before the model is re-invoked.
- **`test_multi_tool_scenario`** — Multiple sequential tool calls within a single turn all execute and produce ToolMessages.
- **`test_workflow_execution`** — A workflow definition is compiled and executed through the agent graph.

These tests are the highest-confidence signal that all the layers — nodes, routing, state schema, tool wiring — work together correctly.
