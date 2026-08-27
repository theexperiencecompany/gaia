> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Linking WooCommerce as a source - Docs

Copy page

# Linking WooCommerce as a source - Docs

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

The WooCommerce connector pulls your store data – products, orders, customers, coupons, and more – into the PostHog data warehouse.

## Adding a data source

1.  Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.
2.  Click **\+ New source** and then click **Link** next to WooCommerce.
3.  Next, you need your store URL and a REST API consumer key and secret. In your WordPress admin, go to **WooCommerce** → **Settings** → **Advanced** → **REST API** and click **Add key**. Give the key at least **Read** permission and generate it – WooCommerce shows the consumer key (starts with `ck_`) and consumer secret (starts with `cs_`) once. Your store URL is the base address of your store (for example, `https://example.com`); the REST API requires HTTPS.
4.  Back in PostHog, enter your store URL in the `Store URL` field, the consumer key in the `Consumer key` field, and the consumer secret in the `Consumer secret` field, then click **Next**.
5.  Select the tables you want to sync, set the sync method and frequency, then click **Import**.

Once the syncs are complete, you can start using WooCommerce data in PostHog.

## Available tables

| Table | Description | Sync method |
| --- | --- | --- |
| products | Store products | Incremental |
| orders | Customer orders | Incremental |
| coupons | Discount coupons | Incremental |
| customers | Customers | Full refresh |
| product_categories | Product categories | Full refresh |
| product_tags | Product tags | Full refresh |
| product_reviews | Product reviews | Full refresh |
| product_attributes | Product attributes | Full refresh |
| tax_rates | Tax rates | Full refresh |
| shipping_zones | Shipping zones | Full refresh |

**Incremental** tables sync only new or updated records on each run. **Full refresh** tables reload all data on each sync.

## Sync limitations

Only `products`, `orders`, and `coupons` support incremental sync, using the WooCommerce `modified_after` filter (available in WooCommerce 5.8.0 and later). All other tables are synced as a full refresh.

## Configuration

| Option | Type | Required |
| --- | --- | --- |
| Store URL | text | Yes |
| Consumer key | text | Yes |
| Consumer secret | password | Yes |

## Supported tables

| Table | Description | Sync method | Incremental field | Primary key |
| --- | --- | --- | --- | --- |
| products | A product sold in the WooCommerce store. | Webhook, Incremental, Full refresh | date_modified_gmt | — |
| orders | A customer order placed in the WooCommerce store. | Webhook, Incremental, Full refresh | date_modified_gmt | — |
| coupons | A discount coupon configured in the WooCommerce store. | Webhook, Incremental, Full refresh | date_modified_gmt | — |
| customers | A registered customer of the WooCommerce store. | Webhook, Full refresh | — | — |
| product_categories | A category used to organize products in the WooCommerce store. | Full refresh | — | — |
| product_tags | A tag used to label products in the WooCommerce store. | Full refresh | — | — |
| product_reviews | A customer review left on a product in the WooCommerce store. | Full refresh | — | — |
| product_attributes | A global product attribute (e.g. color, size) defined in the WooCommerce store. | Full refresh | — | — |
| tax_rates | A tax rate configured in the WooCommerce store. | Full refresh | — | — |
| shipping_zones | A shipping zone that groups regions for shipping method configuration. | Full refresh | — | — |

### Was this page useful?

HelpfulCould be better