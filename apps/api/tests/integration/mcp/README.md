# Integration Tests — MCP

Tests for the MCP (Model Context Protocol) client lifecycle. MCP servers expose tools to the agent over a network transport; these tests verify that `MCPClient` correctly connects, discovers tools, registers them in the tool store, and cleans up on disconnect.

The MCP transport layer and the integration resolver are mocked so tests run without a live MCP server. The focus is on the connection state machine and the side effects on the tools store and the user's integration status record.
