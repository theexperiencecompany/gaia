# Agent Infrastructure Tests

Tests for the cross-cutting tool runtime infrastructure: how tools are configured, how runtime config objects are built, and how they are injected into spawned subagents.

The subject is `ToolRuntimeConfig`, `build_child_tool_runtime_config`, `SubAgentFactory`, and the retrieval pipeline that selects which tools a subagent receives. These tests use a minimal compiled graph to verify that tool wiring survives the parent→child handoff correctly.
