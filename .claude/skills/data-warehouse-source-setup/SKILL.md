---
name: data-warehouse-source-setup
description: Connect a detected data source to the PostHog data warehouse
metadata:
  author: PostHog
  version: 1.46.0
---

# PostHog Data Warehouse — Source Setup

This skill connects a data source the project already uses (a database like Postgres/MySQL, or an API-key source like Stripe) to PostHog's data warehouse, so the data can be queried alongside product analytics.

The wizard has already scanned the project and lists the detected sources in your prompt. Each detected source has a **kind** (e.g. `Postgres`, `Stripe` — this is the PostHog source-type name), a **label**, and a **mode**:

- **`in-cli`** — create the source directly from here (databases and API-key SaaS).
- **`deep-link`** — give the user a pre-filled URL to finish in the PostHog app (OAuth sources; no safe terminal credential path).

## Reference files

- `references/postgres.md` - Linking postgres as a source - docs
- `references/mysql.md` - Linking mysql as a source - docs
- `references/snowflake.md` - Linking snowflake as a source - docs
- `references/bigquery.md` - Linking bigquery as a source - docs
- `references/stripe.md` - Linking stripe as a source - docs
- `references/woocommerce.md` - Linking woocommerce as a source - docs
- `references/shopify.md` - Linking shopify as a source - docs
- `references/wordpress.md` - Linking wordpress as a source - docs
- `references/sources.md` - Link a source - docs
- `references/COMMANDMENTS.md` - Framework-specific rules the integration must follow

Consult the PostHog data warehouse source docs above for source-specific field requirements and sync behavior.

## Tools you will use

You have the PostHog MCP server and the wizard's local tools available. The PostHog tools below are reached through its `exec` tool:

## How to call PostHog MCP tools

The PostHog MCP server exposes a single `exec` tool. Every PostHog operation is driven by a CLI-style command string passed in its `command` parameter — the tool may be namespaced by the host (`mcp__posthog__exec`, `mcp__posthog-wizard__exec`), but the command grammar is the same. Tool names and schemas are not predictable, so discover and inspect before you call.

**Grammar** — run in this order:

```text
exec({ "command": "search <regex>" })      # find tools by name/title/description; `tools` lists them all
exec({ "command": "info <tool_name>" })     # REQUIRED before every call — description + input schema
exec({ "command": "schema <tool_name> <field_path>" })  # drill into a field the schema flags with a `hint`
exec({ "command": "call <tool_name> <json_input>" })    # run the tool
```

Running `info <tool_name>` before `call <tool_name>` is mandatory, the same way you read a file before editing it. `info` returns the full schema for simple tools; for large ones it summarizes and attaches `hint` entries pointing at fields to drill into with `schema`. Dot-notation descends objects (`query.source`), array items (`series.0.properties`), and unions. Never guess the structure of a field that carries a hint — drill first.

Every PostHog tool goes through `exec` this way — there is no separate named tool to call directly. The inner tool names and JSON payloads below are what you pass to `call`.

**Errors** carry a suggestion and similar tool names — read it before retrying. If a name isn't found it may have been renamed; run `search <pattern>` or `tools` again to find the current one.

- **`external-data-sources-wizard`** — returns the required fields per source type. **Always call this for a source kind before creating it** — never guess field names. **Pass `source_type` with the kind(s) you need** (e.g. `source_type: "Postgres"`, or comma-separated `"Postgres,Stripe"`). The unfiltered response describes every source and is hundreds of KB — large enough to blow your context budget — so never call it without `source_type`.
- **`external-data-sources-db-schema`** — validates credentials and lists the tables available for sync. Use this for database sources before creating.
- **`external-data-sources-create`** — creates the source. Follow its input schema exactly for the `payload` and `schemas` shape; the tool definition is the source of truth.
- **`mcp__wizard-tools__check_env_keys`** — tells you which `.env` keys EXIST. It never returns values.
- **`mcp__wizard-tools__wizard_ask`** — the ONLY way to obtain credential values from the user.

## Guiding tenets

1. **Never read or guess secret values.** You cannot read `.env` values — `mcp__wizard-tools__check_env_keys` only reveals which keys exist. Obtain every credential value from the user via `mcp__wizard-tools__wizard_ask`. Never fabricate a host, password, or API key.

2. **Batch a source's credential questions into one `mcp__wizard-tools__wizard_ask` call.** Ask for all of a source's fields (host, port, database, user, password, schema, …) in a single call — up to 8 questions. One call per source is fine; just don't fire several rapid calls for the _same_ source. A follow-up call is allowed when a later question genuinely depends on an earlier answer (e.g. correcting a field after a validation failure). A cancelled or timed-out `wizard_ask` does **not** count against the per-run cap — treat it as "the user declined" and fall back to the deep-link path for that source, without worrying about a wasted call.

3. **Don't pass secret references to the PostHog tools.** If you mark a `wizard_ask` field `sensitive`, the answer comes back as `{ secretRef: ... }`, which only `mcp__wizard-tools__set_env_values` can resolve — `external-data-sources-db-schema`/`-create` reject it. For credentials you'll hand straight to those tools, collect them as normal (non-`sensitive`) `text` answers so you get the real value; reserve `sensitive` for secrets you're only writing to `.env`.

