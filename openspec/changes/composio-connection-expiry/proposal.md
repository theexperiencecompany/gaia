## Why

GAIA's connection state for a Composio integration can only ever move forwards. `user_integrations.status` is written as `"connected"` on OAuth success and is never written back to any other value; the only thing that clears it is the user pressing Disconnect. When Google/Slack/Notion revokes the grant or the refresh token expires, GAIA never learns. `get_all_integrations_status()` (`app/services/oauth/oauth_service.py:162`) reads Mongo first and short-circuits before it ever asks Composio, behind a 24h Redis cache, so:

- the integrations page keeps showing the account as **Connected**, with no way for the user to know it is dead or to fix it;
- the pre-flight check in `check_integration_connection()` (`app/agents/core/subagents/handoff_tools.py:120`) passes, the agent hands off to the subagent, and the failure only surfaces at the last step as a Composio `NotFoundError` (error `1810`, `ActionExecute_ConnectedAccountNotFound`) — which was an unhandled 500 (GAIA-BACKEND-2ZG) until PR #932 wrapped it in a blanket `except Exception`.

That wrapper stops the 500 but keeps the user exactly as stuck, and it swallows timeouts, 5xx and genuine bugs into the same opaque string. Composio publishes a `composio.connected_account.expired` webhook precisely so this is detectable before a tool call fails; GAIA's webhook endpoint currently rejects it.

## What Changes

- **Add an `expired` connection state.** `user_integrations.status` gains `"expired"` alongside `created` / `connected`, so "was connected, no longer works" is representable and distinguishable from "never connected". The `Literal` appears in five places on `UserIntegrationDocument` / `UserIntegrationUpdate` / `UserIntegrationResponse` (`app/models/integration_models.py:172,188,198,344`), on the repository writer `UserIntegrationsRepository.set_status()` (`app/db/repositories/user_integrations.py:46`), and on `MyIntegrationItem.status` (`app/schemas/integrations/responses.py:138`). Surfaced to web and mobile as a **Reconnect** affordance, not a silent **Connect**.
- **Ingest `composio.connected_account.expired`.** `POST /webhook/composio` currently rejects any non-trigger event because `ComposioWebhookEvent` types `trigger_id` / `trigger_nano_id` / `connection_id` / `connection_nano_id` as required `str` (`app/models/webhook_models.py:182-186`), and connection events carry none of them. Split the envelope so lifecycle events parse and route to a dedicated connection handler, leaving the existing trigger path untouched.
- **Define what happens on receipt** (see design.md for the full sequence): mark the integration `expired`, bust the status/tools/namespace caches, drop the in-memory `connected_account_id` from the proxy client, resync the workspace VFS integrations file, push a WebSocket status update so an open integrations page flips live, and raise one in-app notification with a Reconnect action.
- **Replace the blanket catch with reconciliation.** In `LangchainProvider._wrap_action`, catch `composio_client.NotFoundError` **narrowly** and confirm it is the dead-account error before handling it; re-raise everything else so real failures stay loud. On a confirmed dead account, run the same expiry transition the webhook runs, then emit the existing `integration_connection_required` stream event and return `build_integration_connection_message()` — so the agent asks the user to reconnect and the chat renders the connect card that already exists (`IntegrationConnectionPrompt.tsx`, plus the mobile renderer).
- **Clear `expired` on reconnect.** `handle_oauth_connection()` already writes `connected`; confirm it overwrites the expired record and re-registers the workflow triggers stranded by the dead account.
- **Non-goals:** no retry/refresh of the dead token from GAIA (Composio owns refresh), no auto-disabling of workflows that depend on the integration, no email/push channel for the expiry notice (in-app only).

## Capabilities

### New Capabilities

- `integration-connection-health`: the lifecycle of a user's integration connection state after it is established — how a dead connection is detected (webhook and at tool-execution time), how it is recorded, which caches it invalidates, and how it is surfaced to the user in the integrations UI, in chat, and in notifications.
- `composio-webhook-events`: `POST /webhook/composio`'s contract for receiving Composio events — envelope parsing and validation, signature verification, replay dedupe, and routing of connection-lifecycle events separately from trigger messages.

### Modified Capabilities

None. No existing spec in `openspec/specs/` covers integrations or webhooks.

## Impact

**Backend (`apps/api`)**

- `app/api/v1/endpoints/webhook_composio.py` — envelope split and connection-event routing
- `app/models/webhook_models.py` — `ComposioWebhookEvent` field requirements; new connection-event model
- `app/services/composio/langchain_composio_service.py:131` — replaces the `except Exception` added in PR #932
- `app/db/repositories/user_integrations.py` — `set_status()` accepts `expired` (the only writer; the `repository-boundaries` lint forbids services touching the collection directly)
- `app/services/integrations/user_integration_status.py` — `expired` status passthrough
- `app/models/integration_models.py`, `app/schemas/integrations/responses.py` — `Literal` widening
- `app/services/oauth/oauth_service.py` — `get_all_integrations_status()` must treat `expired` as not connected
- `app/models/notification/notification_models.py` — new `NotificationSourceEnum` member
- New: `app/services/integrations/integration_expiry.py` (shared transition) and the connection-lifecycle webhook handler

**Lints this change must satisfy** (`tools/lints/`, run from `apps/api/.pre-commit-config.yaml`): `repository-boundaries`, `no-service-classes`, `no-silent-fallback`, `wide-events-logging`, `route-contract`.

**Frontend (`apps/web`, `apps/mobile`, `libs/shared/ts`)**

- `IntegrationStatusRecord` / `MyIntegrationItem` shared types gain `expired`
- Integrations list/card renders the Reconnect state
- WebSocket consumer handles the integration status update message

**External**

- A Composio webhook subscription must have `composio.connected_account.expired` in its `enabled_events`. This is a dashboard/API change outside this repo and is a prerequisite for the webhook half; the tool-execution reconciliation half works without it.

**Dependencies**

- None added. `composio==0.13.1` (pinned in `uv.lock`) already ships `composio.core.models.webhook_events` with the event name, payload TypedDicts and `is_connection_expired_event()`.
