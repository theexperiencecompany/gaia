# Unit Tests — Middleware

Tests for the agent middleware execution pipeline (`app/agents/middleware/`). Middleware wraps LangGraph nodes to add cross-cutting behaviour such as subagent lifecycle management.

Tests verify that middleware is registered correctly, executed in the right order, and that failures in one middleware do not cascade unexpectedly. The middleware executor itself is the subject — individual middleware implementations are mocked.
