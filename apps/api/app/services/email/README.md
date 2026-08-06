# Platform Email Service

All transactional email GAIA sends (welcome, support, subscription, re-engagement) flows through this package. It is **not** the user's Gmail — that lives in `app/services/mail/` and sends on behalf of the user via Composio.

## Architecture

```
app/services/email/
├── models.py        EmailMessage — provider-agnostic message shape
├── service.py       send_email() + render_email_template() (Jinja2, app/templates/)
├── senders.py       Domain senders — one function per email GAIA sends
└── providers/
    ├── base.py              EmailProvider protocol + optional MarketingContactsProvider capability
    ├── resend_provider.py   Resend adapter (current default)
    └── __init__.py          Registry + get_email_provider() factory
```

Call sites never touch a provider SDK. They call a domain sender (or `send_email()` with an `EmailMessage`), and the provider is resolved from `settings.EMAIL_PROVIDER` — swapping providers is a config change, not a code change at call sites.

```
senders.py ──> service.send_email(EmailMessage) ──> get_email_provider() ──> ResendEmailProvider
```

Sender identities (`FOUNDER_SENDER`, `SUPPORT_SENDER`) and brand URLs live in `app/constants/email.py`.

## Adding or replacing a provider

1. Create `providers/<name>_provider.py` with a class implementing the `EmailProvider` protocol:

   ```python
   class SesEmailProvider:
       async def send(
           self, message: EmailMessage
       ) -> None: ...  # map EmailMessage fields to the provider API; raise on failure
   ```

   Rules: the adapter must be fully async (wrap sync SDKs in `asyncio.to_thread`), must raise on failure (never swallow — retry/fallback policy belongs to callers), and must not leak provider types outside its module.

2. Register it in `providers/__init__.py`:

   ```python
   _PROVIDER_FACTORIES: dict[str, Callable[[], EmailProvider]] = {
       "resend": ResendEmailProvider,
       "ses": SesEmailProvider,
   }
   ```

3. Add any credentials to `app/config/settings.py` (optional in `DevelopmentSettings`, required in `ProductionSettings`) and `app/config/settings_validator.py`.

4. Set `EMAIL_PROVIDER=<name>` in the environment. Done — every sender now routes through the new adapter.

## Adding a new email type

1. Add a Jinja2 template to `app/templates/`.
2. Add a sender function to `senders.py`: render via `render_email_template()`, build an `EmailMessage` with a sender constant from `app/constants/email.py`, and `await send_email(...)`.
3. Export it from `__init__.py` and import it from `app.services.email` at the call site.

## Error semantics

- `send_email()` raises on failure. Each domain sender decides its own policy (e.g. signup emails are caught at the call site so signup never fails on email errors; support notifications are per-recipient best-effort).
- `add_marketing_contact()` never raises — audience membership is best-effort. It only acts when the configured provider implements the optional `MarketingContactsProvider` protocol (Resend does); otherwise it logs and skips.
- Senders contain no business policy beyond composing the email — e.g. the inactive-user throttle (7/14-day rules) lives with its caller in `app/workers/tasks/user_tasks.py`.

## Future extensions (designed for, not built)

The single `send_email()` choke point is where cross-cutting concerns belong when they become needed: multi-provider failover/rotation, quota-aware routing, a shared suppression list, or queueing sends through ARQ for retry. None of these require touching senders or call sites.

**Going multi-provider:** a router satisfies the same `EmailProvider` protocol as a real adapter, so the upgrade is a composite entirely inside this package — `EMAIL_PROVIDER` becomes a priority list (e.g. `resend,ses`), and `get_email_provider()` returns a router wrapping the listed adapters with the chosen policy (failover on error, quota spillover via Redis counters, or per-category routing — the router sees the full `EmailMessage`). Blast radius: the factory function only. Before enabling it, deal with the operational half: DKIM verification per provider, per-provider bounce/complaint webhooks feeding a shared suppression list, and a GAIA-owned unsubscribe endpoint — provider-hosted suppression state does not follow you across providers.
