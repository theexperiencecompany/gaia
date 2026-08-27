> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Linking WordPress as a source - Docs

Copy page

# Linking WordPress as a source - Docs

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_9608fcca70)

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_dark_a92b0e022d)

Let AI connect your sources for you

Skip the manual setup — run this in your project and the wizard auto-detects your databases and APIs and connects them to PostHog.

`npx @posthog/wizard warehouse`

[Learn more](/wizard.md)

![PostHog Wizard hedgehog](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)

![](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)Let AI connect your sources for you

**Alpha release**

This source is currently in **alpha**. The interface and available tables may change.

The WordPress connector syncs posts, pages, comments, media, categories, tags, and users from a self-hosted WordPress site into the PostHog Data warehouse via the core REST API (`/wp-json/wp/v2`).

## Prerequisites

You need a self-hosted WordPress site with the core REST API available. Public, published content syncs without credentials. To sync private content or authenticate, you need WordPress 5.6+ on an HTTPS site so you can create an application password.

## Adding a data source

1.  In PostHog, go to the [Sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section.
2.  Click **\+ New source** and click **Link** next to this source.
3.  Enter your credentials (see [Configuration](#configuration) below) and click **Next**.
4.  Select the tables you want to sync, choose a sync method and frequency, then click **Import**.

Once the syncs are complete, you can start querying this data in PostHog.

When linking WordPress, you'll need:

-   **Site URL** – your WordPress site URL, for example `https://example.com`.
-   **Username** – optional. Required only to authenticate or sync private content.
-   **Application password** – optional. Create one under **Users > Profile > Application Passwords** ([application password docs](https://wordpress.org/documentation/article/application-passwords/)). Required only to authenticate or sync private content, and requires WordPress 5.6+ on an HTTPS site.

## Sync modes

Each table can be synced in one of several modes, depending on what the source supports:

-   **Webhook** (when available) – the source pushes changes to PostHog in real time. Fastest freshness, lowest ongoing cost, and the only mode that reliably captures updates and deletes.
-   **Incremental** – only new or updated rows are synced on each run, using a cursor field (such as an `updated_at` timestamp). Cheaper than a full refresh, but deletes aren't captured.
-   **Append only** – new rows are appended using a cursor field; existing rows are never updated. Ideal for immutable, append-only tables like event logs.
-   **Full refresh** – the whole table is reloaded on every sync. Use it when a table has no reliable cursor or when you need deletions reflected.

See [sync methods](/docs/cdp/sources.md#sync-methods) for a full explanation of how each mode works and how to choose between them.

## Configuration

| Option | Type | Required |
| --- | --- | --- |
| Site URL | text | Yes |
| Username (optional) | text | No |
| Application password (optional) | password | No |

## Supported tables

The tables available from this source are discovered from your account when you connect it, so the exact list depends on your data. Once connected, you can pick which tables to sync from the [sources tab](https://app.posthog.com/data-management/sources).

## Troubleshooting

-   If you see an authentication error, your username or application password may be invalid. Create a new application password and reconnect.
-   If you see a permissions error, check the user's role has permission to read this data, then try again.
-   If the site URL is rejected, use a publicly reachable URL, and make sure it uses HTTPS when you provide credentials.

If your sync is failing or data looks wrong, see the [Data warehouse troubleshooting guide](/docs/data-warehouse/troubleshooting.md). If that doesn't help, [contact support](https://us.posthog.com/#panel=support%3Asupport%3Adata_warehouse%3A%3Atrue) – we're happy to help.

### Was this page useful?

HelpfulCould be better