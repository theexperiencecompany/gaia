# Composio Integration Tests

Live tests that exercise real Composio-connected tools against actual third-party APIs. These require valid credentials (`COMPOSIO_API_KEY`, per-service OAuth tokens) and are skipped automatically when credentials are absent.

Each file covers one integration: Gmail, Google Calendar, Google Docs, LinkedIn, Twitter, Notion, and Linear. Tests verify that the tool can authenticate, perform a basic operation (send a message, create an event, fetch a document), and return a well-formed result.

These tests are not run in CI by default. Run them manually when validating a new Composio SDK version or after OAuth configuration changes.
