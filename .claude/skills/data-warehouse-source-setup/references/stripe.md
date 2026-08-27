> AI agents: this is one page from PostHog's docs. Full index of Markdown docs for LLMs: https://posthog.com/llms.txt

# Linking Stripe as a source - Docs

Copy page

# Linking Stripe as a source - Docs

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_9608fcca70)

![](https://res.cloudinary.com/dmukukwp6/image/upload/texture_tan_dark_a92b0e022d)

Let AI connect your sources for you

Skip the manual setup — run this in your project and the wizard auto-detects your databases and APIs and connects them to PostHog.

`npx @posthog/wizard warehouse`

[Learn more](/wizard.md)

![PostHog Wizard hedgehog](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)

![](https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png)Let AI connect your sources for you

The Stripe connector syncs your Stripe data into PostHog, including charges, customers, invoices, products, subscriptions, and more.

## Prerequisites

You need a Stripe account and either a restricted API key or an OAuth connection. For the best experience, create a restricted API key with **Write** access to **Webhooks** so PostHog can set up real-time webhook syncing for you.

## Choosing a sync mode

Stripe tables can be synced in one of three modes, and the one you pick has a big impact on cost, freshness, and correctness. We **strongly recommend using webhook syncs** for any Stripe source you care about keeping accurate:

-   **Webhook sync (recommended).** Stripe pushes events to PostHog in real time, so inserts, updates, and deletes all land within seconds. This is the only mode that reliably captures mutations to existing rows, and because PostHog only ingests what Stripe sends you, it's also the cheapest to run on an ongoing basis. See [Setting up webhooks for real-time syncing](#setting-up-webhooks-for-real-time-syncing) below.
-   **Append-only (incremental) sync.** PostHog periodically asks Stripe for new rows using Stripe's `created` cursor. This is cheap, but the Stripe API does not expose an "updated since" filter for most resources, so any change to an existing row – a subscription being cancelled, an invoice being marked paid, a customer's email being corrected – is silently missed. Fine for append-only tables you never mutate, dangerous for anything else.
-   **Full refresh sync.** PostHog re-downloads every row every sync. This is the only non-webhook mode that will eventually reflect updates, but it's expensive on both sides (lots of Stripe API calls, lots of warehouse writes) and the larger your Stripe account gets, the slower and more costly it becomes. Treat it as a fallback, not a default.

If you only take one thing from this page: connect with a restricted API key (with **Write** on **Webhook**) or OAuth and turn on webhook syncing as soon as your source is created.

## Adding a data source

1.  In PostHog, go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and select the **Sources** tab.
2.  Click **\+ New source** and select Stripe by clicking the **Link** button.
3.  Choose your authentication method:

### Option 1: Restricted API key (recommended)

1.  Select **Restricted API key** as the authentication type.
2.  Head to your Stripe dashboard > **Developers** > **API keys**, under **Restricted keys**, click [\+ Create a restricted key](https://dashboard.stripe.com/apikeys/create). You need to give your API key the following permissions:

| Resource Type | Required Permissions |
| --- | --- |
| Core | Read on Balance transaction sources, Charges and refunds, Customers, Disputes, Payment methods, Payouts, Products |
| Billing | Read on Coupons, Credit notes, Invoices, Prices, Subscriptions |
| Connect | Click Read in the Connect header |
| Webhooks | Write on Webhooks (so PostHog can create the real-time sync webhook for you – see [Setting up webhooks](#setting-up-webhooks-for-real-time-syncing)) |

If you aren't concerned with giving us more permissions than necessary, you can also simply click **Read** on the **Core**, **Billing**, and **Connect** headers, plus **Write** on **Webhooks**, to give us the necessary permissions.

The **Webhooks** write permission is only required if you want PostHog to set up real-time syncing automatically. If you skip it, everything else still works – you'll just need to [create the webhook manually](#creating-the-webhook-manually-in-stripe) later if you decide to enable real-time syncing.

If your Stripe account is in a language other than English, we suggest you update it to English before following the steps above to guarantee the correct permissions are set.

3.  Paste your API key into PostHog.
4.  *Optional:* Add your Stripe Account ID. You can find it by going to **Settings** > **Business**, selecting the [Account details](https://dashboard.stripe.com/settings/account) tab, and clicking your **Account ID** or pressing `⌘` + `I` to copy your ID.
5.  *Optional:* Add a prefix to your table names.
6.  Click **Next**.

### Option 2: OAuth connection

1.  Select **OAuth connection** as the authentication type.
2.  Click the **Connect** button and follow the prompts to authorize PostHog with your Stripe account.
3.  *Optional:* Add your Stripe Account ID. You can find it by going to **Settings** > **Business**, selecting the [Account details](https://dashboard.stripe.com/settings/account) tab, and clicking your **Account ID** or pressing `⌘` + `I` to copy your ID.
4.  *Optional:* Add a prefix to your table names.
5.  Click **Next**.

> For Stripe tables, incremental (append-only) syncs only sync new records and don't update existing ones – this is a limitation of the Stripe API, not PostHog. Full refresh syncs do pick up changes but get expensive fast as your Stripe account grows. We strongly recommend [setting up webhooks](#setting-up-webhooks-for-real-time-syncing) for real-time, change-aware syncing instead.

The data warehouse then starts syncing your Stripe data. You can see details and progress in the [data pipeline sources tab](https://app.posthog.com/data-management/sources).

## Configuration

| Option | Description |
| --- | --- |
| Authentication typeType: selectRequired: True |
| Account id (optional)Type: textRequired: False | Leave blank in most cases, including when connecting with OAuth. Only set this if you use a Stripe Connect platform key and want to sync a specific connected account. You can find it under Account details in your [Stripe account settings](https://dashboard.stripe.com/settings/account). |

## Supported tables

| Table | Description | Sync method | Incremental field | Primary key |
| --- | --- | --- | --- | --- |
| BalanceTransaction | A change to your Stripe account balance — a charge, refund, payout, or fee. | Webhook, Append only, Full refresh | created_at | — |
| Charge | A single attempt to move money into your Stripe account by charging a payment source. | Webhook, Append only, Full refresh | created_at | — |
| Customer | A Stripe customer, allowing recurring charges and tracking of payments belonging to the same person. | Webhook, Append only, Full refresh | created_at | — |
| Dispute | A customer's challenge of a charge with their card issuer (a chargeback) and its resolution. | Webhook, Append only, Full refresh | created_at | — |
| InvoiceItem | A one-off charge or credit added to a customer's upcoming invoice. | Webhook, Append only, Full refresh | date | — |
| Invoice | A statement of amounts owed by a customer, generated for subscriptions or one-off billing. | Webhook, Append only, Full refresh | created_at | — |
| Payout | A transfer of funds from your Stripe balance to your bank account or debit card. | Webhook, Append only, Full refresh | created_at | — |
| Price | How much and how often to charge for a product — its unit cost, currency, and billing interval. | Webhook, Append only, Full refresh | created_at | — |
| Product | A good or service that you sell, which prices are attached to. | Webhook, Append only, Full refresh | created_at | — |
| Refund | A refund of all or part of a charge back to the customer. | Webhook, Append only, Full refresh | created_at | — |
| Subscription | A customer's recurring billing arrangement against one or more prices. | Webhook, Append only, Full refresh | created_at | — |
| CreditNote | An adjustment to an issued invoice that reduces the amount owed or refunds the customer. | Webhook, Append only, Full refresh | created_at | — |
| CustomerBalanceTransaction | An adjustment to a single customer's credit balance (used toward or away from future invoices). | Full refresh | — | — |
| CustomerPaymentMethod | A saved payment method (card, bank account, …) attached to a customer. | Webhook, Full refresh | — | — |
| CustomerPaymentMethodHistory | One row per observed state of a customer's payment method — seeded from the attached-payment-methods sweep, then appended from payment_method.* webhook events, so detached payment methods stay queryable as they existed historically. | Webhook only | — | — |
| Coupon | A discount you can apply to customers, invoices, or subscriptions. | Webhook, Append only, Full refresh | created_at | — |
| Discount | An applied coupon — the link between a coupon and the customer, subscription, or invoice it discounts. | Webhook only | start | — |
| PaymentIntent | The full lifecycle of collecting one payment, including attempts that never became a charge. | Webhook, Append only, Full refresh | created_at | — |
| CheckoutSession | A customer's session paying through Stripe Checkout or a payment link, including sessions that were never completed. | Webhook, Append only, Full refresh | created_at | — |
| SubscriptionItem | One priced line on a subscription, so multi-product subscriptions can be split by price. | Full refresh | — | — |
| SubscriptionSchedule | A predefined plan of phased changes to a subscription over time. | Webhook, Append only, Full refresh | created_at | — |
| PromotionCode | A customer-redeemable code for a coupon, so you can see which code was actually used. | Webhook, Append only, Full refresh | created_at | — |
| Plan | The legacy pricing model for recurring purchases, superseded by Price but still widely used. | Webhook, Append only, Full refresh | created_at | — |
| TaxRate | A tax rate that can be applied to invoices, subscriptions, and Checkout Sessions. | Webhook, Append only, Full refresh | created_at | — |
| TaxId | A tax identification number registered on the account (customer-owned tax IDs live on the customer). | Webhook, Full refresh | — | — |
| Quote | A proposed set of prices for a customer that creates an invoice, subscription, or schedule once accepted. | Webhook, Full refresh | — | — |
| Event | Stripe's own log of activity in your account — a generic change feed across every resource. Stripe retains events for 30 days. | Append only, Full refresh | created_at | — |
| BillingMeter | A definition of how usage events are aggregated over a billing period for usage-based pricing. | Webhook, Full refresh | — | — |
| BillingCreditGrant | An allocation of billing credits to a customer for usage-based billing. | Webhook, Full refresh | — | — |
| BillingCreditBalanceTransaction | A credit or debit against an existing billing credit grant. | Webhook, Full refresh | — | — |
| BillingCreditBalanceSummary | A customer's current billing credit balance, scoped to one credit grant. | Full refresh | — | — |
| EntitlementsFeature | A monetizable capability in your product that customers can be entitled to. | Full refresh | — | — |
| EntitlementsActiveEntitlement | A customer's current access to a feature, granted by the products they have purchased. | Full refresh | — | — |
| InvoicePayment | A payment made against an invoice, mapping the invoice to the payment object that settled it. | Webhook, Append only, Full refresh | created_at | — |
| SetupIntent | The flow for saving a customer's payment credentials for later payments. | Webhook, Append only, Full refresh | created_at | — |
| SetupAttempt | One attempt to confirm a SetupIntent, successful or not. | Full refresh | — | — |
| PaymentLink | A shareable URL that opens a hosted payment page and can be used repeatedly. | Webhook, Full refresh | — | — |
| Transfer | A movement of funds between Stripe accounts as part of Connect. | Webhook, Append only, Full refresh | created_at | — |
| ApplicationFee | A fee a Connect platform earned on a charge made by a connected account. | Webhook, Append only, Full refresh | created_at | — |
| Topup | A top-up that adds funds to your Stripe balance. | Webhook, Append only, Full refresh | created_at | — |
| Review | A Radar review of a payment, used to supplement automated fraud detection with human decisions. | Webhook, Append only, Full refresh | created_at | — |
| EarlyFraudWarning | A notice from the card issuer that a charge may be fraudulent, usually ahead of a dispute. | Webhook, Append only, Full refresh | created_at | — |
| ShippingRate | The price of shipping presented to customers and applied to a purchase. | Append only, Full refresh | created_at | — |

## Setting up webhooks for real-time syncing

Webhook syncing is the mode we recommend for almost every Stripe source. Without it, you're choosing between append-only syncs (which silently miss updates to existing rows because Stripe's API doesn't expose an "updated since" filter) and full refresh syncs (which work but get expensive as your account grows). Webhooks avoid both problems: Stripe pushes every create, update, and delete to PostHog in real time, and PostHog only ingests what actually changed.

### Creating a webhook

1.  Go to your Stripe source in the [data pipeline sources tab](https://app.posthog.com/data-management/sources).
2.  Click the **Webhook** tab.
3.  Click **Create webhook**.

PostHog then calls the Stripe API on your behalf to create and register a webhook endpoint pointing at PostHog, subscribed to the events needed for the tables you're syncing. Once it's set up, the **Webhook** tab shows both PostHog's internal status and the Stripe-side webhook status so you can confirm events are flowing.

If creation succeeds, you don't need to do anything else – the signing secret is stored automatically and PostHog starts ingesting events immediately. When you enable additional tables later, PostHog automatically updates the webhook subscription to include the required events, so no manual intervention is needed.

### Updating your restricted API key permissions

If you connected with OAuth, PostHog already has the permissions it needs and you can skip this section.

If you connected with a restricted API key, PostHog can only create the webhook automatically if that key has **Write** access to **Webhooks**. The default read-only permissions listed above are not enough. If automatic creation fails with a permissions or `403` error, update your key:

1.  Head to your Stripe dashboard > **Developers** > **API keys**.
2.  Find the restricted key you gave to PostHog under **Restricted keys** and click it, then click **Edit key**. (If your key is locked, you'll need to create a new restricted key with the same read permissions plus the webhook write permission below, and paste the new key into your PostHog source configuration.)
3.  Under **Webhooks**, change the permission from **None** to **Write**.
4.  Save the key.
5.  Back in PostHog, return to the **Webhook** tab on your Stripe source and click **Create webhook** again.

We strongly recommend going this route rather than creating the webhook manually – PostHog will pick exactly the right set of events for the tables you're syncing, keep the signing secret in sync, and clean the webhook up if you remove the source later.

### Automatic webhook event synchronization

When you enable a new table on a Stripe source that already has a webhook, PostHog automatically adds the required events to your Stripe webhook subscription. This works when your API key has **Write** permission on **Webhooks** (or you connected via OAuth).

The sync merges events into the existing subscription – it never removes events you or someone else added manually. If the automatic sync fails (for example, a permission error or network issue), the table is still enabled and data flows once the webhook events are corrected. PostHog shows any events that still need to be added in the **Webhook** tab as a **Missing events** banner so you know exactly what to fix.

### Creating the webhook manually in Stripe

If you'd rather not grant write access to webhooks, you can create the webhook yourself in the Stripe dashboard. PostHog will detect and use it automatically once the signing secret is provided.

1.  In PostHog, go to the **Webhook** tab on your Stripe source and copy the **webhook URL** shown there. You'll paste this into Stripe in the next step.
2.  Open your [Stripe Dashboard > Developers > Webhooks](https://dashboard.stripe.com/webhooks) and click **Add endpoint**.
3.  Paste the PostHog webhook URL into the **Endpoint URL** field.
4.  Under **Events to send**, select the events you want Stripe to forward (see below).
5.  Click **Add endpoint**.
6.  On the new webhook's details page, reveal and copy the **Signing secret** (it starts with `whsec_`).
7.  Back in PostHog, paste the signing secret into the **Signing secret** field on the **Webhook** tab and save. PostHog uses this to verify that incoming events really came from Stripe.

#### Which events should you send?

We recommend **selecting all events** when creating the webhook manually. It's the simplest option, it guarantees you won't miss updates to any table you decide to sync later, and Stripe will happily deliver them – PostHog ignores any event it doesn't have a matching table for.

If you'd rather scope the webhook down to just the resources you're syncing, select every event under the prefixes that match your enabled tables:

| PostHog table | Stripe event prefix |
| --- | --- |
| Account | account.* |
| BalanceTransaction | transfer.* |
| Charge | charge.* |
| Coupon | coupon.* |
| CreditNote | credit_note.* |
| Customer | customer.* |
| CustomerBalanceTransaction | billing.* |
| CustomerPaymentMethod | payment_method.* |
| Discount | customer.discount.* |
| Dispute | dispute.* |
| Invoice | invoice.* |
| InvoiceItem | invoiceitem.* |
| Payout | payout.* |
| Price | price.* |
| Product | product.* |
| Refund | refund.* |
| Subscription | customer.subscription.* |

Narrowing events down means you'll need to revisit the webhook any time you enable a new table, which is why we still recommend **All events** unless you have a specific reason not to.

If you created the webhook manually or your API key lacks **Write** permission on **Webhooks**, PostHog can't update the subscription automatically. Instead, the **Webhook** tab shows a **Missing events** banner listing the events that need to be added. You can copy the list directly from the banner and add them in the [Stripe webhook dashboard](https://dashboard.stripe.com/webhooks).

> **Note:** The Discount table is **webhook-only** – Stripe has no API list endpoint for discounts. This means PostHog can't backfill historical discounts; only new `customer.discount.created`, `customer.discount.updated`, and `customer.discount.deleted` events are captured going forward.

### Subscription discount data

The `stripe_subscription` table includes a `discounts` JSON column. When synced via the API, this column contains full Discount objects with embedded Coupon details (`amount_off`, `percent_off`, `duration`, `duration_in_months`). Under webhook-only mode, it contains an array of discount IDs (`di_*`) instead – join to the `stripe_discount` table for full details.

If you have existing subscription data that was synced before this feature was available, re-sync (or reset your pipeline) to get the expanded discount objects.

## Troubleshooting

### Sync failing with "does not have access to account"

If your Stripe sync fails with an account access error, your API key isn't authorized for the configured account or your OAuth access has been revoked. Check the **Account id** in your source settings – it's only needed for Stripe Connect platform accounts. If you connected via OAuth, try reconnecting your Stripe account.

For more help, see the [Data Warehouse troubleshooting guide](/docs/data-warehouse/troubleshooting.md).

### Was this page useful?

HelpfulCould be better