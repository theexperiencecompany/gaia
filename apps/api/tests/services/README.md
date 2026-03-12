# Service Tests

Tests for service-layer modules that don't fit neatly into the `unit/services/` structure — primarily the MCP tools store and the user service at a higher integration level.

The MCP tools store tests exercise the ChromaDB-backed tool indexing pipeline: indexing tools by namespace, cache invalidation via Redis, and lookup by tool name or namespace filter. The user service tests cover account creation, preference updates, and lookup by external ID.
