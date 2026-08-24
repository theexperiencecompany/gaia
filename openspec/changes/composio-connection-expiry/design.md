> All file:line references are against `origin/develop` (base branch), not `master`.

## Context

### Current state

Connection state for a Composio-managed integration is written in exactly two places and only ever moves forwards:

| Path | Effect on `user_integrations` |
|---|---|
| `handle_oauth_connection()` — `app/services/oauth/oauth_service.py:445` | upserts `status: "connected"` |
| `disconnect_integration()` — `app/services/integrations/integration_connection_service.py:488` | deletes the record (platform integrations) |

The write itself goes through the repository layer: `UserIntegrationsRepository.set_status()` (`app/db/repositories/user_integrations.py:46`), whose `status` parameter is `Literal["created", "connected"]`, as is the service wrapper `update_user_integration_status()` (`app/services/integrations/user_integration_status.py:22`) and `UserIntegrationDocument.status` (`app/models/integration_models.py:188`). There is no value that means "this used to work and no longer does".

Reads go through `get_all_integrations_status()` (`app/services/oauth/oauth_service.py:162`), Mongo-first behind a 24h Redis cache:

```
user_integrations doc exists?  ──yes──▶  use its status, return       ← Composio never consulted
                               ──no───▶  batch-check Composio
```

So once a Composio account is revoked or its refresh token expires, GAIA keeps believing it is connected. Three things follow:

1. The integrations page shows **Connected** indefinitely.
2. The pre-flight guard `check_integration_connection()` (`app/agents/core/subagents/handoff_tools.py:120`) passes, so the agent hands off and commits to the task.
3. Failure lands at the last possible moment as Composio error `1810` / `ActionExecute_ConnectedAccountNotFound`, raised as `composio_client.NotFoundError`. That was an unhandled 500 (Sentry GAIA-BACKEND-2ZG) until PR #932 wrapped `execute_tool` in `except Exception` (`app/services/composio/langchain_composio_service.py:131`).

### What already exists and should be reused

- **A connect card in chat.** Streaming `{"integration_connection_required": {"integration_id", "message"}}` renders `apps/web/src/features/chat/components/bubbles/bot/IntegrationConnectionPrompt.tsx` and the mobile equivalent in `apps/mobile/src/features/chat/tool-data/renderers.tsx`. On develop there are exactly two emitters left — `handoff_tools.py:143` and `integration_tool.py:304` — each constructing the payload inline. Adding a third inline copy would be the "one canonical way" violation the repo rules call out, so this change extracts the emitter once and converts both existing sites.
- **Surface-aware agent copy.** `build_integration_connection_message()` (`app/utils/integration_checker.py:30`) branches on UI vs. text-only clients; `build_connect_link_url()` mints the single-use link.
- **Reverse lookup from Composio auth config to integration.** `get_integration_by_config(auth_config_id)` (`app/config/oauth_config.py:1976`).
- **Proxy account-id cache invalidation.** `invalidate_connected_account_cache(user_id, toolkit)` (`app/services/composio/proxy_client.py:395`).
- **Cache patterns.** `USER_INTEGRATION_CACHE_PATTERNS` (`app/constants/cache.py:97`) covers `tools:user:{user_id}:*`, `tool_namespaces:{user_id}` and `oauth_status:{user_id}`.
- **Signature verification and replay dedupe** on `POST /webhook/composio` (`verify_composio_webhook_signature`, plus `SET NX EX 3600` on the `webhook-id` header).
- **Sanctioned fire-and-forget.** `spawn_logged_task(operation, coro, **ctx)` (`libs/shared/py/wide_events.py:895`) — already used by the webhook endpoint at line 108. Without a boundary, a background task's `log.set()` fields are silently discarded.
- **In-app notifications with actions** — `notification_service.create_notification()` with a `REDIRECT` action, as used by `app/services/workflow/notifications.py`.

### Composio's contract

`composio==0.13.1` (pinned in `uv.lock`) ships `composio/core/models/webhook_events.py`, which is the authoritative source for the payload below.

**Event name:** `WebhookEventType.CONNECTION_EXPIRED = "composio.connected_account.expired"` — emitted when a connected account expires because auth refresh failed. The SDK also exports the type guard `is_connection_expired_event(payload)`.

