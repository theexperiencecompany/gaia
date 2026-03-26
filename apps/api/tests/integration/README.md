# Integration Tests

Tests that exercise multiple real production modules working together. The key difference from unit tests is that production code is imported and run as-is — only live external infrastructure (real databases, real LLM APIs, real third-party services) is mocked or replaced with in-memory alternatives.

These tests catch problems that unit tests miss: incorrect wiring between components, wrong interface assumptions, and graph nodes that work in isolation but break when composed.

Sub-folders by domain:

| Folder | What it covers |
|--------|---------------|
| `agents/` | Full LangGraph graph compilation and execution with fake LLMs |
| `api/` | FastAPI endpoint request/response contracts with a real test client |
| `db/` | Database client wrappers against in-memory or ephemeral backends |
| `mcp/` | MCP client connection lifecycle and tool registration flow |
