# API Route Tests

Smoke and contract tests for FastAPI routes using a real test client. These are lighter-weight than the integration suite in `integration/api/` — they focus on whether routes respond at the right status codes and return the expected shape, rather than deep business logic.

Routes covered: health checks, user endpoints, payment/subscription endpoints, integration management, todo management, and conversation listing. Database calls are mocked via fixtures in `conftest.py`.