**Connection statuses** (`ConnectionStatusEnum`): `INITIALIZING`, `INITIATED`, `ACTIVE`, `FAILED`, `EXPIRED`, `INACTIVE`, `REVOKED`. The SDK treats `FAILED`, `EXPIRED`, `REVOKED` as terminal (`_TERMINAL_CONNECTION_STATES` in `composio/core/models/connected_accounts.py`); `INACTIVE` is excluded there because it can recover to `ACTIVE`, but an `INACTIVE` account still cannot execute tools.

**Delivery headers** (identical to the trigger webhook GAIA already verifies):

| Header | Meaning |
|---|---|
| `webhook-id` | unique delivery id — GAIA's replay dedupe key |
| `webhook-timestamp` | signature timestamp |
| `webhook-signature` | `v1,<base64 HMAC-SHA256 of "{webhook-id}.{webhook-timestamp}.{rawBody}">` |

**Payload** — `ConnectionExpiredEvent`, with `data` shaped as `SingleConnectedAccountDetailedResponse` (mirrors `GET /api/v3/connected_accounts/{id}`, raw snake_case):

```json
{
  "id": "msg_847cdfcd-d219-4f18-a6dd-91acd42ca94a",
  "type": "composio.connected_account.expired",
  "timestamp": "2026-08-10T05:44:33Z",
  "metadata": {
    "project_id": "proj_...",
    "org_id": "org_..."
  },
  "data": {
    "id": "ca_xxxxxxxxxxxx",
    "user_id": "68b1f0c2d4e5a6b7c8d9e0f1",
    "status": "EXPIRED",
    "status_reason": "refresh_token_revoked",
    "is_disabled": false,
    "toolkit": { "slug": "GMAIL" },
    "auth_config": {
      "id": "ac_svLPDmjcTVMX",
      "auth_scheme": "OAUTH2",
      "is_composio_managed": true,
      "is_disabled": false
    },
    "state": { "authScheme": "OAUTH2", "val": { "status": "EXPIRED" } },
    "data": {},
    "params": {},
    "created_at": "2026-05-02T09:12:44Z",
    "updated_at": "2026-08-10T05:44:33Z"
  }
}
```

Fields this design depends on:

| Field | Use |
|---|---|
| `type` | routing discriminator |
| `data.user_id` | the GAIA user id — `connect_account()` passes GAIA's Mongo `_id` string as Composio's `user_id`, so no translation table is needed |
| `data.auth_config.id` | primary integration lookup via `get_integration_by_config()` |
| `data.toolkit.slug` | fallback lookup and the key for `invalidate_connected_account_cache()` |
| `data.status` | guard — only act on a dead status |
| `data.id` | connected-account nanoid, for logs |
| `data.status_reason` | human-readable cause, for logs |

**Two reasons the endpoint rejects this today.**

1. `webhook_composio.py:86` builds `ComposioWebhookEvent` with `connection_id`, `connection_nano_id`, `trigger_nano_id` and `trigger_id` pulled out of `data` — all typed as required `str` (`app/models/webhook_models.py:182-186`). A connection event carries none of them, so every field resolves to `None` and Pydantic raises before routing. The request 500s and Composio retries it forever.
2. `ComposioWebhookEvent` has a `field_validator("type", mode="before")` that **uppercases** the event type (`webhook_models.py:190`), to match the `TRIGGER_TYPES` convention. `"composio.connected_account.expired"` would become `"COMPOSIO.CONNECTED_ACCOUNT.EXPIRED"`, so `is_connection_expired_event()` — which compares against the lowercase literal — can never match a parsed model. Routing must read the raw `body["type"]` *before* model construction.

