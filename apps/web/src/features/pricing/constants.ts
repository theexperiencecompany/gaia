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
