# Unit Tests — Agents

Tests for the agent layer: graph construction, routing logic, state schema, and the subagent wiring.

The core subject is `create_agent` (the LangGraph factory) and `GraphManager` (the provider-based graph registry). Tests verify conditional edge registration, path-map contents, and that the routing closure correctly dispatches between the tool node, the select-tools node, and end-graph hooks based on the last AIMessage.

These tests use a fake LLM (`BindableToolsFakeModel`) and a minimal in-memory `dummy_tool` so no real LLM calls are made. The `nodes/` sub-folder covers individual node functions separately.