Docs: [Verifying webhooks](https://docs.composio.dev/docs/webhook-verification) · [Receiving events](https://docs.composio.dev/docs/setting-up-triggers/subscribing-to-events) · [Connected accounts](https://docs.composio.dev/docs/connected-accounts) · [List event types](https://docs.composio.dev/reference/api-reference/webhook-subscriptions/getWebhookSubscriptionsEventTypes)

## Goals / Non-Goals

**Goals:**

- Detect a dead Composio connection proactively (webhook) and defensively (at tool-execution time), with one shared state transition behind both.
- Make "was connected, now broken" a first-class, persisted state that reads as **Reconnect** in the UI rather than silently as **Connected** or **Connect**.
- Keep the failing tool call useful: the agent should ask the user to reconnect and the chat should render the connect card that already exists.
- Stop masking unrelated tool failures — narrow the catch introduced in PR #932.

**Non-Goals:**

- Refreshing or repairing the upstream token from GAIA. Composio owns refresh; when it gives up, only the user can fix it.
- Auto-disabling or deleting workflows and triggers that depend on the expired integration. They stay as-is and are re-registered on reconnect by the existing `TriggerService.resync_user_workflow_triggers` path.
- Email or push delivery of the expiry notice. In-app only.
- Backfilling historical expiries. Accounts already dead before this ships heal the first time a tool call hits them.
- Handling MCP or self-managed (Google) integration expiry. Different failure modes, different owners; this change is Composio-only.

## Decisions

### D1. Narrow the catch to the dead-account error; re-raise everything else

`_wrap_action` catches `composio_client.NotFoundError` and confirms it is the connected-account failure (Composio code `1810` / `ActionExecute_ConnectedAccountNotFound`, read from the error body with the message string as fallback) before handling it. Anything else propagates.

*Why:* the blanket `except Exception` in PR #932 converts timeouts, 5xx, rate limits and genuine bugs into one indistinguishable `{"successful": false, "error": "<str>"}`. It also removes Sentry's view of the failure, which is how this bug was found in the first place.

*Note on the linter:* develop ships a `no-silent-fallback` lint (`tools/lints/no_silent_fallback.py`) whose stated fix — "catch the specific exception that means that; `except ValueError` is a decision, `except Exception` is a blanket" — is exactly this decision. It would **not** flag PR #932's handler, because the rule only fires when a broad except substitutes a *falsy* value and #932 returns a truthy dict. So the lint endorses the direction but does not enforce it here; the reasoning has to stand on its own.

*Alternative rejected:* string-matching the error message only. The existing observability block at `langchain_composio_service.py:150-161` already does fuzzy matching (`"1810" in err_lower`, `"no active connected account"`) for *logging*, which is fine for a log line but too loose to drive a state mutation. Prefer the typed exception plus the structured error code, and keep the fuzzy matcher for the `successful: false` (non-raising) case where Composio returns rather than raises.

### D2. Add an `expired` status rather than deleting the record

*Why:* deleting would make `get_all_integrations_status()` fall through to the live Composio check and correctly return `False` with no schema change — but it is indistinguishable from "never connected", so the UI can only say **Connect**. The user's complaint is precisely that they are not told the integration *broke*. `expired` also gives us an idempotency key: we notify on the `connected → expired` edge only.

*Cost:* five `Literal` sites in `app/models/integration_models.py` (172, 188, 198, 344), the repository writer's signature (`app/db/repositories/user_integrations.py:46`), the service wrapper (`user_integration_status.py:22`), `MyIntegrationItem.status` (`app/schemas/integrations/responses.py:138`), and the shared TS types consumed by web and mobile. `apps/web/src/features/integrations/types/index.ts` already declares an `error` state on `Integration`, so the frontend union is not starting from zero.

### D3. One transition function, two callers

`expire_user_integration(user_id, integration_id, *, reason, notify)` lives in a new `app/services/integrations/integration_expiry.py` and is the only caller that sets the `expired` status. It writes through `user_integration_repository` — the `repository-boundaries` lint forbids a service touching `user_integrations` directly, and the ownership rule means only that repository may. It:

- no-ops when no `user_integrations` document exists (never fabricates one) and when the status is already `expired` (idempotent);
- writes the status via the repository, stamping `expired_at` and `expired_reason`;
- invalidates `USER_INTEGRATION_CACHE_PATTERNS` via the existing `@CacheInvalidator`;
- calls `invalidate_connected_account_cache(user_id, toolkit)`;
- calls `schedule_user_integrations_sync(user_id)` so the workspace VFS integrations file stops advertising the toolkit;
- when `notify=True`, broadcasts the WebSocket status update and raises the in-app notification.

Per the repo's service-layer rule it is a module-level async function, not a class.

*Why the `notify` flag:* on the webhook path the user is not looking at GAIA, so the notification and the live page update are the whole point. On the tool-execution path the user is in the conversation and is about to be handed a connect card in-line — a notification saying the same thing seconds later is noise. Same state transition, different escalation.

### D4. Bridging the tool path's sync context

`_wrap_action`'s wrapper is a **sync** function (`StructuredTool.from_function(func=...)`, no coroutine), so it cannot await the transition. Redis in this codebase is async-only (`redis.asyncio`, `app/db/redis.py`), so there is no sync route to cache invalidation. `spawn_logged_task` — the sanctioned spawner — wraps `asyncio.create_task`, which requires a running loop *in the calling thread*, and this call runs in an executor thread. So it cannot be used directly here.

Chosen mechanism: capture the running event loop once when `LangchainProvider` is constructed, and dispatch with `asyncio.run_coroutine_threadsafe(coro, loop)` without awaiting the future, where `coro` is wrapped in a `log_context()` boundary (`libs/shared/py/wide_events.py:865`) so its `log.set()` fields are not silently discarded — the same protection `spawn_logged_task` provides. LangGraph invokes these tools through `ainvoke`, which runs the sync callable in an executor thread of that same loop, so the loop is live and the dispatch is safe. If no loop was captured, log a warning and skip the transition — the connect card and agent message still ship.

*Alternatives rejected:* (a) a parallel synchronous Mongo + Redis client just for this path — duplicates the DB layer to serve one call site and breaks the repository boundary; (b) an ARQ job — enqueueing is itself async, so it does not remove the bridge, it only adds a hop.

**This is the one part of the design that must be proven by running it, not by reading it** — contextvar and loop behaviour through LangChain's executor hand-off is exactly the kind of thing that reads correct and behaves otherwise. The same applies to `get_stream_writer()` from this context. Use the `driving-gaia` skill to exercise it against a live stack.

### D5. `user_id` is not always available in the tool wrapper

The comment at `langchain_composio_service.py:110-120` is load-bearing: `user_id` is read from the runnable config metadata and is present for agent-flow calls but `None` for trigger-option calls, which bind the user at `get_tool(user_id=...)` time. When `user_id` is `None`, skip the state transition and the stream event, and return a plain structured failure. The webhook path covers that case with no dependency on chat context.

### D6. Split the webhook envelope instead of loosening the trigger model

Branch on the **raw** `body["type"]` before any model construction (see the uppercasing validator in Context), routing connection events to a `ComposioConnectionEvent` model and everything else down the existing `ComposioWebhookEvent` path. Use `is_connection_expired_event()` from the SDK against the raw body so the event-name literal is not duplicated in GAIA. Make the four identifier fields optional on `ComposioWebhookEvent` only if the trigger path still needs them nullable after the split — prefer leaving that model exactly as it is.

*Why not one permissive model:* every field optional means the trigger handlers lose the validation that currently guarantees they get an id, and the `trigger_nano_id or trigger_id` fallback at `webhook_composio.py:41` (which exists because matching against the internal UUID silently never hits) becomes easy to regress.

The endpoint returns `ComposioWebhookAckResponse` under develop's route contract — return the model, never a `JSONResponse`.

### D7. What happens when a disconnect event is received

```
POST /webhook/composio
  │
  ├─ verify_composio_webhook_signature(request)            ── 401 on failure, nothing mutated
  ├─ SETNX webhook:composio:{webhook-id} (TTL 1h)          ── 200 "duplicate ignored" on replay
  ├─ read raw body, branch on body["type"] BEFORE model construction
  │     └─ composio.connected_account.expired
  │           ├─ resolve integration: get_integration_by_config(data.auth_config.id)
  │           │     └─ fallback: match data.toolkit.slug against composio_config.toolkit
  │           │     └─ no match → log + drop, return 200
  │           ├─ resolve user: data.user_id (already the GAIA user id)
  │           └─ guard: data.status ∈ {EXPIRED, REVOKED, FAILED, INACTIVE}
  │                 └─ otherwise → log + drop, return 200
  ├─ return ComposioWebhookAckResponse immediately
  └─ spawn_logged_task("composio_connection_expiry", ...)   ── existing _WEBHOOK_TASK_TIMEOUT = 120s
        └─ expire_user_integration(user_id, integration_id, reason=data.status_reason, notify=True)
              1. user_integrations record missing        → no-op
              2. status already "expired"                → no-op (no duplicate notification)
              3. repository set_status("expired") + expired_at + expired_reason
              4. @CacheInvalidator busts USER_INTEGRATION_CACHE_PATTERNS
                 (oauth_status:{user_id}, tools:user:{user_id}:*, tool_namespaces:{user_id})
              5. invalidate_connected_account_cache(user_id, toolkit=data.toolkit.slug)
              6. schedule_user_integrations_sync(user_id)          → workspace VFS
              7. websocket_manager.broadcast_to_user(user_id, {integration_status_update})
              8. notification_service.create_notification(...)     → in-app, REDIRECT action
                 to the integrations page for that integration
```

After step 4 the next `get_all_integrations_status()` recomputes and reports the integration as disconnected, so: the integrations page shows **Reconnect**, tool retrieval stops offering that toolkit's tools, the CONNECTED INTEGRATIONS block in the comms prompt drops it (so the agent stops attempting handoffs), and the pre-flight guard now correctly fails closed with the connect card.

Deliberately **not** done on receipt: no trigger deletion, no workflow deactivation, no token refresh attempt, no external-channel push.

The tool-execution path is the same transition with a different tail:

```
execute_tool raises composio_client.NotFoundError
  └─ error code 1810 / ActionExecute_ConnectedAccountNotFound?
        ├─ no  → re-raise
        └─ yes → user_id known?
                   ├─ no  → return structured failure, log
                   └─ yes → run_coroutine_threadsafe(expire_user_integration(..., notify=False))
                            emit_integration_connection_required(integration_id, message)
                            return build_integration_connection_message(name, connect_url)
```

## Risks / Trade-offs

- **The webhook event may not be enabled on the Composio project** → the subscription needs `composio.connected_account.expired` in `enabled_events` (dashboard or API). Until then only the tool-execution path fires, which still fixes the user-visible bug — just reactively instead of proactively. Ship the tool path first so the change stands alone.
- **Webhook envelope version drift** → GAIA reads `data.trigger_nano_id` for triggers, whereas the current V3 trigger envelope documents `metadata.trigger_id`, which suggests this subscription is on an older webhook version. The connection payload above is taken from the pinned SDK's TypedDicts; the actual delivered shape must be confirmed against a real delivery before the handler is trusted. Mitigation: parse defensively, log the raw envelope once behind `LogTag.COMPOSIO`, and drop rather than raise on an unrecognised shape.
- **`INACTIVE` is recoverable** → Composio excludes it from its terminal set because it can return to `ACTIVE`. Treating it as `expired` may show a Reconnect prompt for an account that heals itself. Accepted: an `INACTIVE` account cannot execute tools, so showing it as usable is the worse error, and reconnecting is harmless.
- **The sync→async dispatch in `_wrap_action`** → if the loop capture is wrong the transition silently never runs, and the missing `log_context()` boundary would additionally swallow its log fields, making that failure invisible. Mitigation: log at warning when the loop is unavailable, and assert the path by running a real dead-account tool call (not by reading). The connect card still renders even if the transition is skipped.
- **False expiry from a misread error** → would show Reconnect on a healthy integration. Mitigation: gate on the typed exception *and* the structured error code; a reconnect is cheap and self-correcting, and step 2's idempotency means at most one notification.
- **Notification fatigue** → an integration that flaps would notify per `connected → expired` edge. Mitigation: the transition only notifies on that edge, so flapping requires a real reconnect in between.
- **Widening the status `Literal` touches three apps** → an unhandled `expired` value in web or mobile could render as a blank or crash a switch. Mitigation: land the shared TS type and both clients' handling in the same change; treat unknown statuses as `not_connected` at the render layer.

## Migration Plan

1. **Backend, tool-execution path first.** `expired` status through the repository + `expire_user_integration()` + the narrow catch replacing PR #932's blanket one. Self-contained: no Composio-side change, no client change strictly required (an unknown status degrades to "not connected" on the client until step 3 lands).
2. **Clients.** Shared TS type, web and mobile Reconnect rendering, WebSocket status-update handling.
3. **Webhook.** Envelope split and the connection handler, deployed *before* the Composio subscription is updated so the first delivery is not a 500.
4. **Enable `composio.connected_account.expired`** on the Composio webhook subscription. Verify with a real delivery.

**Rollback:** each step is independently revertible. Reverting step 1 restores the pre-change behaviour for new failures; records already written as `expired` continue to read as "not connected" through the fall-through branch of `get_all_integrations_status()`, so no data migration is needed in either direction. The `Literal` widening is the one thing to revert last — an old build reading an `expired` document would fail validation.

## Open Questions

- Which webhook version is this project's subscription on, and does the delivered connection payload match the SDK TypedDicts above? Confirm with `GET /api/v3.1/webhook_subscriptions/event_types` (needs `COMPOSIO_KEY`, not present in this worktree) and one captured delivery.
- Should `INACTIVE` map to `expired`, or to a softer state that suppresses the notification while still failing the connection check? Defaulting to `expired` above.
- Does the workspace VFS integrations file need the expired entry removed, or listed with a broken marker so the agent can explain the state rather than silently losing the capability?

*Resolved on develop:* `NotificationSourceEnum` now carries `USAGE_LIMIT` alongside the AI/workflow-shaped members, so a plain `INTEGRATION_EXPIRED` member fits the existing convention — no need to reuse `BACKGROUND_JOB`.