4. **The MCP defines the fields, not you.** Call `external-data-sources-wizard` (with `source_type`) for the kind and ask for exactly the fields it lists (respecting `required`). Don't invent extra fields or omit required ones.

5. **Respect the mode.** Only collect credentials and create `in-cli` sources. For `deep-link` sources, provide the URL and stop — do not try to collect OAuth tokens.

6. **Don't modify project code.** This skill connects external data; it does not edit the user's application. Make no source-code changes.

## Pre-flight: credential gotchas that cause most failures

Surface these **before** collecting credentials — they're the top reasons setup fails on the first try, and a failed attempt wastes a `wizard_ask`.

- **The host must be reachable from PostHog's network.** `localhost`, `127.0.0.1`, and private/RFC-1918 hosts (`10.x`, `192.168.x`, `172.16–31.x`) are rejected — PostHog connects from its own infrastructure, not the user's machine. Serverless/managed Postgres (Neon, Supabase, RDS behind strict rules) often also needs PostHog's egress IPs allowlisted first. If the database isn't publicly reachable, go straight to the deep-link path instead of collecting credentials that can't validate.
- **Supabase is Postgres — set it up as one source.** Use the **Session pooler**, not the direct host (the direct host is IPv6-only). The pooler host looks like `aws-0-<region>.pooler.supabase.com`, the **username** must be `postgres.<project-ref>`, and the **port is 6543** (not 5432). The password is the **database** password (Supabase → Settings → Database), which is distinct from the `anon`/`service_role` JWT keys and the account password. If `SUPABASE_URL` exists in the env, derive the project ref from `db.<ref>.supabase.co` to pre-fill the host/username in your prompt.
- **Many SaaS sources need a specific key type or plan** — name the right one in your `wizard_ask` prompt so the user doesn't paste the wrong thing: **Stripe** wants a _restricted_ key (`rk_live_…`), not `sk_live_…`; **Sentry** wants an internal-integration token (not a DSN or personal token); **RevenueCat** a v2 secret key with read scopes; **Convex** requires the Professional plan; **Twilio** an API Key SID + Secret (not the account auth token); **Mailchimp** a key with its `-usX` datacenter suffix. For send-only services (Resend, Mailgun) the key in the env is often restricted — the warehouse import needs a full/read-access key.

## Workflow

If your prompt lists no detected sources, emit `[ABORT] No data source detected` and stop. The wizard middleware catches `[ABORT]` and terminates the run.

Process each detected source in turn.

### For an `in-cli` source

1. `[STATUS] Configuring <label>`
2. Call `external-data-sources-wizard` **with `source_type` set to this `kind`** (never unfiltered) and read the field list. Check the pre-flight gotchas above for this kind before prompting.
3. Optionally call `mcp__wizard-tools__check_env_keys` to see which matching keys already exist — use this only to tailor your prompt (e.g. "we noticed `DATABASE_URL` is set; please paste the connection details"). You still cannot read the value.
4. Call `mcp__wizard-tools__wizard_ask` ONCE, requesting all required fields for the source. If the user declines or cannot provide them, fall back to the deep-link path below for this source.
5. For database sources, call `external-data-sources-db-schema` with the credentials to validate them and list tables. If validation fails, report the error and let the user correct it (one more `mcp__wizard-tools__wizard_ask`), or fall back to deep-link.
6. Build the create payload: `source_type` = the kind, the credential `payload`, `access_method` = `warehouse` (use `direct` only if the user explicitly wants live querying without import), and a `schemas` array selecting tables to sync (default: sync the tables the user wants; pick `incremental` sync with the detected incremental field when available, otherwise `full_refresh`). Follow the `external-data-sources-create` input schema for the exact shape.
7. Call `external-data-sources-create`. On success: `[STATUS] Connected <label>`. On failure: emit `[ABORT] Source creation failed`.

### For a `deep-link` source

1. `[STATUS] <label> needs browser setup`
2. Build the URL from the project context in your prompt (PostHog Host + Project ID):
   `<host>/project/<projectId>/data-warehouse/new-source?kind=<kind>&utm_source=wizard&utm_campaign=warehouse-source`
   Keep the `utm_*` params exactly as written — they let PostHog attribute sources finished in the browser back to the wizard handoff.
3. Tell the user to open that URL to finish connecting `<label>` (OAuth happens in the app). Include the URL in your report. Do not attempt credential collection.

### Non-interactive / CI

If `mcp__wizard-tools__wizard_ask` is unavailable or blocked (CI / headless), do NOT block. Treat every source as deep-link: emit the new-source URL for each and note that credentials must be entered in the app.

## Report

After processing all sources, write the report file requested by the wizard. Summarize:

- Which sources were created in PostHog (kind + which tables sync).
- Which sources need browser setup, with their URLs.
- Any source that was skipped and why.

## Status

Report progress with `[STATUS]` prefixed messages (e.g. `Configuring Postgres`, `Connected Postgres`, `Stripe needs browser setup`).

## Abort statuses

Report abort states with `[ABORT]` prefixed messages:

- No data source detected
- Source creation failed

## Framework guidelines

- A missing PostHog configuration must never break the app — read keys optionally (never a required setting), guard init and capture behind their presence, and keep build and boot working with no PostHog environment set — but never silently: in development or debug builds fail loudly, using the language's idiomatic error, with the message "<VAR> variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once <VAR> is configured" (substituting the actual variable name); production stays a no-op
