// Pricing math constants — the annual-discount relationship lives here so the
// pricing cards can't encode it inconsistently.

/** Months billed up front on an annual plan. */
export const MONTHS_PER_YEAR = 12;

/** Backend prices are in cents; divide by this to get dollars. */
export const CENTS_PER_DOLLAR = 100;

/** Discount every paid annual plan carries versus paying monthly. */
const ANNUAL_DISCOUNT_RATE = 1 / 6;

/**
 * Fraction of the monthly list price an annual plan actually charges
 * (1 - ANNUAL_DISCOUNT_RATE). The pre-discount yearly list price is therefore
 * `annualPrice / ANNUAL_PRICE_RETENTION`.
 */
export const ANNUAL_PRICE_RETENTION = 1 - ANNUAL_DISCOUNT_RATE;

/**
 * localStorage key holding the plan id a logged-out user chose before being
 * sent through OAuth signup. Written on the pricing click, read by the resume
 * hook + the auth redirect gates, cleared once the checkout attempt settles.
 */
export const PENDING_CHECKOUT_KEY = "gaia_pending_checkout_plan";

/**
 * Max age of a pending checkout. Bounds the localStorage footgun: a checkout
 * abandoned at the OAuth screen must not silently fire on a much later login.
 * Generous vs the seconds-long OAuth round-trip.
 */
export const PENDING_CHECKOUT_TTL_MS = 30 * 60 * 1000;

/**
 * localStorage key holding the last product id sent to checkout, so the payment
 * result page can restart checkout for the same plan via "Try Again".
 */
export const LAST_CHECKOUT_PRODUCT_KEY = "gaia_last_checkout_product";

/**
 * Which Dodo environment the embedded overlay talks to. Mirrors the API, which
 * derives `test_mode`/`live_mode` from `ENV` (see `DodoPaymentService.__init__`)
 * — an explicit `NEXT_PUBLIC_DODO_MODE` wins so a preview build can point at
 * test mode while `NODE_ENV` is already `production`.
 */
export const DODO_CHECKOUT_MODE: "test" | "live" =
  process.env.NEXT_PUBLIC_DODO_MODE === "live"
    ? "live"
    : process.env.NEXT_PUBLIC_DODO_MODE === "test"
      ? "test"
      : process.env.NODE_ENV === "production"
        ? "live"
        : "test";

/**
 * The refund promise, shown wherever a subscription is bought. Refunds are
 * handled by email within the window — deliberately no "automatic" or
 * "instant" claim, because nothing automates it.
 */
export const REFUND_WINDOW_COPY = "Cancel within 7 days.";

/**
 * Dodo charges in the buyer's local currency and adds their local tax on top
 * of the USD list price, so the card never shows the final amount.
 */
export const TAX_NOTE_COPY = "Local taxes may apply.";

/** Enterprise is quoted, not sold self-serve: the card carries a contact CTA
 * where Pro carries checkout, with a sub-line in each slot Pro fills so the
 * two cards stay level. */
export const ENTERPRISE_PRICE_SUB_LINE = "Priced around your team";
export const ENTERPRISE_CTA_COPY = "Talk to the team";
export const ENTERPRISE_CTA_NOTE = "Volume pricing and invoicing.";

/**
 * The words every paid-only surface uses for a non-subscriber. Two audiences
 * hit the same wall for different reasons: someone whose subscription ran out
 * is being asked to come back, while a free user at the paid-only migration is
 * being told the rules changed. `has_ever_subscribed` is the only thing that
 * separates them, so the choice lives in one place — `paywallCopyFor`.
 */
export interface PaywallCopy {
  /** Modal heading and the settings plan line. */
  heading: string;
  /** One-line explanation under the heading. */
  body: string;
  /** Short button label wherever the action is offered. */
  cta: string;
  /** The modal's primary button, which names the plan. */
  subscribeCta: string;
  /** The quiet one-liner above the chat composer. */
  composer: string;
  /** Plan name shown where "GAIA Pro" would be. */
  planLabel: string;
  sidebarBody: (monthlyPrice: number) => string;
}

const LAPSED_PAYWALL_COPY: PaywallCopy = {
  heading: "Your subscription ended",
  body: "Pick up right where you left off.",
  cta: "Resubscribe",
  subscribeCta: "Resubscribe to GAIA Pro",
  composer: "Your subscription ended — resubscribe to keep chatting.",
  planLabel: "Subscription ended",
  sidebarBody: (monthlyPrice) =>
    `Resubscribe for $${monthlyPrice} a month to pick up where you left off`,
};

const MIGRATION_PAYWALL_COPY: PaywallCopy = {
  heading: "GAIA is Pro-only",
  body: "Subscribe to GAIA Pro to keep chatting and running workflows.",
  cta: "Upgrade to Pro",
  subscribeCta: "Subscribe to GAIA Pro",
  composer:
    "GAIA is paid-only right now — subscriptions cover the server costs.",
  planLabel: "Not subscribed",
  sidebarBody: (monthlyPrice) =>
    `GAIA is paid-only — subscribe for $${monthlyPrice} a month to keep using it`,
};

/** Unknown status reads as the migration audience — never as lapsed. */
export function paywallCopyFor(
  hasEverSubscribed: boolean | undefined,
): PaywallCopy {
  return hasEverSubscribed ? LAPSED_PAYWALL_COPY : MIGRATION_PAYWALL_COPY;
}

/** First gap between subscription-status polls while confirming a payment. */
export const CHECKOUT_CONFIRM_INITIAL_DELAY_MS = 1_000;

/** Each poll waits this much longer than the last, up to the cap. */
export const CHECKOUT_CONFIRM_BACKOFF_FACTOR = 1.5;

/** Ceiling on the gap between polls, so a slow webhook still gets checked often. */
export const CHECKOUT_CONFIRM_MAX_DELAY_MS = 8_000;

/**
 * How long the "Confirming your payment…" state waits before admitting the
 * webhook is late. Polling continues past this — only the copy changes.
 */
export const CHECKOUT_CONFIRM_VISIBLE_BUDGET_MS = 60_000;

/** Total time spent waiting for the webhook before giving up entirely. */
export const CHECKOUT_CONFIRM_TOTAL_BUDGET_MS = 5 * 60_000;
