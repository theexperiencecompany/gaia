> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Linking Shopify as a source - Docs

Copy page

# Linking Shopify as a source - Docs

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_9608fcca70)

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_dark_a92b0e022d)

Let AI connect your sources for you

Skip the manual setup — run this in your project and the wizard auto-detects your databases and APIs and connects them to PostHog.

`npx @posthog/wizard warehouse`

[Learn more](/wizard.md)

![PostHog Wizard hedgehog](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)

![](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)Let AI connect your sources for you

The Shopify connector can sync your Shopify store data into PostHog.

To sync Shopify data:

## In Shopify

1.  Go to your Shopify store's admin panel at `https://admin.shopify.com/store/your-store-id`
2.  Click **Settings**.
3.  Click **Apps and sales channels**.
4.  Click **Develop apps**.
5.  **IMPORTANT:** Click **Build apps in Dev Dashboard** (legacy apps will be deprecated January 1 2026).
6.  Click **Create app**.
7.  Give your app a name and click **Create**.
8.  You will be redirected to a screen for releasing a new version of your app. Here, you need to:
9.  Set the app URL. Use the default value `https://shopify.dev/apps/default-app-home`.
10.  Choose the app scopes. We recommend selecting all read options for the simplest setup, but only `read_orders` is required to sync core order data. See [scope requirements](#scope-requirements) for details.
11.  Click **Release** and fill in the optional release details.
12.  Go to **Home** in the Dev Dashboard and click **Install app** to install the app in your store.
13.  Go to **Settings** in the Dev Dashboard and note your `Client ID` and `Secret` for later.

For more information about creating apps in Dev Dashboard see [the Shopify docs](https://shopify.dev/docs/apps/build/dev-dashboard/create-apps-using-dev-dashboard).

## In PostHog

1.  Go to the [data pipelines page](https://app.posthog.com/data-management/sources), and select the **Sources** tab.
2.  Click the **\+ New source** button and select Shopify by clicking the **\+ Create** button.
3.  Fill in your Shopify **Store ID** – enter your store subdomain (the `my-store` part of `my-store.myshopify.com`) or paste your full store URL. Also fill in the **Client ID** and **Secret** from above.
4.  *Optional:* Add a prefix to your table names.
5.  Click **Next**.
6.  Select the Shopify objects you want to sync, and make any sync configuration changes you need.
7.  Click **Import**.

After these setup steps, your Shopify data will be automatically synced to the PostHog data warehouse. You can see details and progress in the data pipelines [sources tab](https://app.posthog.com/data-management/sources).

## Configuration

| Option | Description |
| --- | --- |
| Store idType: textRequired: True | Your store subdomain — the my-store in my-store.myshopify.com. Pasting the full store URL works too. |
| Client IDType: textRequired: True |
| SecretType: passwordRequired: True |

## Scope requirements

The `read_orders` scope is sufficient to sync core order data. However, some fields in the orders table require additional scopes:

| Field | Required scope (any one) |
| --- | --- |
| fulfillmentOrders | read_merchant_managed_fulfillment_orders, read_third_party_fulfillment_orders, or read_assigned_fulfillment_orders |
| paymentTerms | read_payment_terms |

> **Note:** If your token doesn't have these additional scopes, the orders sync still succeeds — those fields are simply omitted from the synced data. You don't need to grant extra permissions for data you don't need.

## Supported tables

| Table | Description | Sync method | Incremental field | Primary key |
| --- | --- | --- | --- | --- |
| abandonedCheckouts | A checkout a customer started but did not complete, leaving items in their cart. | Incremental, Full refresh | createdAt | — |
| articles | A blog post (article) published to one of the shop's online store blogs. | Incremental, Full refresh | updatedAt | — |
| blogs | A blog on the shop's online store that groups together articles. | Full refresh | — | — |
| catalogs | A catalog that maps a set of products and prices to a market, company location, or app. | Full refresh | — | — |
| collections | A grouping of products that can be displayed and merchandised together in the store. | Incremental, Full refresh | updatedAt | — |
| customers | A customer of the shop, holding contact details and order history. | Incremental, Full refresh | updatedAt | — |
| discountCodes | A discount and its application rules — a code or automatic discount applied at checkout. | Incremental, Full refresh | updatedAt | — |
| orders | A customer's completed request to purchase one or more products from the shop. | Incremental, Full refresh | updatedAt | — |
| products | A product the shop sells, grouping its variants, media, and selling details. | Incremental, Full refresh | updatedAt | — |

### Was this page useful?

HelpfulCould be better