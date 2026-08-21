## 1. Expired connection state

- [x] 1.1 Widen the `status` `Literal` to `["created", "connected", "expired"]` at all four sites in `app/models/integration_models.py` (172, 188, 198, 344); add optional `expired_at` and `expired_reason` to `UserIntegrationDocument` and `UserIntegrationUpdate`
- [x] 1.2 Widen `MyIntegrationItem.status` (`app/schemas/integrations/responses.py:138`) to include `"expired"`
- [x] 1.3 Widen `UserIntegrationsRepository.set_status()` (`app/db/repositories/user_integrations.py:46`) to accept `"expired"`, stamping `expired_at` / `expired_reason` on that transition the way `connected_at` is stamped on `connected` — this repository stays the only writer of the collection (`repository-boundaries` lint)
- [x] 1.4 Widen `update_user_integration_status()` (`app/services/integrations/user_integration_status.py:22`) to pass `"expired"` through, leaving the `connected`-only VFS resync untouched
- [x] 1.5 Add `INTEGRATION_STATUS_EXPIRED` to `app/constants/integrations.py`, and verify `get_all_integrations_status()` (`app/services/oauth/oauth_service.py:162`) reports it as `False` — it compares against `INTEGRATION_STATUS_CONNECTED`, so this is a verification, not a change
- [x] 1.6 Verify `handle_oauth_connection()` (`app/services/oauth/oauth_service.py:445`) overwrites an `expired` record back to `connected` and clears `expired_at` / `expired_reason` rather than leaving them stale

## 2. Shared expiry transition

- [x] 2.1 Create `app/services/integrations/integration_expiry.py` with a module-level async `expire_user_integration(user_id, integration_id, *, reason, notify)` — no service class (`no-service-classes` lint)
- [x] 2.2 Implement the no-op guards: return early when `user_integration_repository.get_for_user()` finds nothing, and when the status is already `expired`
- [x] 2.3 Wire the side effects — repository status write, `@CacheInvalidator(USER_INTEGRATION_CACHE_PATTERNS)`, `invalidate_connected_account_cache(user_id, toolkit)` (`app/services/composio/proxy_client.py:395`), `schedule_user_integrations_sync(user_id)`
- [x] 2.4 Behind `notify=True`, broadcast the integration status update via `websocket_manager.broadcast_to_user()` and create one in-app notification with a `REDIRECT` action to the integration's page
- [x] 2.5 Add an `INTEGRATION_EXPIRED` member to `NotificationSourceEnum` (`app/models/notification/notification_models.py:30`)
- [x] 2.6 Instrument with `log.set` / `log.set_ns` carrying user, integration, toolkit, previous status, reason and trigger source (`webhook` vs `tool_execution`) — structured kwargs, never interpolated into the message (`wide-events-logging` lint)

## 3. Tool-execution reconciliation

- [x] 3.1 Replace the blanket `except Exception` at `app/services/composio/langchain_composio_service.py:131` with a narrow `composio_client.NotFoundError` catch; re-raise anything that is not the dead-account error
- [x] 3.2 Add one classifier that confirms Composio `1810` / `ActionExecute_ConnectedAccountNotFound` from the structured error body with the message string as fallback, and reuse it for the existing fuzzy `successful: false` check at lines 150-161 so there is a single source of truth
- [x] 3.3 Extract the `integration_connection_required` emitter into one helper and convert both existing inline sites (`handoff_tools.py:143`, `integration_tool.py:304`) to it — do not add a third inline copy
- [x] 3.4 Capture the running event loop when `LangchainProvider` is constructed; dispatch `expire_user_integration(..., notify=False)` with `asyncio.run_coroutine_threadsafe`, wrapping the coroutine in a `log_context()` boundary (`libs/shared/py/wide_events.py:865`) so its log fields survive; log a warning and skip when no loop is available
- [x] 3.5 On the dead-account path, emit the connect-required event and return `build_integration_connection_message(name, connect_url)` (`app/utils/integration_checker.py:30`)
- [x] 3.6 Handle the `user_id is None` case (trigger-option calls, per the comment at lines 110-120): skip the transition and the stream event, return a structured failure
- [x] 3.7 Run a real dead-account tool call end to end and confirm the transition actually executed and `get_stream_writer()` reached the client from the executor thread — reading the code is not sufficient verification here

