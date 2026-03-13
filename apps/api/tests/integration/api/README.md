# Integration Tests — API Endpoints

Tests for the FastAPI HTTP layer using `httpx.AsyncClient` pointed at the real application. The application is booted with a real router but database calls and external services are mocked, so these tests exercise request parsing, authentication middleware, response serialisation, and status codes without needing live infrastructure.

Endpoints covered include chat streaming, conversation CRUD, health checks, integration management, MCP proxy endpoints, and tool listing. A shared `conftest.py` provides the test client and common authentication fixtures.