## 4. Webhook ingestion

- [x] 4.1 Branch `POST /webhook/composio` on the **raw** `body["type"]` before any model construction, using `is_connection_expired_event()` from `composio.core.models.webhook_events` — `ComposioWebhookEvent`'s `field_validator` uppercases `type` (`app/models/webhook_models.py:190`), so a parsed model can never match the lowercase literal
- [x] 4.2 Add a `ComposioConnectionEvent` model matching the `ConnectionExpiredEvent` payload in design.md; leave `ComposioWebhookEvent` and the `trigger_nano_id or trigger_id` fallback (`webhook_composio.py:41`) untouched unless the split forces a change
- [x] 4.3 Log the first raw connection envelope to confirm the delivered shape against the SDK TypedDicts before trusting the parser
- [x] 4.4 Add the connection-lifecycle handler: resolve the integration via `get_integration_by_config(data.auth_config.id)` (`app/config/oauth_config.py:1976`) with a `data.toolkit.slug` fallback, drop unrecognised integrations, and guard on `data.status ∈ {EXPIRED, REVOKED, FAILED, INACTIVE}`
- [x] 4.5 Dispatch `expire_user_integration(..., notify=True)` via `spawn_logged_task` under the existing `_WEBHOOK_TASK_TIMEOUT`, and keep returning `ComposioWebhookAckResponse` (never a `JSONResponse` — `route-contract` lint and S8409)
- [x] 4.6 Confirm signature verification and `webhook-id` replay dedupe apply to the connection path exactly as they do to triggers

## 5. Clients

- [x] 5.1 Add `expired` to the shared `IntegrationStatusRecord` / `MyIntegrationItem` types in `libs/shared/ts`
- [x] 5.2 Render the Reconnect state in the web integrations list and card, treating any unknown status as `not_connected` at the render layer
- [x] 5.3 Mirror the Reconnect state in the mobile integrations UI
- [x] 5.4 Handle the integration status update WebSocket message so an open integrations page flips without a refresh

## 6. Verification

- [x] 6.1 `nx type-check api` and `nx lint api` clean
- [x] 6.2 `python3 tools/lints/run.py apps/api/app` clean — specifically `repository-boundaries`, `no-service-classes`, `no-silent-fallback`, `wide-events-logging`, `route-contract`
- [x] 6.3 `nx run-many -t type-check --projects=web,desktop,mobile` and the matching lint targets clean
- [x] 6.4 Boot the stack and drive the tool-execution path against a genuinely revoked account (use the `driving-gaia` skill): confirm the connect card renders in chat, the integrations page flips to Reconnect, and the agent asks the user to reconnect without a URL on the UI surface
- [x] 6.5 Confirm a non-dead-account failure (timeout or 5xx) still propagates and still reaches Sentry
- [x] 6.6 Replay a captured `composio.connected_account.expired` delivery against the endpoint and confirm 200, the state transition, the notification, and that a redelivery of the same `webhook-id` is ignored
- [x] 6.7 Reconnect the integration and confirm the status returns to `connected`, the expiry fields are cleared, and the workflow triggers are re-registered
- [ ] 6.8 State explicitly in the PR which parts were driven against a live stack and which were only exercised in tests

## 7. External configuration

- [ ] 7.1 Confirm the project's webhook subscription version and the delivered connection payload shape via `GET /api/v3.1/webhook_subscriptions/event_types` and one real delivery
- [ ] 7.2 Add `composio.connected_account.expired` to the subscription's `enabled_events` — only after section 4 is deployed, so the first delivery is not a 500
